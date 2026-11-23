# Author: Codex (IIC)
"""Run the G1 locomotion terminal. The default simulation is offline."""

import argparse
import fcntl
import os
import select
import signal
import sys
import termios
import time
import tty
from contextlib import contextmanager, nullcontext

from .control import CONFIRM_SECONDS, LAB_RUN_FSM, MODES, RUN_IDS, VELOCITY, Controller, EndSession, display_fsm


def mode_menu(modes):
    keys_by_mode = {}
    for key in sorted(modes):
        keys_by_mode.setdefault(modes[key], []).append(key)

    lines = [f"모드 선택   숫자 또는 v → {CONFIRM_SECONDS:g}초 안에 Enter · Esc 취소"]
    for (kind, value, label), keys in keys_by_mode.items():
        target = f"FSM {value}" if kind == "fsm" else f"균형 설정 {value}"
        name = label.partition(" · ")[0]
        lines.append(f"  {'/'.join(keys):<4}  {name} ({target})")
    lines.extend([
        "  4·5는 FSM 500/501에서 사용",
        "  8은 허리 3자유도 구성 확인 후 --waist-3dof로 실행할 때 사용",
    ])
    return "\n".join(lines)


KEY_HELP = """
이동 키
   u    i    o       전진하며 좌회전 / 전진 / 전진하며 우회전
   j    k    l       좌회전 / 정지 / 우회전
   m    ,    .       후진하며 우회전 / 후진 / 후진하며 좌회전
Shift+J/L 옆걸음   방향키 ↑↓ 전후진 · ←→ 회전
이동 요청은 최대 10 Hz로 갱신 · 키 반복이 끊기면 마지막 입력 후 최대 1초   q/z 속도 올림/내림
k 또는 Space 정지   Ctrl+C 정지 요청 후 종료   f 현재 모드   ? 전체 키"""

EXTRA_HELP = """Shift+U/I/O·J/L·M/</> 회전 없이 전후·좌우 이동
w/x 직선·옆걸음 속도 올림/내림    e/c 회전 속도 올림/내림
!/@/#/$ Run(801/802) 속도 상한 0/1/2/3"""


class DryClient:
    def __init__(self, fsm=LAB_RUN_FSM):
        self.fsm = fsm

    def GetFsmId(self):
        return 0, self.fsm

    def SetFsmId(self, value):
        if value != 706:  # The squat/stand toggle has no persistent FSM readback.
            self.fsm = value
        print(f"[모의] SetFsmId({value})", flush=True)
        return 0

    def SetBalanceMode(self, value):
        print(f"[모의] SetBalanceMode({value})", flush=True)
        return 0

    def SetSpeedMode(self, value):
        print(f"[모의] SetSpeedMode({value})", flush=True)
        return 0

    def SetVelocity(self, vx, vy, yaw, duration):
        print(f"[모의] SetVelocity({vx}, {vy}, {yaw}, {duration:.3f})", flush=True)
        return 0


def sdk_client(service):
    from unitree_sdk2py.g1.loco.g1_loco_api import LOCO_SERVICE_NAME
    from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient

    if service == LOCO_SERVICE_NAME:
        client = LocoClient()
    elif service == "loco":
        from unitree_sdk2py.rpc.client import Client

        class LegacyLocoClient(LocoClient):
            def __init__(self):
                # Before ai_sport 8.2 Unitree used this endpoint for the same
                # RPCs. Inherit the pinned SDK's Init and all locomotion methods.
                Client.__init__(self, "loco", False)

        client = LegacyLocoClient()
    else:
        raise ValueError(f"Unsupported G1 locomotion service: {service}")
    client.SetTimeout(0.5)
    client.Init()
    return client


