"""Read-only inspection of published camera streams and an explicitly selected USB device."""

import dataclasses
import importlib
import json
import os
import time
from collections.abc import Mapping, Sequence
from functools import partial
from tempfile import NamedTemporaryFile
from types import SimpleNamespace

import numpy as np

from . import realsense
from .realsense import CameraError


RAW = "sensor_msgs/msg/Image"
COMPRESSED = "sensor_msgs/msg/CompressedImage"
FRONT_VIDEO_TOPIC = "rt/frontvideostream"
FRONT_VIDEO_TYPE = "unitree_go::msg::dds_::Go2FrontVideoData_"
FRONT_VIDEO_IDL = "unitree_sdk2py.idl.unitree_go.msg.dds_:Go2FrontVideoData_"


def _image_metadata(kind, image):
    stamp = image.header.stamp
    result = {"frame_id": image.header.frame_id, "stamp_ns": stamp.sec * 10**9 + stamp.nanosec,
              "payload_bytes": len(image.data)}
    if len(image.data) == 0:
        return None
    if kind == COMPRESSED:
        return dict(result, format=image.format, transport="compressed")

    if min(image.width, image.height, image.step) < 1 or len(image.data) != image.step * image.height:
        return None
    encoding = image.encoding.lower()
    if encoding in ("16uc1", "32fc1"):
        description = "depth-compatible"
    elif encoding.startswith(("rgb", "bgr", "yuv", "bayer", "uyvy")):
        description = "color"
    else:
        description = "other"
    return dict(result, width=image.width, height=image.height, encoding=image.encoding,
                image_kind=description, transport="raw")


def _received(row, kind, image):
    metadata = _image_metadata(kind, image)
    if metadata is not None:
        row["samples_received"] += 1
        row["last_sample"] = metadata


def _domain_id():
    return int(os.getenv("ROS_DOMAIN_ID", "0"))


def _publication_reader(participant):
    from cyclonedds.builtin import BuiltinDataReader, BuiltinTopicDcpsPublication
    return BuiltinDataReader(participant, BuiltinTopicDcpsPublication)


def _refresh_publications(reader, endpoints):
    for endpoint in reader.take(256):
        if endpoint.sample_info.valid_data:
            endpoints[endpoint.key] = endpoint
        else:
            endpoints.pop(endpoint.key, None)


def discover(seconds):
    """Report publisher advertisements separately from sensor_msgs frames actually received."""
    import rclpy
    from cyclonedds.domain import DomainParticipant
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import CompressedImage, Image

    types = {RAW: Image, COMPRESSED: CompressedImage}
    participant = publications = None
    endpoints = {}
    streams = {}
    rclpy.init(args=[])
    node = None
    try:
        node = rclpy.create_node("g1_camera_inspection", enable_rosout=False, start_parameter_services=False)
        # Foxy RMW creates the DDS domain explicitly. Attach the native reader afterwards.
        participant = DomainParticipant(_domain_id())
        publications = _publication_reader(participant)
        end = time.monotonic() + seconds
        next_scan = 0
        while rclpy.ok() and time.monotonic() < end:
            _refresh_publications(publications, endpoints)
            if time.monotonic() >= next_scan:
                next_scan = time.monotonic() + 0.4
                for name, topic_types in node.get_topic_names_and_types():
                    for kind in types.keys() & set(topic_types):
                        if (name, kind) in streams:
                            continue
                        publishers = [p for p in node.get_publishers_info_by_topic(name) if p.topic_type == kind]
                        if not publishers:
                            continue
                        row = {
                            "topic": name, "type": kind, "samples_received": 0,
                            "publishers": [{"node": p.node_name, "namespace": p.node_namespace,
                                            "reliability": p.qos_profile.reliability.name} for p in publishers],
                        }
                        streams[name, kind] = row
                        node.create_subscription(types[kind], name, partial(_received, row, kind),
                                                 qos_profile_sensor_data)
            rclpy.spin_once(node, timeout_sec=max(0.0, min(0.1, end - time.monotonic())))
        _refresh_publications(publications, endpoints)
    finally:
        publications = participant = None
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    names = sorted({(ep.topic_name, ep.type_name) for ep in endpoints.values()})
    rows = [streams[key] for key in sorted(streams)]
    return {
        "status": "ROS_IMAGE_RECEIVED" if any(r["samples_received"] for r in rows) else "NO_CONFIRMED_ROS_IMAGE",
        "domain": _domain_id(), "seconds": seconds, "ros_images": rows,
        "dds_publications": [{"topic": name, "type": kind} for name, kind in names],
    }


def _field_preview(sample):
    """Summarize top-level IDL fields without dumping image payloads to the terminal."""
    result = {}
    for field in dataclasses.fields(sample):
        value = getattr(sample, field.name)
        if isinstance(value, str):
            result[field.name] = value[:120]
        elif isinstance(value, (Sequence, Mapping)):
            result[field.name] = {"length": len(value)}
        elif isinstance(value, (float, int, bool)) or value is None:
            result[field.name] = str(value) if isinstance(value, float) and not np.isfinite(value) else value
        else:
            result[field.name] = type(value).__name__
    return result


