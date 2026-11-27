# Author: Codex (IIC)
"""Desktop viewer for a G1 ROS 2 image topic or the native front video topic."""
import argparse
import ipaddress
import os
import subprocess
import threading
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--address", default="192.168.123.99", type=ipaddress.IPv4Address,
                    help="local IPv4 address on the robot network")
parser.add_argument("--topic", help="preferred ROS 2 image topic")
parser.add_argument("--ros-param", nargs=2, metavar=("NODE", "PARAM"),
                    help="read the preferred ROS image topic name from this string parameter")
parser.add_argument("--domain", type=int, default=int(os.environ.get("ROS_DOMAIN_ID", 0)))
args = parser.parse_args()
os.environ["ROS_DOMAIN_ID"] = str(args.domain)
os.environ.setdefault("CYCLONEDDS_URI", '<CycloneDDS><Domain><General><Interfaces>'
                      f'<NetworkInterface address="{args.address}"/>'
                      '</Interfaces></General></Domain></CycloneDDS>')
import cv2
import numpy as np

latest = {}
stop = threading.Event()
messages = set()

def report(message):
    if message not in messages:
        messages.add(message)
        print(message, flush=True)

def ros_worker():
    try:
        import rclpy
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import Image, CompressedImage
    except ImportError as exc:
        report(f"ROS 2 image support unavailable: {exc}")
        return
    rclpy.init(args=[])
    node = rclpy.create_node("external_g1_camera_view")
    preferred = args.topic
    if args.ros_param:
        try:
            result = subprocess.run(["ros2", "param", "get", *args.ros_param],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip().startswith("String value is:"):
                preferred = result.stdout.split("String value is:", 1)[1].strip()
                report(f"Preferred ROS topic from parameter: {preferred}")
            else:
                report("ROS parameter unavailable or not a string; discovering image topics")
        except (OSError, subprocess.TimeoutExpired) as exc:
            report(f"ROS parameter lookup: {exc}")
    subscribed = {}
    def callback(topic, compressed):
        def handle(msg):
            try:
                data = np.frombuffer(msg.data, dtype=np.uint8)
                if compressed:
                    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
                else:
                    layouts = {"bgr8": (3, None), "rgb8": (3, cv2.COLOR_RGB2BGR),
                               "bgra8": (4, cv2.COLOR_BGRA2BGR), "rgba8": (4, cv2.COLOR_RGBA2BGR),
                               "mono8": (1, cv2.COLOR_GRAY2BGR)}
                    channels, conversion = layouts[msg.encoding.lower()]
                    rows = data.reshape(msg.height, msg.step)
                    frame = rows[:, :msg.width * channels].reshape(msg.height, msg.width, channels)
                    if conversion is not None:
                        frame = cv2.cvtColor(frame, conversion)
                if frame is not None and frame.size:
                    latest[topic] = (time.monotonic(), frame)
            except Exception as exc:
                report(f"Cannot display ROS image {topic}: {exc}")
        return handle
    try:
        next_scan = 0
        while not stop.is_set():
            if time.monotonic() >= next_scan:
                for topic, types in node.get_topic_names_and_types():
                    if topic in subscribed or (preferred and topic != preferred):
                        continue
                    if not preferred and any(word in topic.lower() for word in ("depth", "disparity")):
                        continue
                    for cls in (Image, CompressedImage):
                        if "sensor_msgs/msg/" + cls.__name__ in types:
                            subscribed[topic] = node.create_subscription(cls, topic,
                                callback(topic, cls is CompressedImage), qos_profile_sensor_data)
                            report(f"Listening for ROS frames on {topic}")
                            break
                next_scan = time.monotonic() + 1
            rclpy.spin_once(node, timeout_sec=.05)
    finally:
        node.destroy_node()
        rclpy.shutdown()

DDS = "rt/frontvideostream"

def dds_worker():
    try:
        from cyclonedds.builtin import BuiltinDataReader, BuiltinTopicDcpsPublication
        from cyclonedds.domain import DomainParticipant
        from cyclonedds.dynamic import get_types_for_typeid
        from cyclonedds.qos import Policy, Qos
        from cyclonedds.sub import DataReader, Subscriber
        from cyclonedds.topic import Topic
        from cyclonedds.util import duration
        import av
    except ImportError as exc:
        report(f"Native DDS video support unavailable: {exc}")
        return
    while not stop.is_set():
        try:
            participant = DomainParticipant(args.domain)
            discovery = BuiltinDataReader(participant, BuiltinTopicDcpsPublication)
            ep = None
            while ep is None and not stop.is_set():
                ep = next((p for p in discovery.take(512) if p.sample_info.valid_data
                           and p.topic_name == DDS
                           and p.type_name == "unitree_go::msg::dds_::Go2FrontVideoData_"), None)
                stop.wait(.05)
            if stop.is_set():
                return
            try:
                from unitree_sdk2py.idl.unitree_go.msg.dds_ import Go2FrontVideoData_ as sdk_type
            except ImportError:
                sdk_type = None
            if sdk_type and (ep.type_id is None or sdk_type.__idl__.get_type_id() == ep.type_id):
                dtype = sdk_type
            else:
                if ep.type_id is None:
                    raise RuntimeError("Writer has no type ID; install the matching Unitree SDK IDL")
                dtype, _ = get_types_for_typeid(participant, ep.type_id, duration(seconds=5))
                if dtype.__idl__.get_type_id() != ep.type_id:
                    raise RuntimeError("Discovered front-video type does not match the writer's type ID")
            topic = Topic(participant, DDS, dtype)
            partition = ep.qos[Policy.Partition]
            sub = Subscriber(participant, qos=Qos(partition) if partition else None)
            reader = DataReader(sub, topic, qos=Qos(Policy.Reliability.BestEffort,
                                                     Policy.History.KeepLast(32)))
            decoder = av.CodecContext.create("h264", "r")
            report("Native DDS video writer discovered")
            last_packet = time.monotonic()
            while not stop.is_set() and time.monotonic() - last_packet < 10:
                for msg in reader.take(32):
                    if not msg.sample_info.valid_data:
                        continue
                    payload = getattr(msg, "video360p", None)
                    if getattr(msg, "resolution", None) == 360:
                        payload = msg.data
                    if payload:
                        last_packet = time.monotonic()
                        for packet in decoder.parse(bytes(payload)):
                            try:
                                for frame in decoder.decode(packet):
                                    latest[DDS] = (time.monotonic(), frame.to_ndarray(format="bgr24"))
                            except ValueError:
                                continue
                stop.wait(.003)
        except Exception as exc:
            report(f"DDS receiver: {exc}")
            stop.wait(2)

def main():
    workers = [threading.Thread(target=target, daemon=True) for target in (ros_worker, dds_worker)]
    for worker in workers:
        worker.start()
    waiting = np.zeros((270, 640, 3), dtype=np.uint8)
    cv2.putText(waiting, "Waiting for ROS 2 image or DDS front video", (16, 140),
                cv2.FONT_HERSHEY_SIMPLEX, .75, (220, 220, 220), 1)
    title = "G1 camera"
    last_source = None
    try:
        while True:
            candidates = [(name, frame) for name, (stamp, frame) in latest.copy().items()
                          if time.monotonic() - stamp < 2]
            name, frame = min(candidates, key=lambda item: (item[0] == DDS,
                              "color" not in item[0].lower(), item[0]), default=(None, waiting))
            if name != last_source:
                print("Displaying " + name if name else "Waiting for fresh frames", flush=True)
                last_source = name
            cv2.imshow(title, frame)
            if cv2.waitKey(30) & 255 in (27, ord("q")) or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        stop.set()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
