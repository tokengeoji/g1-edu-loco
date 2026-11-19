"""Read-only inspection of published camera streams and an explicitly selected USB device."""

import dataclasses
import importlib
import json
import os
import time
from collections.abc import Mapping, Sequence
from functools import partial

import numpy as np

from . import realsense
from .realsense import CameraError


RAW = "sensor_msgs/msg/Image"
COMPRESSED = "sensor_msgs/msg/CompressedImage"


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


def tty_dds(args):
    from cyclonedds.core import DDSException
    from cyclonedds.domain import DomainParticipant
    from cyclonedds.dynamic import get_types_for_typeid
    from cyclonedds.qos import Policy, Qos
    from cyclonedds.sub import DataReader, Subscriber
    from cyclonedds.topic import Topic
    from cyclonedds.util import duration

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
        if args.idl_class:
            data_type = _load_idl(args.idl_class)
        elif match.type_id is not None:
            try:
                data_type, _ = get_types_for_typeid(participant, match.type_id, duration(seconds=args.seconds))
            except DDSException as exc:
                raise CameraError(f"DDS_IDL_REQUIRED: use --idl-class with the publisher's installed IDL: {exc}") from exc
        else:
            raise CameraError("DDS_IDL_REQUIRED: writer did not advertise a type ID; supply its installed --idl-class")
        topic = Topic(participant, args.topic, data_type)
        if topic.typename != args.type:
            raise CameraError(f"DDS_TYPE_MISMATCH: selected IDL is {topic.typename}, writer uses {args.type}")
        partition = match.qos[Policy.Partition]
        subscriber = Subscriber(participant, qos=Qos(partition) if partition else None)
        qos = Qos(Policy.Reliability.BestEffort, Policy.History.KeepLast(1))
        reader = DataReader(subscriber, topic, qos=qos)
        count = 0
        next_report = 0.0
        ends = time.monotonic() + args.seconds
        while time.monotonic() < ends:
            for sample in reader.take(1):
                if not sample.sample_info.valid_data:
                    continue
                count += 1
                if time.monotonic() >= next_report:
                    fields = _field_preview(sample) if dataclasses.is_dataclass(sample) else {"idl_type": args.type}
                    print(json.dumps({"sample": count, "fields": fields}, ensure_ascii=False), flush=True)
                    next_report = time.monotonic() + 1.0
            time.sleep(0.02)
        if not count:
            raise CameraError("DDS_NO_SAMPLES: writer and type found, no valid samples received in the observation window")
        return {"status": "DDS_SAMPLES_RECEIVED", "domain": _domain_id(), "topic": args.topic,
                "type": args.type, "samples_read": count}
    except DDSException as exc:
        raise CameraError(f"DDS_INSPECTION_FAILED: {exc}") from exc


def tty_usb(args):
    state = {}
    count = 0
    next_report = 0.0

    def sample(image, info):
        nonlocal count, next_report
        count += 1
        if time.monotonic() >= next_report:
            row, col = image.shape[0] // 2, image.shape[1] // 2
            raw = int(image[row, col])
            print(json.dumps({"frame_number": info["frame_number"], "height": image.shape[0],
                              "width": image.shape[1], "encoding": "Z16", "center_depth_raw": raw or None,
                              "valid_fraction": round(np.count_nonzero(image) / image.size, 3)}), flush=True)
            next_report = time.monotonic() + 1.0

    realsense.record(args.seconds, args.width, args.height, args.fps, args.device_index, sample, state)
    return {"status": "USB_FRAMES_RECEIVED", "model": state["model"], "frames": count,
            "depth_scale_m": state["depth_scale_m"]}
