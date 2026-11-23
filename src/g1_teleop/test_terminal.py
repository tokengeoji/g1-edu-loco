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
        for key in "uiojk lm,.UIOJKLM<>qzwxecf?+-=!@#$0123456789v \r\n":
            self.assertEqual(keys.read(key.encode()), key)
        for unused_key in b"rg":
            self.assertEqual(keys.read(bytes([unused_key])), "\x1b")
        for seq, key in [(b"\x1b[A", "i"), (b"\x1bOB", ","),
                         (b"\x1b[D", "j"), (b"\x1bOC", "l")]:
            self.assertEqual(keys.read(seq), key)
            self.assertEqual(keys.read(seq[:1]), "\x1b")
            self.assertEqual(keys.read(seq[1:]), key)

    def test_ambiguous_bursts_and_reports_do_not_move_or_change_modes(self):
        keys = cli.TerminalKeys()
        for seq in [b"ii", b"2\r", b"v\r", b"m\r", b"\x1b[Ai", b"i\x1b[A", b"\x1b[1;5D",
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
            self.assertEqual(keys.read(seq), keys.exit_key)

    def test_stale_direction_cannot_swallow_stop_or_exit(self):
        keys = cli.TerminalKeys()
        self.assertEqual(keys.read(b"i "), " ")
        self.assertEqual(keys.read(b"ik"), " ")
        self.assertEqual(keys.read(b"i\x04"), keys.exit_key)
        self.assertEqual(keys.read(b"ii", repeat_key="i"), "i")
        self.assertEqual(keys.read(b"ij", repeat_key="i"), "\x1b")
        self.assertEqual(keys.read(b",,", repeat_key="i"), "\x1b")
        self.assertEqual(keys.read(b"\x1b[A" * 3, repeat_key="i"), "i")
        self.assertEqual(keys.read(b"\x1b[A" * 3, repeat_key=","), "\x1b")

    def test_queued_repeats_coalesce_and_never_override_stops(self):
        def drain(events):
            read_ready = [([91], [], [])] * len(events) + [([], [], [])]
            with patch.object(cli.select, "select", side_effect=read_ready), \
                    patch.object(cli.os, "read", side_effect=events):
                return cli.poll_queued(91, cli.TerminalKeys(), "i")

        self.assertEqual(drain([b"i", b"ii", b"i"]), "i")
        self.assertEqual(drain([b"i", b",", b"i"]), "\x1b")
        self.assertEqual(drain([b"i", b"k", b"ii"]), " ")
        self.assertEqual(drain([b"i", b" ", b"\x04"]), cli.TerminalKeys.exit_key)


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
        with patch.object(cli, "connect", return_value=(client, "loco", 4)) as connect, \
                patch(__package__ + ".status.status_details", return_value="SDK 상태") as details, \
                patch(__package__ + ".services.motion_service_details", return_value="서비스 상태") as services:
            with patch.dict(os.environ, ROS_DOMAIN_ID="8"), contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(["--status", "--interface", "eth0"]), 0)
        connect.assert_called_once_with(8, "eth0", "auto")
        self.assertEqual(client.mock_calls, [])
        details.assert_called_once_with(client)
        services.assert_called_once_with()
        self.assertIn("서비스 상태", output.getvalue())
        self.assertIn("SDK 상태", output.getvalue())
        self.assertIn("현재 FSM=4 (잠금 기립) · NIC=eth0 · DDS domain=8 · service=loco", output.getvalue())

    def test_feedback_is_read_only_and_needs_no_tty_or_loco_rpc(self):
        with patch(__package__ + ".feedback.watch_odometry") as observe, patch.object(cli, "connect") as connect:
            self.assertEqual(cli.main(["--feedback", "--interface", "lo", "--domain", "7"]), 0)
        observe.assert_called_once_with("lo", 7)
        connect.assert_not_called()

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
                        with contextlib.redirect_stdout(io.StringIO()), \
                                patch(__package__ + ".status.status_details", return_value="SDK 상태"), \
                                patch(__package__ + ".services.motion_service_details", return_value="서비스 상태"):
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
        startup = self.await_output("준비 ·", timeout=12)
        self.assertFalse(termios.tcgetattr(slave)[3] & termios.ICANON)
        return startup

    @staticmethod
    def reap(proc):
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=3)

    def await_output(self, text, timeout=3):
        target = text.encode()
        deadline = time.monotonic() + timeout
        while target not in self.output:
            if not select.select([self.master], [], [], max(0, deadline - time.monotonic()))[0]:
                self.fail(f"Missing {text!r} in {self.output.decode(errors='replace')!r}")
            self.output += os.read(self.master, 8192)
        before, _, self.output = self.output.partition(target)
        return before + target

    def assert_restored(self, status=0):
        self.assertEqual(self.proc.wait(timeout=3), status)
        self.assertEqual(termios.tcgetattr(self.slave), self.original)

    def test_startup_shows_every_mode_and_stop_before_any_key(self):
        startup = " ".join(self.start().decode().split())
        for binding in ("0 댐핑 (FSM 1)", "1 잠금 기립 (FSM 4)", "2 Run 보행 (FSM 802)",
                        "3 위치 제어 쪼그림 (FSM 2)", "4 균형 기립 (균형 설정 0)",
                        "5 연속 제자리걸음 (균형 설정 1)", "6 균형 쪼그림 ↔ 기립 전환 (FSM 706)",
                        "7/9 의자에 앉기 (FSM 3)", "8 허리 3자유도 보행 (FSM 501)", "v 일반 보행 (FSM 500)"):
            self.assertIn(binding, startup)
        self.assertIn("--waist-3dof", startup)
        self.assertIn("← / → = 소문자 j / l · 제자리 회전 요청 (vx=vy=0)", startup)
        self.assertIn("대문자 J / L (Shift+j / Shift+l) · 왼쪽 / 오른쪽 옆걸음 요청 (vx=yaw=0)", startup)
        self.assertIn("Ctrl+C 정지 요청 후 종료", startup)
        os.write(self.master, b"\x04")
        self.assert_restored()

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
        os.write(self.master, b"i")
        self.await_output("SetVelocity(0.15, 0.0, 0.0, ")
        os.write(self.master, b"\x04")
        self.assert_restored()

    def test_reverse_arc_is_motion_and_does_not_request_regular_mode(self):
        self.start()
        os.write(self.master, b"m")
        seen = self.await_output("SetVelocity(-0.15, 0.0, -0.3, ")
        self.assertNotIn(b"SetFsmId(", seen)
        os.write(self.master, b"k")
        self.await_output("SetVelocity(0.0, 0.0, 0.0, ")
        os.write(self.master, b"\x04")
        self.assert_restored()

    def test_signal_stops_owned_motion_and_restores_terminal(self):
        for sig in [signal.SIGHUP, signal.SIGINT, signal.SIGTERM]:
            with self.subTest(signal=sig):
                self.start()
                os.write(self.master, b"i")
                self.await_output("SetVelocity(0.15, 0.0, 0.0, ")
                self.proc.send_signal(sig)
                self.await_output("SetVelocity(0.0, 0.0, 0.0, ")
                self.assert_restored()

    def start_live_spy(self, *, delay="", zero_code=0):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.velocities = Path(directory.name) / "velocities"
        self.velocities.touch()
        return self.start(f"""
import fcntl
import os
import select
import sys
import termios
import time
from {__package__} import __main__ as cli

# Make this slave the child's controlling terminal so writing Ctrl+C to the
# master exercises VINTR/SIGINT just as it does in an interactive docker exec.
os.setsid()
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
assert os.tcgetpgrp(0) == os.getpgrp()

class SpyClient:
    fsm_reads = 0

    def rpc_wait(self):
        # The SDK future can catch exceptions raised in its blocking wait.
        try:
            time.sleep(0.4)
        except BaseException:
            pass

    def GetFsmId(self):
        self.fsm_reads += 1
        if {delay!r} == "read":
            print("reading FSM", flush=True)
            self.rpc_wait()
        if ({delay!r}, self.fsm_reads) in (("initial", 1), ("refresh", 2)):
            print("waiting for key during FSM read", flush=True)
            # Leave the byte queued so the terminal sees it before the send.
            if not select.select([sys.stdin], [], [], 2)[0]:
                raise RuntimeError("key did not arrive during FSM read")
        return 0, 802

    def SetVelocity(self, vx, vy, yaw, duration):
        command = "move" if any((vx, vy, yaw)) else "zero"
        with open({str(self.velocities)!r}, "a") as out:
            print(command, file=out)
        print("wire " + command + " after FSM read", self.fsm_reads, flush=True)
        if command == {delay!r}:
            self.rpc_wait()
        return {zero_code} if command == "zero" else 0

cli.LIVE_LOCK = {str(Path(directory.name) / "lock")!r}
cli.connect = lambda *args: (SpyClient(), "sport", 802)
sys.exit(cli.main(["--live", "--interface", "lo", "--domain", "0"]))
""")

    def test_typed_ctrl_c_during_move_waits_for_zero_even_after_second_interrupt(self):
        self.start_live_spy(delay="zero")
        os.write(self.master, b"i")
        self.await_output("wire move")
        os.write(self.master, b"\x03")
        self.await_output("wire zero")
        os.write(self.master, b"\x03")
        self.await_output("종료 정지 · 속도 0 요청 수락")
        self.assert_restored()
        self.assertEqual(self.velocities.read_text().splitlines(), ["move", "zero"])

    def test_typed_ctrl_c_during_inflight_rpc_finishes_with_zero(self):
        for operation, marker, expected in [
            ("read", "reading FSM", ["zero"]),
            ("move", "wire move", ["move", "zero"]),
        ]:
            with self.subTest(operation=operation):
                self.start_live_spy(delay=operation)
                os.write(self.master, b"i")
                self.await_output(marker)
                os.write(self.master, b"\x03")
                self.await_output("종료 정지 · 속도 0 요청 수락")
                self.assert_restored()
                self.assertEqual(self.velocities.read_text().splitlines(), expected)

    def test_typed_ctrl_c_after_idle_timeout_requests_new_final_zero(self):
        self.start_live_spy()
        os.write(self.master, b"i")
        self.await_output("키 반복 입력 만료")
        os.write(self.master, b"\x03")
        self.await_output("종료 정지 · 속도 0 요청 수락")
        self.assert_restored()
        commands = self.velocities.read_text().splitlines()
        self.assertGreater(len(commands), 3)
        self.assertEqual(commands[:-2], ["move"] * (len(commands) - 2))
        self.assertEqual(commands[-2:], ["zero", "zero"])

    def test_stop_during_initial_or_refresh_fsm_read_preempts_velocity_send(self):
        for delay, expected in [("initial", ["zero", "zero"]), ("refresh", ["move", "zero", "zero"])]:
            with self.subTest(delay=delay):
                self.start_live_spy(delay=delay)
                os.write(self.master, b"i")
                self.await_output("waiting for key during FSM read")
                os.write(self.master, b"k")
                message = self.await_output("속도 0 요청 수락.")
                self.assertNotIn("만료".encode(), message)
                os.write(self.master, b"\x04")
                self.assert_restored()
                self.assertEqual(self.velocities.read_text().splitlines(), expected)

    def test_same_direction_repeat_during_initial_fsm_read_keeps_original_send(self):
        self.start_live_spy(delay="initial")
        os.write(self.master, b"i")
        self.await_output("waiting for key during FSM read")
        os.write(self.master, b"ii")
        self.await_output("wire move after FSM read 1")
        os.write(self.master, b"\x04")
        self.assert_restored()
        commands = self.velocities.read_text().splitlines()
        self.assertEqual(commands[0], "move")
        self.assertEqual(commands[-1], "zero")

    def test_failed_final_stop_reports_rpc_code_and_exits_unsuccessfully(self):
        self.start_live_spy(zero_code=4201)
        os.write(self.master, b"i")
        self.await_output("wire move")
        os.write(self.master, b"\x03")
        self.await_output("종료 정지 미확인")
        self.await_output("4201")
        self.assert_restored(status=1)
        self.assertEqual(self.velocities.read_text().splitlines(), ["move", "zero", "zero"])

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
        os.write(self.master, b"i")
        self.await_output("in RPC")
        os.write(self.master, b",")
        self.await_output("SetVelocity(0.15, 0.0, 0.0, ")
        os.write(self.master, b"\x04")
        self.assert_restored()
        while select.select([self.master], [], [], 0)[0]:
            self.output += os.read(self.master, 8192)
        self.assertNotIn(b"SetVelocity(-0.15", self.output)
