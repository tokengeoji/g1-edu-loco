# Author: Codex (IIC)
"""Watch G1 ROS images and receive a read-only ROS stream over a wired SSH tunnel."""
import argparse
from contextlib import closing
from dataclasses import dataclass
from functools import partial
import socket
import struct
import sys
import time

import numpy as np


@dataclass(frozen=True)
class Channel:
    option: str
    default_topic: str
    local_topic: str
    type_name: str
    max_bytes: int


IMAGE_LIMIT = 16 * 1024 * 1024
CHANNELS = {
    1: Channel("color_topic", "/g1/head/color/image_raw", "/g1_remote/color/image_raw", "Image", IMAGE_LIMIT),
    2: Channel("depth_topic", "/g1/head/depth/image_rect_raw", "/g1_remote/depth/image_rect_raw", "Image", IMAGE_LIMIT),
    3: Channel("color_info_topic", "/g1/head/color/camera_info", "/g1_remote/color/camera_info", "CameraInfo", 65536),
    4: Channel("depth_info_topic", "/g1/head/depth/camera_info", "/g1_remote/depth/camera_info", "CameraInfo", 65536),
    5: Channel("state_topic", "/lowstate", "/g1_remote/lowstate", "LowState", 65536),
}
MAGIC = b"G1VIEW\x01\n"
HEADER = struct.Struct("!BI")
KEEPALIVE = HEADER.pack(0, 0)
LOOPBACK = "127.0.0.1"
PORT = 8766


def message_types():
    from sensor_msgs.msg import Image, CameraInfo
    from unitree_hg.msg import LowState
    return {"Image": Image, "CameraInfo": CameraInfo, "LowState": LowState}


def read_exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise EOFError("Relay or SSH tunnel closed before the next complete message.")
    return data


def read_packet(stream):
    channel_id, size = HEADER.unpack(read_exact(stream, HEADER.size))
    if channel_id == 0 and size == 0:
        return 0, b""
    channel = CHANNELS.get(channel_id)
    if channel is None or not 0 < size <= channel.max_bytes:
        raise ValueError("Invalid relay channel or message size.")
    return channel_id, read_exact(stream, size)


def send_samples(ros, node, peer, args, types):
    from rclpy.qos import QoSProfile, QoSReliabilityPolicy

    # Keep at most one sample per input while the operator's link is slow.
    qos = QoSProfile(depth=1, reliability=QoSReliabilityPolicy.BEST_EFFORT)
    subscriptions = []
    next_send = {}
    last_write = time.monotonic()

    def forward(channel_id, data):
        nonlocal last_write
        now = time.monotonic()
        channel = CHANNELS[channel_id]
        # CameraInfo is small; keep headers for the images that survive throttling.
        if channel.type_name != "CameraInfo" and now < next_send.get(channel_id, 0):
            return
        if not 0 < len(data) <= channel.max_bytes:
            raise ValueError(f"{channel.default_topic}: CDR size outside supported range")
        peer.sendall(HEADER.pack(channel_id, len(data)))
        peer.sendall(data)
        next_send[channel_id] = now + 1.0 / args.hz
        last_write = now

    try:
        peer.settimeout(2)
        peer.sendall(MAGIC)
        for channel_id, channel in CHANNELS.items():
            subscriptions.append(node.create_subscription(
                types[channel.type_name], getattr(args, channel.option),
                partial(forward, channel_id), qos, raw=True))
        while ros.ok():
            ros.spin_once(node, timeout_sec=0.15)
            if time.monotonic() - last_write >= 2:
                peer.sendall(KEEPALIVE)
                last_write = time.monotonic()
    finally:
        for subscription in subscriptions:
            node.destroy_subscription(subscription)


def serve(ros, node, args):
    types = message_types()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((LOOPBACK, args.port))
        listener.listen(1)
        listener.settimeout(0.5)
        print(f"G1 read-only relay on {LOOPBACK}:{args.port}; waiting for SSH forwarding.", flush=True)
        while ros.ok():
            try:
                peer, _ = listener.accept()
            except socket.timeout:
                continue
            with closing(peer):
                print("Viewer connected.", flush=True)
                try:
                    send_samples(ros, node, peer, args, types)
                except (ConnectionError, socket.timeout) as error:
                    print(f"Viewer disconnected ({error}). Waiting for the next connection.", flush=True)


def receive(ros, node, args):
    from rclpy.serialization import deserialize_message

    types = message_types()
    publishers = {}
    with socket.create_connection((LOOPBACK, args.port), timeout=8) as peer, peer.makefile("rb") as stream:
        if read_exact(stream, len(MAGIC)) != MAGIC:
            raise ValueError("Unknown relay protocol; use matching versions on PC2 and the development PC.")
        print("Relay connected. Waiting for the first sample of each channel.", flush=True)
        while ros.ok():
            channel_id, data = read_packet(stream)
            if channel_id == 0:
                continue
            channel = CHANNELS[channel_id]
            msg_type = types[channel.type_name]
            # Decode against the locally installed ROS type before publishing.
            msg = deserialize_message(data, msg_type)
            if channel.type_name == "Image" and (
                not msg.width or not msg.height or not msg.step or len(msg.data) != msg.step * msg.height
            ):
                raise ValueError(f"Invalid Image dimensions on {channel.local_topic}")
            if channel_id not in publishers:
                publishers[channel_id] = node.create_publisher(msg_type, channel.local_topic, 3)
                print(f"Received {channel.type_name} -> {channel.local_topic}", flush=True)
            publishers[channel_id].publish(msg)


