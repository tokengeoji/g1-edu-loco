import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from . import __main__ as camera_cli
from . import realsense


def _profile(width, height, fps, stream="depth", encoding="z16"):
    profile = Mock()
    profile.width.return_value = width
    profile.height.return_value = height
    profile.fps.return_value = fps
    profile.stream_type.return_value = stream
    profile.format.return_value = encoding
    profile.as_video_stream_profile.return_value = profile
    return profile


def _device(model, *profiles, product_id=None):
    sensor = Mock()
    sensor.get_stream_profiles.return_value = profiles
    fields = {"name": model, "serial_number": f"mock-{model}"}
    if product_id is not None:
        fields["product_id"] = product_id
    device = Mock()
    device.supports.side_effect = fields.__contains__
    device.get_info.side_effect = fields.__getitem__
    device.query_sensors.return_value = [sensor]
    return device


def _sdk(*devices):
    context = Mock()
    context.query_devices.return_value = list(devices)
    return SimpleNamespace(
        context=Mock(return_value=context),
        pipeline=Mock(),
        config=Mock(),
        camera_info=SimpleNamespace(name="name", serial_number="serial_number", product_id="product_id"),
        stream=SimpleNamespace(depth="depth"),
        format=SimpleNamespace(z16="z16"),
    )


class G1HeadCameraTest(unittest.TestCase):
    def test_probe_distinguishes_model_from_format_and_reports_guide_profile(self):
        guide = _profile(640, 480, 60)
        other = _profile(848, 480, 30)
        color = _profile(1280, 720, 30, stream="color", encoding="rgb8")
        sdk = _sdk(
            _device("Intel RealSense D435i", guide, other, color, product_id="0B3A"),
            _device("Intel RealSense D435", guide, product_id="0B07"),
        )
        with patch.object(realsense, "_sdk", return_value=sdk):
            result = realsense.probe()
        self.assertEqual(realsense.G1_HEAD_MODEL, "D435i")
        self.assertEqual(realsense.G1_DEPTH_PROFILE, (640, 480, 60))
        guide_profile = {"width": 640, "height": 480, "fps": 60}
        self.assertEqual(result["guide_depth_profile"], dict(guide_profile, encoding="Z16"))
        head, other_device = result["devices"]
        self.assertEqual(head["model"], "Intel RealSense D435i")
        self.assertTrue(head["matches_g1_head_model"])
        self.assertTrue(head["supports_guide_depth_profile"])
        self.assertEqual(head["z16_profiles"], [guide_profile, {"width": 848, "height": 480, "fps": 30}])
        self.assertFalse(other_device["matches_g1_head_model"])
        self.assertFalse(result["stream_started"])
        sdk.pipeline.assert_not_called()

    def test_other_models_and_missing_profile_are_rejected_before_start(self):
        for device, status in (
            (_device("Intel RealSense D435", _profile(640, 480, 60), product_id="0B07"), "DEVICE_MODEL_MISMATCH"),
            (_device("Intel RealSense D435i", _profile(640, 480, 30), product_id="0B3A"), "DEPTH_PROFILE_UNSUPPORTED"),
        ):
            with self.subTest(status=status):
                sdk = _sdk(device)
                with patch.object(realsense, "_sdk", return_value=sdk):
                    with self.assertRaisesRegex(realsense.CameraError, status):
                        realsense.record(1, 640, 480, 60, 0, Mock(), {})
                sdk.pipeline.return_value.start.assert_not_called()

    def test_explicit_supported_alternate_profile_can_be_started(self):
        device = _device("Intel RealSense D435I", _profile(848, 480, 30), product_id="0B3A")
        sdk = _sdk(device)
        pipeline = sdk.pipeline.return_value
        pipeline.start.side_effect = RuntimeError("mock capture boundary")
        with patch.object(realsense, "_sdk", return_value=sdk):
            with self.assertRaisesRegex(realsense.CameraError, "mock capture boundary"):
                realsense.record(1, 848, 480, 30, None, Mock(), {})
        sdk.config.return_value.enable_stream.assert_called_once_with("depth", 848, 480, "z16", 30)
        pipeline.start.assert_called_once_with(sdk.config.return_value)

    def test_record_cli_defaults_to_the_unitree_guide_profile(self):
        with patch.object(camera_cli, "_record", return_value={}) as record, redirect_stdout(io.StringIO()):
            self.assertEqual(camera_cli.main(["record", "--run", "fixture"]), 0)
        args = record.call_args.args[0]
        self.assertEqual((args.width, args.height, args.fps), (640, 480, 60))


if __name__ == "__main__":
    unittest.main()
