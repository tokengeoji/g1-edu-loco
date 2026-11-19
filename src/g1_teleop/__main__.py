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

from .control import Controller, MODES


HELP = """f 현재 FSM    ? 키 안내    x 종료
w/s 전진·후진    a/d 왼쪽·오른쪽 이동    q/e 좌회전·우회전
↑/↓ 전진·후진    ←/→ 좌회전·우회전    +/- 이동 속도 배율
!/@/#/$ (Shift+1/2/3/4) FSM 802 속도 상한 단계 0/1/2/3
Space 속도 0    모드 키를 누른 뒤 Enter로 요청    Esc 선택 취소
%s
이동 키는 0.25초 동안 적용됩니다. 연속 이동은 키를 반복 입력하세요.
Space는 이동 속도를 0으로 요청합니다.
FSM 802에서는 내장 보행기가 팔을 흔들 수 있습니다. 키보드에서 팔 자세 명령을 보내지 않습니다.""" % "\n".join(
    f"  {key}  {mode[2]}" for key, mode in MODES.items()
)


class DryClient:
    def __init__(self, fsm=802):
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

    commands = b"wasdqefx?+-=!@#$ \r\n\x03\x04" + "".join(MODES).encode("ascii")
    arrows = {ord("A"): "w", ord("B"): "s", ord("C"): "e", ord("D"): "q"}

    def __init__(self):
        self.state = "normal"
        self.sequence = b""
        self.arrow_started = 0.0
        self.clean_arrow = False
        self.mouse_bytes = 0

    def read(self, data):
        if not data:
            return "x"
        if len(data) > 1 and self.state == "normal" and all(byte in self.commands for byte in data):
            # A new stop/exit can arrive next to an old key while an RPC was
            # blocked. Never replay movement or mode changes from that buffer.
            if any(byte in b"x\x03\x04" for byte in data):
                return "x"
            return " " if b" " in data else "\x1b"
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
                return "x" if byte in (3, 4) else chr(byte)
        return "\x1b"  # Cancel any pending mode when input is ambiguous.


class EndSession(BaseException):
    pass


@contextmanager
def keyboard_terminal(fd):
    saved = termios.tcgetattr(fd)
    previous = {}

    def end_session(signum, _frame):
        raise EndSession(signum)

    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGTSTP):
            previous[sig] = signal.signal(sig, end_session)
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


def poll_queued(fd, keys):
    """Drop commands typed during an RPC, tracking paste/escape boundaries."""
    priority = None
    while select.select([fd], [], [], 0)[0]:
        data = os.read(fd, 4096)
        key = keys.read(data)
        if key == "x":
            return "x"
        keys.clean_arrow = False  # A queued arrow prefix must stay stale.
        if key == " ":
            priority = " "
        elif not priority:
            priority = "\x1b"
    return priority


def show(message, prefix=""):
    if message:
        print(prefix + message.replace("\n", "\n" + prefix), flush=True)


def interact(controller, *, preview=False):
    fd = sys.stdin.fileno()
    keys = TerminalKeys()
    prefix = "[모의] " if preview else ""
    with keyboard_terminal(fd):
        try:
            show(HELP, prefix)
            show("준비 · 방향키로 이동, f로 현재 모드 조회", prefix)
            pending = None
            while True:
                if pending is None:
                    message = controller.tick()
                    if message:
                        pending = poll_queued(fd, keys)
                        show(message, prefix)
                if pending is None:
                    if not select.select([fd], [], [], 0.05)[0]:
                        continue
                    pending = keys.read(os.read(fd, 4096))
                key, pending = pending, None
                if key == "x":
                    break
                message = controller.handle("\x1b" if key == "?" else key)
                pending = poll_queued(fd, keys)
                show(message, prefix)
                if key == "?":
                    show(HELP, prefix)
        finally:
            show(controller.close(), prefix)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="g1 teleop", description="G1 고수준 보행 키보드 제어")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="실제 G1 키보드 제어")
    mode.add_argument("--preview", action="store_true", help="시작 시 실제 FSM·모터 상태를 읽고 키 입력은 모의 실행")
    mode.add_argument("--dry-run", action="store_true", help="오프라인 모의 제어 (기본값)")
    mode.add_argument("--status", action="store_true", help="실제 G1의 현재 FSM을 한 번 조회")
    parser.add_argument("--interface", metavar="NIC", help="G1 연결 인터페이스")
    parser.add_argument("--domain", type=int, default=os.getenv("ROS_DOMAIN_ID") or "0",
                        help="DDS 도메인 ID (기본 ROS_DOMAIN_ID 또는 0)")
    parser.add_argument("--service", choices=("auto", "sport", "loco"), default="auto",
                        help="GetFsmId로 확인할 로코모션 서비스 (기본 auto)")
    parser.add_argument("--waist-3dof", action="store_true", help="허리 3자유도 모델의 FSM 501 허용")
    args = parser.parse_args(argv)
    if (args.live or args.preview or args.status) and not args.interface:
        parser.error("--live / --preview / --status 실행에는 --interface NIC가 필요합니다.")
    if args.domain < 0:
        parser.error("--domain은 0 이상의 정수여야 합니다.")
    if not args.status and not (sys.stdin.isatty() and sys.stdout.isatty()):
        parser.error("키보드 제어에는 대화형 TTY가 필요합니다. Docker에서는 -it를 사용하세요.")
    try:
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
                show(f"현재 FSM={fsm} · {network} · service={service}",
                     "[시작 시점 실측] " if args.preview else "")
                if args.preview:
                    show(f"모터 상태 · {motors}", "[시작 시점 실측] ")
                    show("FSM과 모터 상태는 시작 시점에만 읽었습니다. 지금부터 키 입력과 f 조회는 모두 모의 실행입니다.")
                    client = DryClient(fsm)
                if args.status:
                    return 0
            else:
                client = DryClient()
                show(f"오프라인 모의 제어 · 초기 FSM={client.fsm}")
            controller = Controller(client, waist_3dof=args.waist_3dof)
            interact(controller, preview=args.preview)
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
