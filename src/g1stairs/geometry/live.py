# Author: Codex (IIC)
"""Show stair geometry from live D435i depth at a fixed surveyed pose."""

import math
from pathlib import Path

from g1stairs.camera import realsense, ros_depth
from g1stairs.camera.publish import CAMERA_ROOT, IMAGE_NAMES

from .projection import camera_rays, deproject, load_calibration
from .surfaces import MeasurementOptions, measure_surfaces
from .terminal import format_stairs
from .terminal_map import format_stair_map


def configure_parser(parser):
    parser.add_argument("--calibration", type=Path, required=True,
                        help="measured optical-to-gravity transform for this fixed pose")
    parser.add_argument("--source", choices=("usb", "ros"), default="usb")
    parser.add_argument("--seconds", type=float, default=10.0, help="observation time in seconds")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="minimum seconds between analyzed frames (default: 1)")
    parser.add_argument("--map", action="store_true", help="also show observed tread cells in the terminal")
    usb = parser.add_argument_group("USB D435i")
    width, height, fps = realsense.G1_DEPTH_PROFILE
    usb.add_argument("--width", type=int, help=f"depth width (default: {width})")
    usb.add_argument("--height", type=int, help=f"depth height (default: {height})")
    usb.add_argument("--fps", type=int, help=f"depth frame rate (default: {fps})")
    usb.add_argument("--device-index", type=int, help="index from g1 camera probe-usb")
    ros = parser.add_argument_group("ROS 2 rectified depth")
    ros.add_argument("--depth-topic", help=f"default: {CAMERA_ROOT}/depth/{IMAGE_NAMES['depth']}")
    ros.add_argument("--info-topic", help=f"default: {CAMERA_ROOT}/depth/camera_info")
    ros.add_argument("--depth-scale-m", type=float,
                     help="verified metres per image unit (required for --source ros)")
    ros.add_argument("--timeout-s", type=float, help="wait for the first matched image/calibration (default: 8 s)")


def run(args):
    if not all(math.isfinite(v) and v > 0 for v in (args.seconds, args.interval)):
        raise ValueError("--seconds and --interval must be finite and positive")
    if not args.calibration.is_file():
        raise ValueError(f"measured calibration file not found: {args.calibration}")
    options = MeasurementOptions(args.grid_m, args.height_tolerance_m, args.min_samples)
    # ros_depth.record replaces frame_id with the measured ROS optical frame
    # before its first callback. USB uses the existing direct capture frame ID.
    metadata = {"frame_id": "camera_depth_optical"}
    rays = calibration = None
    next_rx_ns = 0

    def show_frame(depth, sample):
        nonlocal rays, calibration, next_rx_ns
        received = sample["host_rx_monotonic_ns"]
        if received < next_rx_ns:
            return
        if rays is None:
            calibration, _ = load_calibration(args.calibration, metadata["frame_id"])
            rays = camera_rays(metadata["intrinsics"])
        points = deproject(depth, rays, metadata["depth_scale_m"], calibration)
        result = measure_surfaces(points, calibration.translation_m, calibration.ground_z_m, options)
        result.update(frame_number=sample["frame_number"], host_rx_monotonic_ns=received,
                      frame_id=calibration.frame_id)
        print(format_stairs(result), flush=True)
        if args.map:
            print(format_stair_map(result), flush=True)
        next_rx_ns = received + args.interval * 1_000_000_000

    if args.source == "ros":
        if any(v is not None for v in (args.width, args.height, args.fps, args.device_index)):
            raise ValueError("--width, --height, --fps and --device-index select USB profiles")
        if args.depth_scale_m is None or not math.isfinite(args.depth_scale_m) or args.depth_scale_m <= 0:
            raise ValueError("--source ros requires a verified positive --depth-scale-m")
        if args.timeout_s is None:
            args.timeout_s = 8.0
        elif not math.isfinite(args.timeout_s) or args.timeout_s <= 0:
            raise ValueError("--timeout-s must be finite and positive")
        args.depth_topic = args.depth_topic or f"{CAMERA_ROOT}/depth/{IMAGE_NAMES['depth']}"
        args.info_topic = args.info_topic or f"{CAMERA_ROOT}/depth/camera_info"
        metadata["depth_scale_m"] = args.depth_scale_m
        ros_depth.record(args, show_frame, metadata)
    else:
        if any(v is not None for v in (args.depth_topic, args.info_topic, args.depth_scale_m, args.timeout_s)):
            raise ValueError("use --source ros with ROS depth topics, --depth-scale-m or --timeout-s")
        if args.device_index is not None and args.device_index < 0:
            raise ValueError("--device-index must be nonnegative")
        profile = tuple(default if value is None else value for default, value in
                        zip(realsense.G1_DEPTH_PROFILE, (args.width, args.height, args.fps)))
        if min(profile) <= 0:
            raise ValueError("--width, --height and --fps must be positive")
        realsense.record(args.seconds, *profile, args.device_index, show_frame, metadata)
