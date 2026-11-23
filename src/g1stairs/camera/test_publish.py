# Author: Codex (IIC)
import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import numpy as np

from . import __main__ as cli, publish, realsense
from .test_realsense import _device, _sdk


class Message:
    def __init__(self):
        self.header = NS()


def frame(pixels, ms, units=None):
    data = Mock()
    data.get_data.return_value = pixels
    data.get_timestamp.return_value = ms
    data.get_frame_timestamp_domain.return_value = "hardware_clock"
    data.get_frame_number.return_value = 501
    data.get_units.return_value = units
    return data


class LiveCameraTests(unittest.TestCase):
    def test_camera_clock_preserves_sensor_interval_despite_receive_jitter(self):
        clock = publish.FrameStamp()
        f = frame(None, 1250)
        self.assertEqual(clock.nanoseconds(f, 4_000_000_000), 4_000_000_000)
        f.get_timestamp.return_value = 1300
        self.assertEqual(clock.nanoseconds(f, 5_000_000_000), 4_050_000_000)
        f.get_frame_timestamp_domain.return_value = "system_time"
        self.assertEqual(clock.nanoseconds(f, 5_000_000_000), 1_300_000_000)

    def test_z16_converts_native_measurement_to_representable_millimetres(self):
        img = np.array([[0, 2, 8, 65535]], dtype=np.uint16)
        self.assertIs(publish.depth_millimetres(img, np.float32(0.001)), img)
        np.testing.assert_array_equal(publish.depth_millimetres(img, 0.002), [[0, 4, 16, 0]])
        np.testing.assert_array_equal(publish.depth_millimetres(img, 0.00025), [[0, 0, 2, 16384]])
        with self.assertRaisesRegex(realsense.CameraError, "INVALID_DEPTH_SCALE"):
            publish.depth_millimetres(img, float("nan"))

    def setUp(self):
        self.sdk = _sdk(_device("Intel RealSense D435i"))
        self.sdk.stream.color, self.sdk.format.bgr8 = "color", "bgr8"
        self.pipe = self.sdk.pipeline.return_value
        profile = self.pipe.start.return_value.get_stream.return_value.as_video_stream_profile.return_value
        profile.get_intrinsics.return_value = NS(width=2, height=1, fx=1.5, fy=1.6, ppx=0.5, ppy=0.6,
                                                 coeffs=[0.0]*5, model="none")
        self.color = frame(np.array([[[2, 4, 8], [1, 3, 5]]], dtype=np.uint8), 100)
        self.depth = frame(np.array([[0, 183]], dtype=np.uint16), 101, 0.002)
        self.frames = NS(get_depth_frame=lambda: self.depth, get_color_frame=lambda: self.color)
        self.ros = Mock()
        node = self.ros.create_node.return_value
        node.get_clock.return_value.now.return_value.nanoseconds = 4_000_000_000
        self.sent = {}
        def publisher(_type, topic, _qos):
            self.sent[topic] = []
            pub = Mock()
            pub.publish.side_effect = self.sent[topic].append
            return pub
        node.create_publisher.side_effect = publisher
        self.modules = {"rclpy": self.ros, "rclpy.time": NS(Time=lambda nanoseconds: NS(to_msg=lambda: nanoseconds)),
                        "rclpy.qos": NS(qos_profile_sensor_data="sensor"), "sensor_msgs": Mock(),
                        "sensor_msgs.msg": NS(CameraInfo=Message, Image=Message)}
        self.addCleanup(patch.stopall)
        patch.object(realsense, "_sdk", return_value=self.sdk).start()
        patch.dict("sys.modules", self.modules).start()

    def test_start_publishes_matching_image_info_and_closes_device(self):
        self.ros.ok.side_effect = [True, True, False, False]
        self.pipe.try_wait_for_frames.return_value = True, self.frames
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["start", "--width", "2", "--height", "1"]), 0)
        self.pipe.stop.assert_called_once()
        self.ros.create_node.return_value.destroy_node.assert_called_once()
        for kind, topic, encoding, expected in [
            ("color", "image_raw", "bgr8", [2, 4, 8, 1, 3, 5]),
            ("depth", "image_rect_raw", "16UC1", list(np.array([0, 366], dtype=np.uint16).tobytes())),
        ]:
            # RealSense may repeat a previous frame in a synchronized frameset.
            image, = self.sent[f"/g1/head/{kind}/{topic}"]
            info, = self.sent[f"/g1/head/{kind}/camera_info"]
            self.assertEqual((image.header.frame_id, image.header.stamp),
                             (info.header.frame_id, info.header.stamp))
            self.assertEqual(image.encoding, encoding)
            self.assertEqual(list(image.data), expected)
            self.assertEqual((info.k[0], info.k[4], info.p[2]), (1.5, 1.6, 0.5))
        self.assertEqual(self.sdk.config.return_value.enable_stream.call_count, 2)
        self.sdk.config.return_value.enable_device.assert_called_once_with("mock-Intel RealSense D435i")

    def test_missing_frames_and_interrupt_both_release_the_camera(self):
        self.ros.ok.return_value = True
        args = NS(stream="depth", width=2, height=1, fps=15, device_index=None, timeout_s=1)
        self.pipe.try_wait_for_frames.return_value = False, None
        with patch.object(publish.time, "monotonic", side_effect=[0.0, 1.2]):
            with self.assertRaisesRegex(realsense.CameraError, "NO_CAMERA_FRAMES"):
                publish.start(args)
        self.pipe.try_wait_for_frames.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            publish.start(args)
        self.assertEqual(self.pipe.stop.call_count, 2)
        self.assertEqual(self.ros.shutdown.call_count, 2)
        self.assertEqual(self.sdk.config.return_value.enable_stream.call_args.args, ("depth", 2, 1, "z16", 15))