def discover(service, make_client=sdk_client):
    names = ("sport", "loco") if service == "auto" else (service,)
    failures = []
    for name in names:
        client = make_client(name)
        for attempt in range(2):
            if attempt:
                time.sleep(0.25)  # Allow cold DDS endpoints time to match.
            try:
                code, fsm = client.GetFsmId()
                if code == 0 and type(fsm) is int and fsm >= 0:
                    return client, name, fsm
                failures.append(f"{name} GetFsmId code={code}, FSM={fsm!r}")
            except Exception as error:
                failures.append(f"{name} GetFsmId: {error}")
    raise RuntimeError(" / ".join(failures))


def connect(domain, interface, service):
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize

    ChannelFactoryInitialize(domain, interface)
    return discover(service)


LIVE_LOCK = "/run/g1-tools/teleop.lock"


@contextmanager
def live_session_lock():
    # Every docker exec in this container sees the same inode. Leave it in
    # place across sessions; closing the descriptor releases the kernel lock.
    with open(LIVE_LOCK, "a", encoding="ascii") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("이 컨테이너에서 다른 실기체 텔레옵이 실행 중입니다.") from error
        yield


class TerminalKeys:
    """Accept one fresh key or standard arrow. Consume reports and pasted text."""

    exit_key = "\x04"
    commands = b"kKqzwxecf?+-=!@#$ \r\n\x03\x04" + "".join((*VELOCITY, *MODES)).encode("ascii")
    arrows = {ord("A"): "i", ord("B"): ",", ord("C"): "l", ord("D"): "j"}

    def __init__(self):
        self.state = "normal"
        self.sequence = b""
        self.arrow_started = 0.0
        self.clean_arrow = False
        self.mouse_bytes = 0

    def read(self, data, repeat_key=None):
        if not data:
            return self.exit_key
        # SSH may deliver several identical autorepeat arrows in one read.
        if (self.state == "normal" and repeat_key and len(data) > 3 and
                data[:2] in (b"\x1b[", b"\x1bO") and self.arrows.get(data[2]) == repeat_key and
                data == data[:3] * (len(data) // 3)):
            return repeat_key
        if len(data) > 1 and self.state == "normal" and all(byte in self.commands for byte in data):
            # A new stop/exit can arrive next to an old key while an RPC was
            # blocked. Never replay movement or mode changes from that buffer.
            if any(byte in (3, 4) for byte in data):
                return self.exit_key
            if any(byte in b"kK " for byte in data):
                return " "
            if repeat_key and data == repeat_key.encode("ascii") * len(data):
                return repeat_key
            return "\x1b"
        now = time.monotonic()
        if self.state == "esc" and len(data) == 1 and data[0] in self.commands:
            if now - self.arrow_started > 0.15:
                self.state = "normal"  # Independent key after a standalone Esc.
        for i, byte in enumerate(data):
            if self.state == "paste":
                self.sequence = (self.sequence + bytes([byte]))[-6:]
                if self.sequence == b"\x1b[201~":
                    self.state = "normal"
            elif self.state == "string":
                self.sequence = (self.sequence + bytes([byte]))[-2:]
                if byte in (7, 0x9c) or self.sequence == b"\x1b\\":
                    self.state = "normal"
            elif self.state == "mouse":
                self.mouse_bytes -= 1
                if self.mouse_bytes == 0:
                    self.state = "normal"
            elif byte in (0x9d, 0x90, 0x98, 0x9e, 0x9f):
                self.state = "string"
                self.sequence = b""
            elif byte == 0x9b:
                self.state = "csi"
                self.sequence = b""
                self.clean_arrow = False
            elif byte == 27:
                self.clean_arrow = i == 0
                self.arrow_started = now
                self.state = "esc"
                self.sequence = b""
            elif self.state == "esc":
                if byte in b"[O":
                    self.state = "csi" if byte == ord("[") else "ss3"
                elif byte in b"]PX^_":
                    self.state = "string"
                elif 0x20 <= byte <= 0x2f:
                    self.state = "esc-intermediate"
                else:
                    self.state = "normal"
            elif self.state == "esc-intermediate":
                if 0x30 <= byte <= 0x7e:
                    self.state = "normal"
            elif self.state in ("csi", "ss3"):
                if 0x40 <= byte <= 0x7e:
                    if (byte in self.arrows and not self.sequence and self.clean_arrow
                            and i == len(data) - 1 and now - self.arrow_started <= 0.15):
                        self.state = "normal"
                        return self.arrows[byte]
                    if byte == ord("M") and self.state == "csi" and not self.sequence:
                        self.state = "mouse"
                        self.mouse_bytes = 3
                        continue
                    if byte == ord("~") and self.sequence == b"200":
                        self.state = "paste"
                        self.sequence = b""
                    else:
                        self.state = "normal"
                else:
                    self.sequence = (self.sequence + bytes([byte]))[:4]
            elif len(data) == 1 and byte in self.commands:
                return self.exit_key if byte in (3, 4) else chr(byte)
        return "\x1b"  # Cancel any pending mode when input is ambiguous.


@contextmanager
def keyboard_terminal(fd, on_signal):
    saved = termios.tcgetattr(fd)
    previous = {}

    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGTSTP):
            previous[sig] = signal.signal(sig, on_signal)
        tty.setcbreak(fd, termios.TCSAFLUSH)
        # Request bracketed paste from compatible terminals.
        sys.stdout.write("\x1b[?2004h")
        sys.stdout.flush()
        yield
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSAFLUSH, saved)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            sys.stdout.write("\x1b[?2004l")
            sys.stdout.flush()