def _load_idl(qualified_name):
    module_name, separator, class_name = qualified_name.partition(":")
    if not separator or not module_name or not class_name:
        raise CameraError("IDL_CLASS_INVALID: use an installed MODULE:CLASS from the publisher's IDL")
    try:
        return getattr(importlib.import_module(module_name), class_name)
    except (AttributeError, ImportError) as error:
        raise CameraError(f"IDL_CLASS_UNAVAILABLE: {qualified_name}: {error}") from error


def _writer_type(participant, writer, idl_class, seconds):
    from cyclonedds.core import DDSException
    from cyclonedds.dynamic import get_types_for_typeid
    from cyclonedds.util import duration

    front = (writer.topic_name, writer.type_name) == (FRONT_VIDEO_TOPIC, FRONT_VIDEO_TYPE)
    if idl_class or front:
        try:
            selected = _load_idl(idl_class or FRONT_VIDEO_IDL)
        except CameraError:
            if idl_class or writer.type_id is None:
                raise
        else:
            if writer.type_id is None or selected.__idl__.get_type_id() == writer.type_id:
                return selected, "explicit" if idl_class else "unitree_sdk"
            if idl_class:
                raise CameraError("DDS_TYPE_MISMATCH: selected IDL differs from the writer's advertised "
                                  "type identifier; omit --idl-class to use the writer's definition")
    if writer.type_id is None:
        raise CameraError("DDS_IDL_REQUIRED: writer did not advertise a type ID; supply its installed --idl-class")
    try:
        selected, _ = get_types_for_typeid(participant, writer.type_id, duration(seconds=seconds))
    except DDSException as exc:
        raise CameraError(f"DDS_IDL_REQUIRED: cannot resolve the writer's advertised type; "
                          f"supply its matching installed --idl-class: {exc}") from exc
    if selected.__idl__.get_type_id() != writer.type_id:
        raise CameraError("DDS_TYPE_MISMATCH: discovered definition differs from the writer's advertised type ID")
    return selected, "writer_type"


def _read_dds_samples(reader, typename, seconds, verbose):
    front_video = typename == FRONT_VIDEO_TYPE
    payload_samples = 0
    count = 0
    next_report = 0.0
    ends = time.monotonic() + seconds
    while time.monotonic() < ends:
        for sample in reader.take(1):
            if not sample.sample_info.valid_data:
                continue
            count += 1
            if front_video:
                # The lab writer exposes resolution/data. The pinned Unitree IDL has three streams.
                if hasattr(sample, "resolution") and hasattr(sample, "data"):
                    payload_samples += bool(sample.data)
                else:
                    payload_samples += any(getattr(sample, field, ()) for field in
                                           ("video720p", "video360p", "video180p"))
            if verbose and time.monotonic() >= next_report:
                fields = _field_preview(sample) if dataclasses.is_dataclass(sample) else {"idl_type": typename}
                print(json.dumps({"sample": count, "fields": fields}, ensure_ascii=False), flush=True)
                next_report = time.monotonic() + 1.0
        time.sleep(0.02)
    return count, payload_samples


def tty_dds(args, *, verbose=True):
    from cyclonedds.core import DDSException, Listener
    from cyclonedds.domain import DomainParticipant
    from cyclonedds.qos import Policy, Qos
    from cyclonedds.sub import DataReader, Subscriber
    from cyclonedds.topic import Topic

    participant = DomainParticipant(_domain_id())
    publications = _publication_reader(participant)
    ends = time.monotonic() + args.seconds
    try:
        while True:
            match = next((ep for ep in publications.take(256) if ep.sample_info.valid_data
                          and ep.topic_name == args.topic and ep.type_name == args.type), None)
            if match is not None:
                break
            if time.monotonic() >= ends:
                raise CameraError("DDS_WRITER_NOT_FOUND: check the topic, type, domain and interface")
            time.sleep(0.05)
        data_type, idl_source = _writer_type(participant, match, args.idl_class, args.seconds)
        topic = Topic(participant, args.topic, data_type)
        if topic.typename != args.type:
            raise CameraError(f"DDS_TYPE_MISMATCH: selected IDL is {topic.typename}, writer uses {args.type}")
        partition = match.qos[Policy.Partition]
        subscriber = Subscriber(participant, qos=Qos(partition) if partition else None)
        qos = Qos(Policy.Reliability.BestEffort, Policy.History.KeepLast(1))
        matches = {"total": 0, "incompatible_qos": 0}

        def matched(_reader, status):
            matches["total"] = status.total_count

        def incompatible(_reader, status):
            matches["incompatible_qos"] = status.total_count

        listener = Listener(on_subscription_matched=matched, on_requested_incompatible_qos=incompatible)
        reader = DataReader(subscriber, topic, qos=qos, listener=listener)
        count, payload_samples = _read_dds_samples(reader, args.type, args.seconds, verbose)
        if not count and verbose:
            raise CameraError(f"DDS_NO_SAMPLES: writer and type found, no valid samples; "
                              f"reader matches={matches['total']}, incompatible QoS events={matches['incompatible_qos']}")
        result = {"status": "DDS_SAMPLES_RECEIVED" if count else "DDS_NO_SAMPLES", "idl_source": idl_source,
                  "domain": _domain_id(), "topic": args.topic, "type": args.type, "samples_read": count,
                  "reader_matches": matches["total"], "incompatible_qos_events": matches["incompatible_qos"]}
        if args.type == FRONT_VIDEO_TYPE:
            result["samples_with_video_bytes"] = payload_samples
        return result
    except DDSException as exc:
        raise CameraError(f"DDS_INSPECTION_FAILED: {exc}") from exc


