"""Read a live rectified depth stream from an existing ROS 2 Foxy camera publisher."""

import time
from collections import OrderedDict

import numpy as np

from .realsense import CameraError


def _intrinsics(info, image):
    if (info.width, info.height) != (image.width, image.height) or min(image.width, image.height) < 2:
        raise CameraError("INVALID_CAMERA_INFO: CameraInfo and depth image dimensions must match")
    roi = info.roi
    if (info.binning_x not in (0, 1) or info.binning_y not in (0, 1)
            or roi.x_offset or roi.y_offset or (roi.width, roi.height) not in (
                (0, 0), (info.width, info.height))):
        raise CameraError("INVALID_CAMERA_INFO: cropped or binned calibration is unsupported")
    projection = np.asarray(info.p, dtype=float).reshape(3, 4)
    rotation = np.asarray(info.r, dtype=float).reshape(3, 3)
    fx, fy, cx, cy = projection[0, 0], projection[1, 1], projection[0, 2], projection[1, 2]
    expected = [[fx, 0, cx, 0], [0, fy, cy, 0], [0, 0, 1, 0]]
    if (not np.isfinite(projection).all() or not np.isfinite(info.k[0]) or info.k[0] <= 0
            or fx <= 0 or fy <= 0 or not np.allclose(projection, expected, rtol=0, atol=1e-8)
            or not np.allclose(rotation, np.eye(3), rtol=0, atol=1e-6)):
        raise CameraError("INVALID_CAMERA_INFO: require calibrated rectified P in the native depth frame")
    return {
        "width": int(info.width), "height": int(info.height),
        "fx": float(fx), "fy": float(fy), "cx": float(cx), "cy": float(cy),
        "distortion": "none", "coefficients": [0.0] * 5,
    }


def _image_array(image):
    if image.encoding != "16UC1" or image.step < image.width * 2:
        raise CameraError("DEPTH_FORMAT_MISMATCH: require a rectified native-depth 16UC1 image")
    if len(image.data) != image.height * image.step:
        raise CameraError("DEPTH_FORMAT_MISMATCH: data length does not match row stride")
    dtype = np.dtype(">u2" if image.is_bigendian else "<u2")
    rows = np.ndarray((image.height, image.width), dtype=dtype, buffer=image.data,
                      strides=(image.step, 2))
    return rows.astype(np.uint16, copy=False)


def record(args, write_frame, metadata):
    try:
        import rclpy
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import CameraInfo, Image
    except (ImportError, OSError) as error:
        raise CameraError("DEPENDENCY_MISSING: load the base image's Foxy environment") from error

    if args.depth_topic == args.info_topic:
        raise CameraError("INVALID_TOPICS: select distinct Image and CameraInfo topics")
    pending = {"depth": OrderedDict(), "info": OrderedDict()}
    counts = {"depth": 0, "info": 0}
    recorded = 0
    last_stamp = None
    last_arrival = None
    capture_end = None

    def receive(kind, message):
        nonlocal recorded, last_stamp, last_arrival, capture_end
        arrived = time.monotonic_ns()
        counts[kind] += 1
        header = message.header
        stamp = header.stamp.sec * 1_000_000_000 + header.stamp.nanosec
        if not header.frame_id or stamp <= 0:
            raise CameraError("INVALID_HEADER: a nonempty optical frame and acquisition stamp are required")
        key = (header.frame_id, stamp)
        other = "info" if kind == "depth" else "depth"
        partner = pending[other].pop(key, None)
        if partner is None:
            pending[kind][key] = (message, arrived)
            if len(pending[kind]) > 12:
                pending[kind].popitem(last=False)
            return
        image, image_arrival = (message, arrived) if kind == "depth" else partner
        info = message if kind == "info" else partner[0]
        if last_stamp is not None and (stamp <= last_stamp or image_arrival <= last_arrival):
            return
        if node.count_publishers(args.depth_topic) > 1 or node.count_publishers(args.info_topic) > 1:
            raise CameraError("AMBIGUOUS_ROS_SOURCE: use topics from one camera publisher per topic")
        intrinsics = _intrinsics(info, image)
        if not recorded:
            metadata.update(frame_id=header.frame_id, intrinsics=intrinsics)
        elif header.frame_id != metadata["frame_id"] or intrinsics != metadata["intrinsics"]:
            raise CameraError("CALIBRATION_CHANGED: optical frame or rectified intrinsics changed")
        write_frame(_image_array(image), {
            "frame_number": recorded, "host_rx_monotonic_ns": image_arrival,
            "ros_header_stamp_ns": stamp, "device_timestamp_ms": None,
            "device_timestamp_domain": None,
        })
        if not recorded:
            capture_end = time.monotonic() + args.seconds
        recorded += 1
        last_stamp, last_arrival = stamp, image_arrival

    rclpy.init(args=[])
    node = None
    try:
        node = rclpy.create_node("g1_depth_recorder", enable_rosout=False, start_parameter_services=False)
        node.create_subscription(Image, args.depth_topic, lambda image: receive("depth", image),
                                 qos_profile_sensor_data)
        node.create_subscription(CameraInfo, args.info_topic, lambda info: receive("info", info),
                                 qos_profile_sensor_data)
        discovery_end = time.monotonic() + args.timeout_s
        while rclpy.ok():
            remaining = (discovery_end if capture_end is None else capture_end) - time.monotonic()
            if remaining <= 0:
                break
            rclpy.spin_once(node, timeout_sec=min(0.25, remaining))
        if not rclpy.ok():
            raise CameraError("ROS_SHUTDOWN: recording interrupted")
        if not recorded:
            raise CameraError(
                "NO_MATCHED_DEPTH: no exact Image/CameraInfo pair; received "
                f"Image={counts['depth']}, CameraInfo={counts['info']}. Check the topics, DDS domain, QoS, "
                "frame_id and acquisition stamps."
            )
        metadata.update(
            depth_topic=args.depth_topic, camera_info_topic=args.info_topic, ros_image_encoding="16UC1",
            depth_scale_m=args.depth_scale_m, depth_scale_source="operator_verified_published_units",
            intrinsics_source="ros_camera_info_rectified_P", frame_number_source="recorder_sequence",
            camera_source="operator_selected_native_rectified_depth_topic",
            received_images=counts["depth"], received_camera_info=counts["info"],
            requested_seconds=args.seconds,
        )
    except RuntimeError as error:
        if isinstance(error, CameraError):
            raise
        raise CameraError(f"ROS_CAPTURE_FAILED: {error}") from error
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