def poll_queued(fd, keys, repeat_key, pending=None):
    """Keep stops or one repeat of current motion, never a buffered direction change."""
    if pending == keys.exit_key:
        return pending
    if pending in VELOCITY and pending != repeat_key:
        pending = "\x1b"
    while select.select([fd], [], [], 0)[0]:
        data = os.read(fd, 4096)
        key = keys.read(data, repeat_key)
        if key == keys.exit_key:
            return key
        keys.clean_arrow = False  # A queued arrow prefix must stay stale.
        if key in ("k", "K", " "):
            pending = " "
        elif pending != " ":
            if key != repeat_key:
                pending = "\x1b"
            elif pending is None:
                pending = key
    return pending


def show(message, prefix=""):
    if message:
        print(prefix + message.replace("\n", "\n" + prefix), flush=True)


def interact(controller, *, live=False):
    fd = sys.stdin.fileno()
    keys = TerminalKeys()
    prefix = "[실기체] " if live else "[모의] "
    pending = None

    def input_waiting():
        return bool(select.select([fd], [], [], 0)[0])

    def cancel_requested():
        nonlocal pending
        # A repeat during GetFsmId may renew this direction. A stop takes priority.
        pending = poll_queued(fd, keys, key, pending)
        return pending is not None and pending != key

    def request_exit(_signum, _frame):
        # The SDK catches exceptions inside its RPC wait. Latch Ctrl+C instead,
        # and let any ongoing send/receive finish before sending the final zero.
        controller.exit_requested = True

    help_text = mode_menu(controller.modes) + KEY_HELP
    with keyboard_terminal(fd, request_exit):
        try:
            show(help_text, prefix)
            show("준비 · i 전진, k 정지", prefix)
            if live:
                show("키 입력이 기체로 전송됩니다. 802 내장 보행기는 팔을 흔들 수 있습니다.", prefix)
            while not controller.exit_requested:
                if pending is None:
                    received_at = time.monotonic()
                    message = controller.tick(input_waiting)
                    if controller.exit_requested:
                        break
                    if message is not None:
                        pending = poll_queued(fd, keys, controller.moving_key)
                        show(message, prefix)
                if pending is None:
                    if not select.select([fd], [], [], 0.05)[0]:
                        continue
                    received_at = time.monotonic()
                    pending = keys.read(os.read(fd, 4096), controller.moving_key)
                key, pending = pending, None
                if key == keys.exit_key or controller.exit_requested:
                    break
                started = time.monotonic()
                message = controller.handle("\x1b" if key == "?" else key, received_at=received_at,
                                            cancel_requested=cancel_requested)
                if controller.exit_requested:
                    break
                pending = poll_queued(fd, keys, controller.moving_key, pending)
                received_at = started  # An input waiting after the RPC may be this old.
                show(message, prefix)
                if key == "?":
                    show(help_text, prefix)
                    show(EXTRA_HELP, prefix)
        finally:
            show(controller.close(force_stop=live), prefix)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="g1 teleop", description="G1 고수준 보행 키보드 제어")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="실제 G1 키보드 제어")
    mode.add_argument("--preview", action="store_true", help="시작 시 실제 FSM·모터 상태를 읽고 키 입력은 모의 실행")
    mode.add_argument("--dry-run", action="store_true", help="오프라인 모의 제어 (기본값)")
    mode.add_argument("--feedback", action="store_true", help="이동 중 G1 오도메트리 위치·속도 수신 (읽기 전용)")
    mode.add_argument("--status", action="store_true", help="실제 G1의 FSM·보행 상태·서비스 API 버전 조회")
    parser.add_argument("--interface", metavar="NIC", help="G1 연결 인터페이스")
    parser.add_argument("--domain", type=int, default=os.getenv("ROS_DOMAIN_ID") or "0",
                        help="DDS 도메인 ID (기본 ROS_DOMAIN_ID 또는 0)")
    parser.add_argument("--service", choices=("auto", "sport", "loco"), default="auto",
                        help="GetFsmId로 확인할 로코모션 서비스 (기본 auto)")
    parser.add_argument("--run-fsm", type=int, choices=RUN_IDS,
                        help="2번 키로 요청할 Run ID (기본: 시작 시 확인된 801/802, 그 외에는 연구실 802)")
    parser.add_argument("--waist-3dof", action="store_true", help="허리 3자유도 모델의 FSM 501 허용")
    args = parser.parse_args(argv)
    if (args.live or args.preview or args.status or args.feedback) and not args.interface:
        parser.error("--live / --preview / --status / --feedback 실행에는 --interface NIC가 필요합니다.")
    if args.domain < 0:
        parser.error("--domain은 0 이상의 정수여야 합니다.")
    if not (args.status or args.feedback) and not (sys.stdin.isatty() and sys.stdout.isatty()):
        parser.error("키보드 제어에는 대화형 TTY가 필요합니다. Docker에서는 -it를 사용하세요.")
    try:
        if args.feedback:
            from .feedback import watch_odometry
            watch_odometry(args.interface, args.domain)
            return 0
        with live_session_lock() if args.live else nullcontext():
            if args.live or args.preview or args.status:
                network = f"NIC={args.interface} · DDS domain={args.domain}"
                try:
                    if args.preview:
                        from .preview import read_robot_snapshot
                        service, fsm, motors = read_robot_snapshot(
                            args.interface, args.domain, args.service, discover)
                    else:
                        client, service, fsm = connect(args.domain, args.interface, args.service)
                except Exception as error:
                    raise RuntimeError(f"{network} · service={args.service} · {error}") from error
                show(f"현재 FSM={display_fsm(fsm)} · {network} · service={service}",
                     "[시작 시점 실측] " if args.preview else "")
                if args.preview:
                    show(f"모터 상태 · {motors}", "[시작 시점 실측] ")
                    show("FSM과 모터 상태는 시작 시점에만 읽었습니다. 지금부터 키 입력과 f 조회는 모두 모의 실행입니다.")
                    client = DryClient(fsm)
                if args.status:
                    from .services import motion_service_details
                    from .status import status_details
                    show(status_details(client))
                    show(motion_service_details())
                    return 0
            else:
                client = DryClient()
                fsm = client.fsm
                show(f"오프라인 모의 제어 · 초기 FSM={display_fsm(fsm)}")
            default_run = fsm if fsm in RUN_IDS else LAB_RUN_FSM
            controller = Controller(client, waist_3dof=args.waist_3dof, run_fsm=args.run_fsm or default_run)
            interact(controller, live=args.live)
    except EndSession:
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ImportError, RuntimeError, termios.error) as error:
        print(f"텔레오퍼레이션 오류: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