def save_depth_preview(path, image):
    """Write an 8-bit PNG for inspection; reserve black for missing depth."""
    valid = image != 0
    depths = image[valid]
    if not depths.size:
        raise ValueError("this frame has no valid depth")
    near, far = int(depths.min()), int(depths.max())
    pixels = np.zeros_like(image, dtype=np.uint8)
    pixels[valid] = 255 - 254 * (depths.astype(float) - near) / max(1, far - near)
    with NamedTemporaryFile(dir=path.parent) as stream:
        try:
            import cv2
        except ImportError:
            # Also support offline inspection environments with Pillow.
            from PIL import Image
            Image.fromarray(pixels).save(stream, format="PNG")
        else:
            try:
                ok, encoded = cv2.imencode(".png", pixels)
            except cv2.error as error:
                raise OSError(f"OpenCV could not encode the depth preview: {error}") from error
            if not ok:
                raise OSError("OpenCV could not encode the depth preview")
            stream.write(encoded.tobytes())
        stream.flush()
        os.link(stream.name, path)  # Publish only the complete preview and preserve existing files.
    return {"path": str(path), "near_raw": near, "far_raw": far}


def tty_usb(args, *, verbose=True, preview_path=None):
    state = {}
    count = frames_with_depth = 0
    first_valid = None
    next_report = 0.0

    def sample(image, info):
        nonlocal count, frames_with_depth, first_valid, next_report
        count += 1
        valid = np.count_nonzero(image)
        if valid:
            frames_with_depth += 1
            if preview_path is not None and first_valid is None:
                first_valid = (info["frame_number"], image.copy())
        if verbose and time.monotonic() >= next_report:
            row, col = image.shape[0] // 2, image.shape[1] // 2
            raw = int(image[row, col])
            print(json.dumps({"frame_number": info["frame_number"], "height": image.shape[0],
                              "width": image.shape[1], "encoding": "Z16", "center_depth_raw": raw or None,
                              "valid_fraction": round(valid / image.size, 3)}), flush=True)
            next_report = time.monotonic() + 1.0

    realsense.record(args.seconds, args.width, args.height, args.fps, args.device_index, sample, state)
    result = {"status": "USB_FRAMES_RECEIVED", "model": state["model"], "frames": count,
              "frames_with_valid_depth": frames_with_depth, "depth_scale_m": state["depth_scale_m"]}
    if first_valid is not None:
        number, image = first_valid
        try:
            result["depth_preview"] = dict(save_depth_preview(preview_path, image), frame_number=number)
        except (ImportError, OSError, RuntimeError) as error:
            result["preview_error"] = str(error)
    return result


def _inspect_source(function, *args, **kwargs):
    """A failed transport should not prevent testing a second independent input."""
    try:
        return function(*args, **kwargs)
    except CameraError as error:
        status, _, detail = str(error).partition(": ")
        return {"status": status, "detail": detail}
    except Exception as error:
        # DDS and ROS each define native exception types. Preserve their reason
        # here and continue to the independent transports.
        return {"status": "INSPECTION_FAILED", "error_type": type(error).__name__, "detail": str(error)}


def check(args):
    ros = _inspect_source(discover, args.seconds)
    # `discover` keeps the full DDS endpoint list; this report tests the front
    # video endpoint directly, independently of ROS discovery.
    ros.pop("dds_publications", None)
    dds_args = SimpleNamespace(topic=FRONT_VIDEO_TOPIC, type=FRONT_VIDEO_TYPE, idl_class=None, seconds=args.seconds)
    dds = _inspect_source(tty_dds, dds_args, verbose=False)
    usb = _inspect_source(tty_usb, args, verbose=False, preview_path=args.depth_preview)
    return {"domain": _domain_id(), "interface": os.getenv("G1_CAMERA_IFACE") or None,
            "ros": ros, "front_video_dds": dds, "usb_depth": usb}
