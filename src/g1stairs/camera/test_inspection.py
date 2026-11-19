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
