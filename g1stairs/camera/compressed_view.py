"""Decode a live ROS 2 CompressedImage for RViz using the standard Foxy plugins."""

import argparse
from pathlib import Path
import subprocess
import sys
import uuid


VIEW_TOPIC = "/g1_jsj/view_image"


def decoder_transport(image_format):
    format_lower = image_format.lower()
    if "compresseddepth" in format_lower:
        if "rvl" in format_lower:
            raise ValueError("The Foxy compressedDepth decoder supports PNG. The publisher reports RVL.")
        return "compressedDepth"
    return "compressed"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topic", help="Absolute ROS 2 sensor_msgs/msg/CompressedImage topic")
    args = parser.parse_args(argv)
    if not args.topic.startswith("/") or args.topic == VIEW_TOPIC:
        parser.error(f"Use an absolute input topic distinct from {VIEW_TOPIC}")

    import rclpy
    from ament_index_python.packages import get_package_prefix
    from rclpy.qos import QoSProfile, QoSReliabilityPolicy, qos_profile_sensor_data
    from sensor_msgs.msg import CompressedImage

    decoder = Path(get_package_prefix("image_transport")) / "lib/image_transport/republish"
    if not decoder.is_file():
        parser.exit(1, f"Missing Foxy image_transport executable: {decoder}\n")

    rclpy.init(args=[])
    suffix = uuid.uuid4().hex[:12]
    node = rclpy.create_node(f"g1_compressed_view_{suffix}")
    relay_topic = f"/_g1_jsj/decoder_{suffix}/input"
    process = None
    transport = None
    pending = None
    try:
        # Foxy's stock republish requests RELIABLE input. Receive the actual
        # sensor stream with BEST_EFFORT and relay the original message locally.
        relay = node.create_publisher(
            CompressedImage, relay_topic,
            QoSProfile(depth=2, reliability=QoSReliabilityPolicy.RELIABLE),
        )

        def receive(message):
            nonlocal pending, process, transport
            chosen = decoder_transport(message.format)
            if process is None:
                transport = chosen
                process = subprocess.Popen([
                    str(decoder), transport, "raw", "--ros-args",
                    "-r", f"in/{transport}:={relay_topic}", "-r", f"out:={VIEW_TOPIC}",
                    "-r", f"__node:=g1_decoder_{suffix}",
                ], start_new_session=True)
                print(f"{args.topic} ({message.format}) -> {VIEW_TOPIC}", flush=True)
            elif chosen != transport:
                raise RuntimeError("Publisher switched transport. Restart the viewer for the new codec.")
            pending = message

        node.create_subscription(CompressedImage, args.topic, receive, qos_profile_sensor_data)
        print(f"Waiting for a CompressedImage on {args.topic}", flush=True)
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.1)
            if process is not None and process.poll() is not None:
                raise RuntimeError(f"Foxy decoder exited with status {process.returncode}")
            # Keep the latest input while DDS discovers the decoder. This also
            # works when the sensor sends just one frame during startup.
            if pending is not None and relay.get_subscription_count():
                relay.publish(pending)
                pending = None
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
