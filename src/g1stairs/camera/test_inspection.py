import dataclasses
import io
import inspect
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import numpy as np

from . import inspection


def raw(encoding="16UC1", payload=b"12345678"):
    return NS(header=NS(frame_id="optical", stamp=NS(sec=2, nanosec=19)), height=2, width=2, step=4, encoding=encoding, data=payload)


class InspectionTest(unittest.TestCase):
    def test_empty_or_truncated_images_are_not_confirmed_samples(self):
        self.assertIsNone(inspection._image_metadata(inspection.RAW, raw(payload=b"123")))
        self.assertIsNone(inspection._image_metadata(inspection.COMPRESSED, raw(payload=b"")))
        self.assertEqual(inspection._image_metadata(inspection.RAW, raw())["image_kind"], "depth-compatible")

    def test_discovery_keeps_advertisements_separate_from_live_frames(self):
        ros = Mock()
        node = ros.create_node.return_value
        node.get_topic_names_and_types.return_value = [
            ("/depth", [inspection.RAW]), ("/silent", [inspection.RAW]),
        ]
        node.get_publishers_info_by_topic.return_value = [
            NS(topic_type=inspection.RAW, node_name="driver", node_namespace="/camera", qos_profile=NS(reliability=NS(name="BEST_EFFORT"))),
        ]
        callbacks = {}
        node.create_subscription.side_effect = lambda cls, name, cb, qos: callbacks.update({name: cb})
        ros.spin_once.side_effect = lambda *args, **kwargs: callbacks["/depth"](raw())
        ros.ok.side_effect = [True, False, True]
        reader = Mock()
        reader.take.return_value = [
            NS(sample_info=NS(valid_data=True), key=1, topic_name="unidentified", type_name="custom::Stream"),
        ]
        participant = Mock()
        modules = {"rclpy": ros, "rclpy.qos": NS(qos_profile_sensor_data=object()),
                   "sensor_msgs": Mock(), "sensor_msgs.msg": NS(CompressedImage=object, Image=object),
                   "cyclonedds": Mock(), "cyclonedds.domain": NS(DomainParticipant=participant)}
        with patch.dict("os.environ", {"ROS_DOMAIN_ID": "5"}), patch.dict("sys.modules", modules):
            with patch.object(inspection, "_publication_reader", return_value=reader):
                result = inspection.discover(1)
        participant.assert_called_once_with(5)
        self.assertEqual(result["domain"], 5)
        self.assertEqual(len(inspect.signature(callbacks["/depth"]).parameters), 1)
        live = result["ros_images"][0]
        self.assertEqual(live["publishers"], [{"node": "driver", "namespace": "/camera", "reliability": "BEST_EFFORT"}])
        self.assertEqual(live["last_sample"]["stamp_ns"], 2000000019)
        self.assertEqual(result["status"], "ROS_IMAGE_RECEIVED")
        self.assertEqual([row["samples_received"] for row in result["ros_images"]], [1, 0])
        self.assertEqual(result["dds_publications"], [{"topic": "unidentified", "type": "custom::Stream"}])
        node.destroy_node.assert_called_once()

    def test_dds_tty_summarizes_octets_without_printing_image(self):
        @dataclasses.dataclass
        class Frame:
            width: int
            data: bytes
        preview = inspection._field_preview(Frame(640, b"x" * 1000))
        self.assertEqual(preview, {"width": 640, "data": {"length": 1000}})

    def test_usb_tty_reports_invalid_center_and_measured_scale(self):
        def fake_record(seconds, width, height, fps, index, write, state):
            state.update(model="D435i", depth_scale_m=0.001)
            write(np.array([[0, 100], [10, 0]], dtype=np.uint16), {"frame_number": 17})
        output = io.StringIO()
        args = NS(seconds=1, width=2, height=2, fps=1, device_index=None)
        with patch.object(inspection.realsense, "record", side_effect=fake_record), redirect_stdout(output):
            result = inspection.tty_usb(args)
        row = json.loads(output.getvalue())
        self.assertIsNone(row["center_depth_raw"])
        self.assertEqual(row["valid_fraction"], 0.5)
        self.assertEqual(result["depth_scale_m"], 0.001)

    def test_check_preserves_silent_dds_and_writes_first_nonempty_usb_frame(self):
        from . import __main__ as camera_cli
        from pathlib import Path
        from tempfile import TemporaryDirectory

        def fake_record(seconds, width, height, fps, index, write, state):
            state.update(model="D435i", depth_scale_m=0.001)
            write(np.zeros((1, 3), dtype=np.uint16), {"frame_number": 15})
            image = np.array([[0, 10, 20]], dtype=np.uint16)
            write(image, {"frame_number": 16})
            image[:] = 0  # The SDK owns this memory.

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "depth.png"
            with patch.object(inspection, "discover", side_effect=RuntimeError("no ROS")), \
                 patch.object(inspection, "tty_dds", return_value={"status": "DDS_NO_SAMPLES"}), \
                 patch.object(inspection.realsense, "record", side_effect=fake_record):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = camera_cli.main(["check", "--depth-preview", str(path)])
                result = json.loads(output.getvalue())
                self.assertEqual(code, 0)
                self.assertEqual(result["ros"]["status"], "INSPECTION_FAILED")
                self.assertEqual(result["front_video_dds"]["status"], "DDS_NO_SAMPLES")
                self.assertEqual(result["usb_depth"]["frames_with_valid_depth"], 1)
                self.assertEqual(result["usb_depth"]["depth_preview"]["frame_number"], 16)
                data = path.read_bytes()
                self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertEqual(int.from_bytes(data[16:20], "big"), 3)
                self.assertEqual(int.from_bytes(data[20:24], "big"), 1)
                self.assertEqual(result["usb_depth"]["depth_preview"]["near_raw"], 10)
                self.assertEqual(result["usb_depth"]["depth_preview"]["far_raw"], 20)
                path.write_bytes(b"existing")
                with redirect_stdout(io.StringIO()):
                    code = camera_cli.main(["check", "--depth-preview", str(path)])
                self.assertEqual(code, 1)
                self.assertEqual(path.read_bytes(), b"existing")

    def test_empty_video_and_all_zero_depth_are_not_positive_checks(self):
        from . import __main__ as camera_cli
        with patch.object(inspection, "discover", return_value={"status": "NO_CONFIRMED_ROS_IMAGE"}), \
             patch.object(inspection, "tty_dds", return_value={"status": "DDS_SAMPLES_RECEIVED",
                                                                "samples_with_video_bytes": 0}), \
             patch.object(inspection, "tty_usb", return_value={"status": "USB_FRAMES_RECEIVED",
                                                                "frames_with_valid_depth": 0}), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(camera_cli.main(["check"]), 1)

    def test_front_video_counts_payloads_separately_from_valid_samples(self):
        empty = NS(sample_info=NS(valid_data=True), video720p=b"", video360p=b"", video180p=b"")
        full = NS(sample_info=NS(valid_data=True), video720p=b"", video360p=b"abc", video180p=b"")
        reader = Mock()
        reader.take.side_effect = [[empty], [full], [NS(sample_info=NS(valid_data=False))]]
        with patch.object(inspection.time, "monotonic", side_effect=[0, 0.1, 0.2, 0.3, 1]), \
             patch.object(inspection.time, "sleep"):
            counts = inspection._read_dds_samples(reader, inspection.FRONT_VIDEO_TYPE, 1, False)
        self.assertEqual(counts, (2, 1))
