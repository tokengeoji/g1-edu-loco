# Author: Codex (IIC)
"""Exercise the actual terminal loop on a Linux pseudo-terminal without a robot."""

import contextlib
import io
import os
import pty
import select
import signal
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from . import __main__ as cli


class KeyboardInputTests(unittest.TestCase):
    def test_single_commands_and_complete_arrows(self):
        keys = cli.TerminalKeys()
        for key in "wasdqefx?+-=!@#$0123456789m \r\n":
            self.assertEqual(keys.read(key.encode()), key)
        for unused_key in b"rg":
            self.assertEqual(keys.read(bytes([unused_key])), "\x1b")
        for seq, key in [(b"\x1b[A", "w"), (b"\x1bOB", "s"),
                         (b"\x1b[D", "q"), (b"\x1bOC", "e")]:
            self.assertEqual(keys.read(seq), key)
            self.assertEqual(keys.read(seq[:1]), "\x1b")
            self.assertEqual(keys.read(seq[1:]), key)

    def test_ambiguous_bursts_and_reports_do_not_move_or_change_modes(self):
        keys = cli.TerminalKeys()
        for seq in [b"ww", b"2\r", b"m\r", b"\x1b[Aw", b"w\x1b[A", b"\x1b[1;5D",
                    b"\x1bw", b"\x1b[I", b"\x1b[O", b"\x1b[", b"3", b"~",
                    b"\x1b]report", b"w", b"\x07", b"\x1b[M", b"w", b"r", b"d"]:
            self.assertEqual(keys.read(seq), "\x1b", seq)
        self.assertEqual(keys.read(b"f"), "f")

    def test_bracketed_paste_across_individual_bytes(self):
        keys = cli.TerminalKeys()
        for byte in b"\x1b[200~wr2\r\x1b[Ax\x04\x1b[201~":
            self.assertEqual(keys.read(bytes([byte])), "\x1b")
        self.assertEqual(keys.read(b"w"), "w")
        for seq in [b"\x03", b"\x04", b""]:
            self.assertEqual(keys.read(seq), "x")

    def test_stale_direction_cannot_swallow_stop_or_exit(self):
        keys = cli.TerminalKeys()
        self.assertEqual(keys.read(b"s "), " ")
        self.assertEqual(keys.read(b"sx"), "x")


class DiscoveryTests(unittest.TestCase):
    @patch.object(cli.time, "sleep")
    def test_auto_uses_only_fsm_reads_and_binds_one_service(self, _sleep):
        sport = Mock()
        sport.GetFsmId.side_effect = [(3104, None), (3104, None)]
        loco = Mock()
        loco.GetFsmId.return_value = (0, 500)
        factory = Mock(side_effect=[sport, loco])
        self.assertEqual(cli.discover("auto", factory), (loco, "loco", 500))
        self.assertEqual(factory.call_args_list, [call("sport"), call("loco")])
        self.assertEqual(sport.mock_calls, [call.GetFsmId()] * 2)
        self.assertEqual(loco.mock_calls, [call.GetFsmId()])

    @patch.object(cli.time, "sleep")
    def test_service_override_does_not_fall_back_after_failure(self, _sleep):
        bad = Mock()
        bad.GetFsmId.side_effect = [(3105, None), (0, None)]
        factory = Mock(return_value=bad)
        with self.assertRaisesRegex(RuntimeError, "loco GetFsmId code=3105.*code=0"):
            cli.discover("loco", factory)
        factory.assert_called_once_with("loco")

    @patch.object(cli.time, "sleep")
    def test_discovery_rejects_unknown_negative_fsm(self, _sleep):
        bad = Mock()
        bad.GetFsmId.return_value = (0, -1)
        with self.assertRaisesRegex(RuntimeError, "sport GetFsmId code=0, FSM=-1"):
            cli.discover("sport", lambda _: bad)
        self.assertEqual(bad.mock_calls, [call.GetFsmId()] * 2)

    def test_status_reports_discovered_fsm_without_control_or_tty(self):
        output = io.StringIO()
        client = Mock()
        with patch.object(cli, "connect", return_value=(client, "loco", 4)) as connect:
            with patch.dict(os.environ, ROS_DOMAIN_ID="8"), contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(["--status", "--interface", "eth0"]), 0)
        connect.assert_called_once_with(8, "eth0", "auto")
        self.assertEqual(client.mock_calls, [])
        self.assertIn("현재 FSM=4 · NIC=eth0 · DDS domain=8 · service=loco", output.getvalue())

    def test_failed_discovery_shows_network_and_rpc_code(self):
        errors = io.StringIO()
        with patch.object(cli, "connect", side_effect=RuntimeError("sport GetFsmId code=3104")):
            with contextlib.redirect_stderr(errors):
                self.assertEqual(cli.main(["--status", "--interface", "eth0", "--domain", "7"]), 1)
        self.assertIn("NIC=eth0 · DDS domain=7 · service=auto · sport GetFsmId code=3104",
                      errors.getvalue())


