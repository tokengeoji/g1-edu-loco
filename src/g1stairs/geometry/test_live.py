# Author: Codex (IIC)
"""Exercise live display without opening a camera, DDS participant or run directory."""

import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from g1stairs.camera.test_realsense import _device, _profile, _sdk

from . import live


class LiveStairTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cal = Path(temp.name) / "measured.json"
        self.cal.write_text(json.dumps({
            "source_frame": "camera_depth_optical", "frame_id": "survey",
            "rotation": np.eye(3).tolist(), "translation_m": [0., 0., 0.], "ground_z_m": 0.,
        }), encoding="utf-8")
        self.parser = argparse.ArgumentParser()
        live.configure_parser(self.parser)
        self.parser.set_defaults(grid_m=0.025, height_tolerance_m=0.018, min_samples=45)

    def args(self, *extra):
        return self.parser.parse_args(["--calibration", str(self.cal), *extra])

    def test_usb_uses_frame_units_caches_rays_and_prints_before_capture_ends(self):
        depth = np.zeros((3, 3), dtype=np.uint16)
        output = io.StringIO()

        def usb(seconds, width, height, fps, index, callback, metadata):
            self.assertEqual((seconds, width, height, fps, index), (10., 640, 480, 60, None))
            metadata.update(intrinsics={"width": 3}, depth_scale_m=0.00025)
            for number, stamp in [(1, 1), (2, 60_000_001), (3, 1_000_000_001)]:
                callback(depth, {"frame_number": number, "host_rx_monotonic_ns": stamp})
            self.assertIn("프레임 1", output.getvalue())
            self.assertNotIn("프레임 2", output.getvalue())
            self.assertIn("프레임 3", output.getvalue())

        with patch.object(live.realsense, "record", side_effect=usb), redirect_stdout(output), \
                patch.object(live, "camera_rays", return_value=np.zeros((3, 3, 3))) as rays, \
                patch.object(live, "deproject", wraps=live.deproject) as project, \
                patch.object(live, "format_stair_map", wraps=live.format_stair_map) as map_view:
            live.run(self.args("--map"))
        rays.assert_called_once_with({"width": 3})
        self.assertEqual([call.args[2] for call in project.call_args_list], [0.00025, 0.00025])
        self.assertEqual(map_view.call_count, 2)
        self.assertEqual(list(self.cal.parent.iterdir()), [self.cal])

    def test_first_usb_frame_has_device_scale_and_interrupt_closes_pipeline(self):
        profile = _profile(3, 3, 30)
        profile.get_intrinsics.return_value = SimpleNamespace(
            width=3, height=3, fx=2., fy=2., ppx=1., ppy=1., model="none", coeffs=[0.] * 5)
        sdk = _sdk(_device("Intel RealSense D435i", profile))
        pipe = sdk.pipeline.return_value
        pipe.start.return_value.get_stream.return_value = profile
        frames = Mock()
        frame = frames.get_depth_frame.return_value
        frame.get_frame_number.return_value = 7
        frame.get_data.return_value = np.zeros((3, 3), dtype=np.uint16)
        frame.get_units.return_value = .0005
        frame.get_timestamp.return_value = 1.
        pipe.try_wait_for_frames.side_effect = [(True, frames), KeyboardInterrupt()]
        with patch.object(live.realsense, "_sdk", return_value=sdk), redirect_stdout(io.StringIO()), \
                patch.object(live, "camera_rays", return_value=np.zeros((3, 3, 3))), \
                patch.object(live, "deproject", wraps=live.deproject) as project:
            with self.assertRaises(KeyboardInterrupt):
                live.run(self.args("--width", "3", "--height", "3", "--fps", "30"))
        self.assertEqual(project.call_args.args[2], .0005)
        pipe.stop.assert_called_once()

    def test_ros_requires_known_units_and_checks_observed_optical_frame(self):
        def ros(args, callback, metadata):
            self.assertEqual(args.depth_topic, "/g1/head/depth/image_rect_raw")
            self.assertEqual(args.info_topic, "/g1/head/depth/camera_info")
            self.assertEqual(metadata["depth_scale_m"], 0.002)
            metadata.update(frame_id="different_camera_depth", intrinsics={})
            callback(None, {"frame_number": 0, "host_rx_monotonic_ns": 100})

        with patch.object(live.ros_depth, "record", side_effect=ros) as reader, \
                patch.object(live, "camera_rays") as rays:
            with self.assertRaisesRegex(ValueError, "depth-scale-m"):
                live.run(self.args("--source", "ros"))
            reader.assert_not_called()
            with self.assertRaisesRegex(ValueError, "source_frame"):
                live.run(self.args("--source", "ros", "--depth-scale-m", "0.002"))
            rays.assert_not_called()

    def test_invalid_options_do_not_open_camera(self):
        with patch.object(live.realsense, "record") as reader:
            for options in [("--seconds", "nan"), ("--interval", "0"), ("--fps", "-1"),
                            ("--depth-scale-m", "0.001")]:
                with self.subTest(options=options), self.assertRaises(ValueError):
                    live.run(self.args(*options))
            reader.assert_not_called()
