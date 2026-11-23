# Author: Codex (IIC)
"""Offline cadence checks for recorded and dashboard temperatures."""

import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from g1stairs.session import read_jsonl

from . import __main__ as monitor
from .dashboard import Live


def lowstate(tick):
    motor = SimpleNamespace(q=tick, dq=tick, tau_est=tick)
    imu = SimpleNamespace(quaternion=[], gyroscope=[], accelerometer=[], rpy=[])
    # The middle sample deliberately has no temperature attributes. Reading
    # either one before the 10-second interval expires must fail this test.
    if tick != 2:
        motor.temperature = [30 + tick, 40 + tick]
        imu.temperature = 20 + tick
    return SimpleNamespace(tick=tick, mode_pr=0, mode_machine=5, imu_state=imu,
                           motor_state=[motor] * 29)


class TemperatureTest(unittest.TestCase):
    def setUp(self):
        self.timeline = [(n, lowstate(i)) for i, n in enumerate((0, 9_999_999_999, 10_000_000_000), 1)]

    def check_samples(self, samples):
        self.assertEqual([s["temperature_host_rx_monotonic_ns"] for s in samples], [0, 0, 10_000_000_000])
        self.assertEqual([s["imu"]["temperature_c"] for s in samples], [21, 21, 23])
        self.assertEqual([s["joints"][28]["temperature_casing_c"] for s in samples], [31, 31, 33])
        self.assertEqual([s["joints"][28]["temperature_winding_c"] for s in samples], [41, 41, 43])
        self.assertEqual([s["joints"][28]["q_rad"] for s in samples], [1, 2, 3])
        self.assertEqual([s["tick"] for s in samples], [1, 2, 3])

    def test_live_dashboard(self):
        receiver = Mock()
        receiver.snapshot.side_effect = [(item, 0) for item in self.timeline]
        live = Live(receiver, stale_after=1)
        self.check_samples([live.sample(0)["sample"] for _ in self.timeline])

    def test_record(self):
        receiver = Mock()
        receiver.wait.side_effect = self.timeline + [None]
        receiver.snapshot.return_value = None, 0
        with tempfile.TemporaryDirectory() as directory:
            args = monitor.parser().parse_args(["record", "--run", "fake", "--seconds", "11", "--runs-dir", directory])
            with patch.object(monitor, "Receiver", return_value=receiver), patch.object(monitor, "subscribe", return_value=nullcontext()):
                monitor.record(args)
            self.check_samples(list(read_jsonl(Path(directory) / "fake/state/samples.jsonl")))
