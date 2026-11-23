# Author: Codex (IIC)
"""Publish the stock D435i's native optical streams using librealsense and ROS 2."""

from array import array
from contextlib import contextmanager
import math
import sys
import time

import numpy as np

from . import realsense
from .realsense import CameraError


CAMERA_ROOT = "/g1/head"
IMAGE_NAMES = {"color": "image_raw", "depth": "image_rect_raw"}


def depth_millimetres(raw, units):
    """Convert Z16 ticks to REP 118 millimetres. Zero marks unrepresentable ranges."""
    if not math.isfinite(units) or units <= 0:
        raise CameraError("INVALID_DEPTH_SCALE: librealsense returned invalid metres per tick")
    if math.isclose(units, 0.001, rel_tol=1e-7):
        return raw
    mm = np.rint(raw.astype(np.float64) * (units * 1000.0))
    mm[mm > 65535] = 0
    return mm.astype(np.uint16)


def camera_info(profile, frame_id, message_type):
    intr = profile.get_intrinsics()
    info = message_type()
    info.header.frame_id = frame_id
    info.width, info.height = intr.width, intr.height
    fx, fy, cx, cy = intr.fx, intr.fy, intr.ppx, intr.ppy
    if (not all(math.isfinite(v) for v in (fx, fy, cx, cy, *intr.coeffs))
            or min(fx, fy) <= 0):
        raise CameraError("INVALID_CAMERA_INFO: invalid factory intrinsics for active profile")
    # Same CameraInfo projection and distortion conventions as realsense-ros.
    info.k = [fx, 0.0, cx, 0.0, fy, cy, 0.0, 0.0, 1.0]
    info.r = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    info.p = [fx, 0.0, cx, 0.0, 0.0, fy, cy, 0.0, 0.0, 0.0, 1.0, 0.0]
    fisheye = realsense._enum_name(intr.model) == "kannala_brandt4"
    info.distortion_model = "equidistant" if fisheye else "plumb_bob"
    info.d = list(intr.coeffs[:4 if fisheye else 5])
    return info


class FrameStamp:
    """Map each optical sensor's hardware clock to ROS time once per session."""

    def __init__(self):
        self.offset_ns = None
        self.last_ns = None

    def nanoseconds(self, frame, received_ns):
        ms = frame.get_timestamp()
        if not math.isfinite(ms) or ms < 0:
            raise CameraError("INVALID_FRAME_TIME: camera returned an invalid acquisition time")
        device_ns = round(ms * 1_000_000)
        domain = realsense._enum_name(frame.get_frame_timestamp_domain())
        if domain in ("global_time", "system_time"):
            return device_ns
        if domain != "hardware_clock":
            raise CameraError(f"INVALID_FRAME_TIME: unsupported clock {domain}")
        if self.offset_ns is None or device_ns < self.last_ns:
            self.offset_ns = received_ns - device_ns
        self.last_ns = device_ns
        return self.offset_ns + device_ns


def image_message(kind, frame, info, stamp, message_type):
    pixels = np.asanyarray(frame.get_data())
    if kind == "depth":
        if pixels.shape != (info.height, info.width) or pixels.dtype != np.uint16:
            raise CameraError("DEPTH_FORMAT_MISMATCH: expected a native Z16 frame")
        pixels = depth_millimetres(pixels, frame.get_units())
        encoding = "16UC1"
    else:
        if pixels.shape != (info.height, info.width, 3) or pixels.dtype != np.uint8:
            raise CameraError("COLOR_FORMAT_MISMATCH: expected a BGR8 frame")
        encoding = "bgr8"
    msg = message_type()
    msg.header.frame_id = info.header.frame_id
    msg.header.stamp = stamp
    msg.encoding = encoding
    msg.width, msg.height = info.width, info.height
    msg.is_bigendian = int(pixels.dtype.itemsize > 1 and sys.byteorder == "big")
    msg.step = info.width * (2 if kind == "depth" else 3)
    msg.data = array("B", pixels.tobytes(order="C"))
    return msg


@contextmanager
def open_camera(args, kinds):
    rs = realsense._sdk()
    try:
        context = rs.context()
        config = rs.config()
        _, model = realsense._select_device(rs, context, config, args.device_index)
        for kind in kinds:
            fmt = rs.format.z16 if kind == "depth" else rs.format.bgr8
            config.enable_stream(getattr(rs.stream, kind), args.width, args.height, fmt, args.fps)
        pipeline = rs.pipeline(context)
        profile = pipeline.start(config)
    except CameraError:
        raise
    except RuntimeError as exc:
        raise realsense._classify(exc, "STREAM_OPEN_FAILED") from exc
    try:
        profiles = {k: profile.get_stream(getattr(rs.stream, k)).as_video_stream_profile() for k in kinds}
        yield model, pipeline, profiles
    finally:
        # Preserve the acquisition error if a disconnected device also fails to stop.
        failed = sys.exc_info()[0] is not None
        try:
            pipeline.stop()
        except RuntimeError as exc:
            if not failed:
                raise realsense._classify(exc, "STREAM_CLOSE_FAILED") from exc


def start(args):
    """Run until Ctrl+C; bounded timeouts distinguish a silent stream from a running one."""
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from rclpy.time import Time
    from sensor_msgs.msg import CameraInfo, Image

    kinds = ("color", "depth") if args.stream == "both" else (args.stream,)
    rclpy.init(args=[])
    node = None
    try:
        node = rclpy.create_node("g1_head_camera", enable_rosout=False, start_parameter_services=False)
        with open_camera(args, kinds) as (model, pipeline, profiles):
            infos, publishers, clocks = {}, {}, {}
            for k in kinds:
                topic = f"{CAMERA_ROOT}/{k}"
                infos[k] = camera_info(profiles[k], f"g1_head_{k}_optical_frame", CameraInfo)
                publishers[k] = (node.create_publisher(Image, f"{topic}/{IMAGE_NAMES[k]}", qos_profile_sensor_data),
                                 node.create_publisher(CameraInfo, topic + "/camera_info", qos_profile_sensor_data))
                clocks[k] = FrameStamp()
            last_frame = {k: time.monotonic() for k in kinds}
            previous_number = dict.fromkeys(kinds)
            while rclpy.ok():
                ready, frames = pipeline.try_wait_for_frames(250)
                now = time.monotonic()
                received_ns = node.get_clock().now().nanoseconds
                for k in kinds:
                    frame = None
                    if ready:
                        frame = frames.get_depth_frame() if k == "depth" else frames.get_color_frame()
                    if frame and frame.get_frame_number() != previous_number[k]:
                        info = infos[k]
                        stamp = Time(nanoseconds=clocks[k].nanoseconds(frame, received_ns)).to_msg()
                        image = image_message(k, frame, info, stamp, Image)
                        info.header.stamp = stamp
                        publishers[k][0].publish(image)
                        publishers[k][1].publish(info)
                        last_frame[k] = now
                        if previous_number[k] is None:
                            print(f"{model} {k}: {image.width}x{image.height} {image.encoding} "
                                  f"→ {CAMERA_ROOT}/{k}/{IMAGE_NAMES[k]}", flush=True)
                        previous_number[k] = frame.get_frame_number()
                    elif now - last_frame[k] >= args.timeout_s:
                        raise CameraError(f"NO_CAMERA_FRAMES: {k} had no frame for {args.timeout_s:g} seconds")
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
