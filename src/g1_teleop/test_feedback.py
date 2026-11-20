# Author: Codex (IIC)
import io
import sys
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from .feedback import TOPIC, format_odometry, watch_odometry


class OdometryFeedbackTests(unittest.TestCase):
    def test_planar_displacement_and_speed_use_world_xy_axes(self):
        sample = SimpleNamespace(position=[1., -1., 0.8], velocity=[3., 4., 0.], yaw_speed=-.2)
        initial, origin = format_odometry(sample, None)
        self.assertIn("시작점과 수평거리=0.000 m", initial)
        self.assertIn("수평 속력=5.000 m/s", initial)
        sample.position = [4., 3., 2.]
        next_view, same_origin = format_odometry(sample, origin)
        self.assertEqual(same_origin, origin)
        self.assertIn("시작점과 수평거리=5.000 m", next_view)
        self.assertIn("회전속도=-0.200 rad/s", next_view)

    def test_unknown_or_invalid_velocity_is_not_reported_as_stationary(self):
        for velocity in [[], [float("nan"), 0., 0.]]:
            with self.assertRaises(ValueError):
                format_odometry(SimpleNamespace(position=[0, 0], velocity=velocity, yaw_speed=0), None)

    def test_reader_uses_official_odom_type_and_does_not_reprint_stale_values(self):
        sample = SimpleNamespace(position=[0, 0, 0], velocity=[1, 0, 0], yaw_speed=0)
        channel = Mock()
        sdk = {"unitree_sdk2py.core.channel": channel,
               "unitree_sdk2py.idl.unitree_go.msg.dds_": SimpleNamespace(SportModeState_=type(sample))}
        clock = Mock()
        clock.monotonic.side_effect = [10.0, 10.25, 10.50, 11.50]
        clock.sleep.side_effect = [None, None, None, KeyboardInterrupt]
        receiver = Mock()
        receiver.snapshot.return_value = ((10_000_000_000, sample), 0)
        output = io.StringIO()
        with patch.dict(sys.modules, sdk), patch("g1_teleop.feedback.time", clock), \
                patch("g1_teleop.feedback.Receiver", return_value=receiver), redirect_stdout(output):
            with self.assertRaises(KeyboardInterrupt):
                watch_odometry("eth0", 0)
        channel.ChannelFactoryInitialize.assert_called_once_with(0, "eth0")
        channel.ChannelSubscriber.assert_called_once_with(TOPIC, type(sample))
        channel.ChannelSubscriber.return_value.Init.assert_called_once_with(receiver.on_sample, 0)
        channel.ChannelSubscriber.return_value.Close.assert_called_once_with()
        self.assertEqual(output.getvalue().count("수평 속력=1.000"), 1)
        self.assertEqual(output.getvalue().count("새 오도메트리 샘플 대기"), 1)