def render_image(msg, columns, rows):
    """Downsample actual pixels, accounting for channel order, row stride and byte order."""
    encoding = msg.encoding.lower()
    formats = {"rgb8": ("u1", 3), "bgr8": ("u1", 3), "rgba8": ("u1", 4), "bgra8": ("u1", 4),
               "mono8": ("u1", 1), "8uc1": ("u1", 1), "mono16": ("u2", 1),
               "16uc1": ("u2", 1), "32fc1": ("f4", 1)}
    if encoding not in formats:
        raise ValueError(f"Unsupported TTY encoding {msg.encoding!r}. Choose an RGB or depth Image topic.")
    format_code, channels = formats[encoding]
    dtype = np.dtype((">" if msg.is_bigendian else "<") + format_code)
    width, height, step = int(msg.width), int(msg.height), int(msg.step)
    if (width <= 0 or height <= 0 or step < width * channels * dtype.itemsize
            or step * height != len(msg.data) or len(msg.data) > IMAGE_LIMIT):
        raise ValueError("Invalid ROS image dimensions or row stride.")
    image = np.ndarray((height, width, channels), dtype=dtype, buffer=msg.data,
                       strides=(step, channels * dtype.itemsize, dtype.itemsize))
    width_chars = min(columns, width, max(1, round(rows * 2 * width / height)))
    height_chars = min(rows, height, max(1, round(width_chars * height / width / 2)))
    x = np.linspace(0, width - 1, width_chars, dtype=int)
    y = np.linspace(0, height - 1, height_chars, dtype=int)
    pixels = image[y[:, None], x].astype(np.float32)
    if channels >= 3:
        rgb = pixels[..., :3]
        if encoding.startswith("bgr"):
            rgb = rgb[..., ::-1]
        light = (rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)) / 255
    elif format_code == "u1":
        light = pixels[..., 0] / 255
    else:
        depth = pixels[..., 0]
        valid = np.isfinite(depth) & (depth > 0)
        light = np.zeros(depth.shape, dtype=np.float32)
        if valid.any():
            near, far = float(depth[valid].min()), float(depth[valid].max())
            light[valid] = 1 - 0.85 * (depth[valid] - near) / max(1e-12, far - near)
    ramp = np.array(list(" .:-=+*#%@"))
    chars = ramp[np.rint(np.clip(light, 0, 1) * (len(ramp) - 1)).astype(int)]
    return "\n".join("".join(row) for row in chars)


def tty_view(ros, node, args):
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image

    last_image = time.monotonic()
    rendered = False

    def show(msg):
        nonlocal last_image, rendered
        now = time.monotonic()
        if rendered and now - last_image < 0.2:
            return
        preview = render_image(msg, args.columns, args.rows)
        stamp = msg.header.stamp
        title = f"{args.topic}  {msg.width}x{msg.height} {msg.encoding}  {stamp.sec}.{stamp.nanosec:09}"
        prefix = "\x1b[H\x1b[J" if sys.stdout.isatty() and not args.once else ""
        print(prefix + title + "\n" + preview, flush=True)
        last_image = now
        rendered = True

    node.create_subscription(Image, args.topic, show, qos_profile_sensor_data)
    print(f"Waiting for Image on {args.topic}", file=sys.stderr, flush=True)
    while ros.ok():
        ros.spin_once(node, timeout_sec=0.2)
        if args.once and rendered:
            return
        if time.monotonic() - last_image > args.timeout:
            raise RuntimeError(f"No new image for {args.timeout:g} s on {args.topic}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="g1 camera remote", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    server = commands.add_parser("serve", help="PC2: send selected ROS topics over the local SSH endpoint")
    client = commands.add_parser("receive", help="Windows container: publish received samples on /g1_remote")
    terminal = commands.add_parser("tty", help="Render actual ROS Image pixels as terminal grayscale")
    for cmd in (server, client):
        cmd.add_argument("--port", type=int, default=PORT, help="loopback TCP port (default 8766)")
    for ch in CHANNELS.values():
        server.add_argument("--" + ch.option.replace("_", "-"), default=ch.default_topic, help=ch.default_topic)
    server.add_argument("--hz", type=float, default=5.0, help="maximum rate per image and state channel (default 5 Hz)")
    terminal.add_argument("--topic", default=CHANNELS[1].local_topic)
    terminal.add_argument("--columns", type=int, default=72)
    terminal.add_argument("--rows", type=int, default=24)
    terminal.add_argument("--once", action="store_true", help="print one frame and exit")
    terminal.add_argument("--timeout", type=float, default=10, help="fail if no new Image within this many seconds")
    args = parser.parse_args(argv)
    if args.command == "tty":
        if not (1 <= args.columns <= 300 and 1 <= args.rows <= 150 and 0 < args.timeout <= 3600):
            parser.error("Use 1..300 columns, 1..150 rows and a timeout in (0, 3600].")
    elif not (1 <= args.port <= 65535):
        parser.error("Use a TCP port from 1 through 65535.")
    elif args.command == "serve" and not 0 < args.hz <= 60:
        parser.error("Use a transmit rate in (0, 60] Hz.")

    import rclpy
    rclpy.init(args=[])
    node = rclpy.create_node("g1_remote_" + args.command)
    try:
        {"serve": serve, "receive": receive, "tty": tty_view}[args.command](rclpy, node, args)
    except KeyboardInterrupt:
        pass
    except (OSError, EOFError, ValueError, RuntimeError, ImportError) as error:
        print(f"g1 camera remote {args.command}: {error}", file=sys.stderr)
        return 1
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
