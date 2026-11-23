# Author: Codex (IIC)
"""Exercise preview through the real CLI, state decoder and keyboard controller."""

import contextlib
import io
import time
import unittest
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from . import __main__ as cli
from . import preview


def motor_feedback():
    motors = [SimpleNamespace(q=0.0, dq=0.0, tau_est=0.0, temperature=[24, 25])
              for _ in preview.JOINT_NAMES]
    knee = motors[preview.JOINT_NAMES.index("left_knee")]
    knee.q, knee.dq = 0.25, -0.5
    imu = SimpleNamespace(quaternion=[1, 0, 0, 0], gyroscope=[0] * 3, accelerometer=[0] * 3,
                          rpy=[0] * 3, temperature=24)
    return SimpleNamespace(tick=123, mode_pr=0, mode_machine=0, imu_state=imu, motor_state=motors)


class PreviewTests(unittest.TestCase):
    args = ["--preview", "--interface", "test-nic", "--domain", "17", "--service", "sport"]

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.sample = motor_feedback()
        self.stamp_offset_ns = 0
        self.channel_events = []
        self.stack.enter_context(patch.object(preview, "subscribe", self.subscribe))
        self.robot = Mock(spec_set=["GetFsmId", "SetFsmId", "SetVelocity", "SetSpeedMode", "SetBalanceMode"])
        self.robot.GetFsmId.return_value = (0, 4)
        for method in ("SetFsmId", "SetVelocity", "SetSpeedMode", "SetBalanceMode"):
            getattr(self.robot, method).side_effect = AssertionError(f"physical {method} called")
        self.factory = Mock(return_value=self.robot)
        discover = partial(cli.discover, make_client=self.factory)
        self.stack.enter_context(patch.object(cli, "discover", discover))
        self.connect = self.stack.enter_context(patch.object(cli, "connect"))
        self.live_lock = self.stack.enter_context(patch.object(cli, "live_session_lock"))

        self.output = io.StringIO()
        self.errors = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.stack.enter_context(contextlib.redirect_stderr(self.errors))
        self.stack.enter_context(patch.object(self.output, "isatty", return_value=True))
        stdin = self.stack.enter_context(patch.object(cli.sys, "stdin"))
        stdin.isatty.return_value = True
        stdin.fileno.return_value = 37

    def tearDown(self):
        self.live_lock.assert_not_called()
        self.assertTrue(all(operation == call.GetFsmId() for operation in self.robot.mock_calls),
                        f"unexpected physical RPCs: {self.robot.mock_calls}")

    @contextlib.contextmanager
    def subscribe(self, nic, domain, receiver):
        self.channel_events.append(("open", nic, domain))
        try:
            if self.sample is not None:
                stamp = time.monotonic_ns() + self.stamp_offset_ns
                with patch.object(time, "monotonic_ns", return_value=stamp):
                    receiver.on_sample(self.sample)
            yield
        finally:
            self.channel_events.append(("close", nic, domain))

    def keyboard(self, args, events):
        # Every scripted byte is fresh. Zero-time polls in poll_queued() find no backlog.
        def select_ready(readers, _writers, _errors, timeout):
            return (readers if timeout else [], [], [])

        with patch.object(cli, "keyboard_terminal", return_value=contextlib.nullcontext()), \
                patch.object(cli.select, "select", side_effect=select_ready), \
                patch.object(cli.os, "read", side_effect=events):
            return cli.main(args)

    def assert_preview_refused(self):
        with patch.object(cli, "interact") as interact:
            self.assertEqual(cli.main(self.args), 1)
            interact.assert_not_called()
        self.connect.assert_not_called()
        self.assertIn("NIC=test-nic", self.errors.getvalue())
        self.assertEqual(self.channel_events, [("open", "test-nic", 17), ("close", "test-nic", 17)])

    def test_real_snapshot_seeds_local_fsm_and_every_operation_stays_local(self):
        keys = [b"f", b"i", b"2", b"\r", b"i", b"k", b"@", b"i", b"\x04"]
        self.assertEqual(self.keyboard(self.args, keys), 0)
        text = self.output.getvalue()
        self.assertIn("[시작 시점 실측] 현재 FSM=4", text)
        self.assertIn("service=sport", text)
        self.assertIn("rt/lowstate", text)
        self.assertIn("29/29", text)
        self.assertIn("left_knee", text)
        self.assertIn("q=0.250 rad, dq=-0.500 rad/s", text)
        before, after = text.split("[모의] SetFsmId(802)", 1)
        self.assertIn("[모의] 현재 FSM=4", before)
        self.assertNotIn("[모의] SetVelocity(", before)
        self.assertIn("[모의] SetSpeedMode(1)", after)
        self.assertEqual(after.count("[모의] SetVelocity(0.15, 0.0, 0.0,"), 2)
        self.assertEqual(after.count("[모의] SetVelocity(0.0, 0.0, 0.0,"), 2)  # k and exit.
        self.assertEqual(self.channel_events, [("open", "test-nic", 17), ("close", "test-nic", 17)])
        self.factory.assert_called_once_with("sport")
        self.robot.GetFsmId.assert_called_once_with()
        self.connect.assert_not_called()

    def test_terminal_error_during_motion_closes_only_the_local_controller(self):
        self.robot.GetFsmId.return_value = (0, 802)
        self.assertEqual(self.keyboard(self.args, [b"i", OSError("TTY disconnected")]), 1)
        self.assertIn("TTY disconnected", self.errors.getvalue())
        text = self.output.getvalue()
        self.assertIn("[모의] SetVelocity(0.15, 0.0, 0.0,", text)
        self.assertIn("[모의] SetVelocity(0.0, 0.0, 0.0,", text)
        self.robot.GetFsmId.assert_called_once_with()
        self.connect.assert_not_called()

    def test_run_selection_defaults_to_the_observed_801_in_preview(self):
        self.robot.GetFsmId.return_value = (0, 801)
        self.assertEqual(self.keyboard(self.args, [b"2", b"\r", b"i", b"\x04"]), 0)
        text = self.output.getvalue()
        self.assertIn("2 Run 보행 (FSM 801)", " ".join(text.split()))
        self.assertNotIn("[모의] SetFsmId(", text)
        self.assertIn("[모의] SetVelocity(7105) 수락 · FSM=801", text)
        self.robot.GetFsmId.assert_called_once_with()
        self.connect.assert_not_called()

    def test_explicit_run_id_overrides_the_preview_selection_only(self):
        for observed, requested in [(4, 801), (801, 802)]:
            with self.subTest(observed=observed, requested=requested):
                self.robot.GetFsmId.return_value = (0, observed)
                args = self.args + ["--run-fsm", str(requested)]
                start = self.output.tell()
                self.assertEqual(self.keyboard(args, [b"2", b"\r", b"i", b"\x04"]), 0)
                text = self.output.getvalue()[start:]
                self.assertIn(f"[시작 시점 실측] 현재 FSM={observed}", text)
                self.assertIn(f"2 Run 보행 (FSM {requested})", " ".join(text.split()))
                self.assertIn(f"[모의] SetFsmId({requested})", text)
                self.assertIn(f"[모의] SetVelocity(7105) 수락 · FSM={requested}", text)
        self.assertEqual(self.robot.mock_calls, [call.GetFsmId(), call.GetFsmId()])
        self.connect.assert_not_called()

    def test_timeout_or_failed_fsm_read_cannot_open_a_controller(self):
        self.sample = None
        with patch.object(preview.Receiver, "wait", return_value=None) as wait:
            self.assert_preview_refused()
            wait.assert_called_once()
        self.assertIn("rt/lowstate", self.errors.getvalue())

        self.channel_events.clear()
        self.robot.GetFsmId.return_value = (3104, None)
        with patch.object(cli.time, "sleep"):
            self.assert_preview_refused()
        self.assertIn("3104", self.errors.getvalue())

    def test_rejects_samples_from_before_subscription_and_future_timestamps(self):
        for offset in (-50_000_000, 60_000_000_000):
            with self.subTest(offset=offset):
                self.channel_events.clear()
                self.stamp_offset_ns = offset
                self.assert_preview_refused()

    def test_rpc_delay_can_expire_a_sample_received_during_the_subscription(self):
        observed_start = time.monotonic_ns()
        clock = Mock()
        clock.monotonic_ns.side_effect = [observed_start, observed_start + 60_000_000_000]
        with patch.object(preview, "time", clock):
            self.assert_preview_refused()
        self.assertIn("rt/lowstate", self.errors.getvalue())

    def test_rejects_incomplete_and_invalid_motor_feedback(self):
        for field, value in (("q", float("nan")), ("dq", float("inf")), ("q", True), ("dq", None)):
            with self.subTest(field=field, value=value):
                self.channel_events.clear()
                self.sample = motor_feedback()
                setattr(self.sample.motor_state[-1], field, value)
                self.assert_preview_refused()
                self.assertIn("rt/lowstate", self.errors.getvalue())
        self.channel_events.clear()
        self.sample = motor_feedback()
        self.sample.motor_state.pop()
        self.assert_preview_refused()

    def test_requires_a_nic_and_an_exclusive_execution_mode(self):
        for args in (["--preview"], self.args + ["--live"], self.args + ["--dry-run"],
                     self.args + ["--status"], self.args + ["--run-fsm", "800"]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                cli.main(args)
            self.assertEqual(error.exception.code, 2)
        self.assertEqual(self.channel_events, [])
        self.factory.assert_not_called()
        self.connect.assert_not_called()

    def test_dry_run_does_not_attempt_a_snapshot_or_open_any_connection(self):
        self.assertEqual(self.keyboard(["--dry-run"], [b"\x04"]), 0)
        self.assertIn("초기 FSM=802", self.output.getvalue())
        self.assertEqual(self.channel_events, [])
        self.factory.assert_not_called()
        self.connect.assert_not_called()

    def test_plain_status_reports_diagnostics_and_exits_before_keyboard(self):
        self.connect.side_effect = lambda domain, nic, service: cli.discover(service)
        with patch.object(cli, "interact") as interact, \
                patch(__package__ + ".status.status_details", return_value="SDK 상태") as details:
            self.assertEqual(cli.main(["--status", "--interface", "test-nic", "--service", "sport"]), 0)
            interact.assert_not_called()
            details.assert_called_once_with(self.robot)
        self.assertEqual(self.channel_events, [])
        self.robot.GetFsmId.assert_called_once_with()