class LiveLockTests(unittest.TestCase):
    def test_second_live_session_is_rejected_before_dds_and_crash_releases_lock(self):
        holder = """
import fcntl, sys
with open(sys.argv[1], "a") as stream:
    fcntl.flock(stream, fcntl.LOCK_EX)
    print("locked", flush=True)
    sys.stdin.read()
"""
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "teleop.lock")
            with subprocess.Popen([sys.executable, "-c", holder, path],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE) as proc:
                try:
                    self.assertTrue(select.select([proc.stdout], [], [], 5)[0])
                    self.assertEqual(proc.stdout.readline(), b"locked\n")
                    with patch.object(cli, "LIVE_LOCK", path), patch.object(cli, "connect") as connect:
                        with patch.object(sys.stdin, "isatty", return_value=True), \
                                patch.object(sys.stdout, "isatty", return_value=True), \
                                contextlib.redirect_stderr(io.StringIO()) as errors:
                            self.assertEqual(cli.main(["--live", "--interface", "lo"]), 1)
                        self.assertIn("다른 실기체 텔레옵", errors.getvalue())
                        connect.assert_not_called()
                        connect.return_value = (Mock(), "sport", 500)
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(cli.main(["--status", "--interface", "lo"]), 0)
                finally:
                    proc.kill()
            with patch.object(cli, "LIVE_LOCK", path), cli.live_session_lock():
                self.assertTrue(Path(path).is_file())


class TerminalLoopTests(unittest.TestCase):
    def start(self, script=None):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        self.master, self.slave = master, slave
        self.original = termios.tcgetattr(slave)
        args = ["-c", script] if script else ["-m", __package__]
        self.proc = subprocess.Popen(
            [sys.executable, *args], cwd=Path(__file__).resolve().parents[len(__package__.split("."))],
            stdin=slave, stdout=slave, stderr=slave,
        )
        self.addCleanup(self.reap, self.proc)
        self.output = b""
        self.await_output("준비 ·")
        self.assertFalse(termios.tcgetattr(slave)[3] & termios.ICANON)

    @staticmethod
    def reap(proc):
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=3)

    def await_output(self, text):
        target = text.encode()
        deadline = time.monotonic() + 3
        while target not in self.output:
            if not select.select([self.master], [], [], max(0, deadline - time.monotonic()))[0]:
                self.fail(f"Missing {text!r} in {self.output.decode(errors='replace')!r}")
            self.output += os.read(self.master, 8192)
        before, _, self.output = self.output.partition(target)
        return before + target

    def assert_restored(self):
        self.assertEqual(self.proc.wait(timeout=3), 0)
        self.assertEqual(termios.tcgetattr(self.slave), self.original)

    def test_first_arrow_moves_in_802_then_idle_stop_and_eof_restore_terminal(self):
        self.start()
        os.write(self.master, b"\x1b[A")
        self.await_output("SetVelocity(0.15, 0.0, 0.0, ")
        self.await_output("SetVelocity(0.0, 0.0, 0.0, ")
        os.write(self.master, b"\x04")
        self.assert_restored()

    def test_mode_request_and_speed_cap_are_separate_from_motion(self):
        self.start(f"""
from {__package__} import __main__ as cli
class LockedStand(cli.DryClient):
    def __init__(self):
        self.fsm = 4
cli.DryClient = LockedStand
raise SystemExit(cli.main())
""")
        os.write(self.master, b"2")
        self.await_output("Esc")
        os.write(self.master, b"\r")
        self.await_output("FSM=802")
        os.write(self.master, b"@")
        # The mock prints during the RPC. Only the acceptance message follows
        # the stale-input drain and marks the next keystroke as fresh.
        transcript = self.await_output("SetSpeedMode(1) 수락")
        self.assertIn(b"SetSpeedMode(1)", transcript)
        self.assertNotIn(b"SetVelocity(", transcript)
        os.write(self.master, b"w")
        self.await_output("SetVelocity(0.15, 0.0, 0.0, ")
        os.write(self.master, b"x")
        self.assert_restored()

    def test_explicit_regular_and_run_switches_and_status_readback(self):
        self.start()
        for key, target in [(b"m", 500), (b"2", 802)]:
            with self.subTest(target=target):
                os.write(self.master, key)
                self.await_output("Enter로 요청, Esc로 취소")
                os.write(self.master, b"\r")
                self.await_output(f"[모의] SetFsmId({target})")
                self.await_output(f"현재 FSM={target}")
                os.write(self.master, b"f")
                self.await_output(f"현재 FSM={target}")
        os.write(self.master, b"x")
        self.assert_restored()

    def test_signal_stops_owned_motion_and_restores_terminal(self):
        for sig in [signal.SIGHUP, signal.SIGINT, signal.SIGTERM]:
            with self.subTest(signal=sig):
                self.start()
                os.write(self.master, b"w")
                self.await_output("SetVelocity(0.15, 0.0, 0.0, ")
                self.proc.send_signal(sig)
                self.await_output("SetVelocity(0.0, 0.0, 0.0, ")
                self.assert_restored()

    def test_direction_typed_during_slow_rpc_is_not_replayed(self):
        self.start(f"""
import sys
import time
from {__package__} import __main__ as cli
original = cli.DryClient.SetVelocity
def slow(self, vx, vy, yaw, duration):
    if vx > 0:
        print('in RPC', flush=True)
        time.sleep(0.15)
    return original(self, vx, vy, yaw, duration)
cli.DryClient.SetVelocity = slow
sys.exit(cli.main())
""")
        os.write(self.master, b"w")
        self.await_output("in RPC")
        os.write(self.master, b"s")
        self.await_output("SetVelocity(0.15, 0.0, 0.0, ")
        os.write(self.master, b"x")
        self.assert_restored()
        while select.select([self.master], [], [], 0)[0]:
            self.output += os.read(self.master, 8192)
        self.assertNotIn(b"SetVelocity(-0.15", self.output)
