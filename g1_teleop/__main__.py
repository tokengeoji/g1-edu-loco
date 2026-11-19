# Author: Codex (IIC)
"""Run the G1 locomotion terminal. The default simulation is offline."""

import argparse
import os
import select
import signal
import sys
import termios
import time
import tty
from contextlib import contextmanager

from .control import Controller, MODES


HELP = """r 제어 활성화    g 제어 해제    f 현재 FSM    ? 키 안내    x 종료
w/s 전진·후진    a/d 왼쪽·오른쪽 이동    q/e 좌회전·우회전
↑/↓ 전진·후진    ←/→ 좌회전·우회전    +/- 속도 조절
Space 속도 0    숫자 선택 후 별도로 Enter 확인    Esc 선택 취소
%s
이동 키는 0.25초 동안 적용됩니다. 연속 이동은 키를 반복 입력하세요.
Space는 이동 속도를 0으로 요청합니다. 연속 제자리걸음 해제는 4, Enter입니다.""" % "\n".join(
    f"  {key}  {mode[2]}" for key, mode in MODES.items()
)


class DryClient:
    def __init__(self):
        self.fsm = 4

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

    def SetVelocity(self, vx, vy, yaw, duration):
        print(f"[모의] SetVelocity({vx}, {vy}, {yaw}, {duration:.3f})", flush=True)
        return 0


def sdk_client(service):
    from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
    from unitree_sdk2py.rpc.client import Client

    class NamedLocoClient(LocoClient):
        def __init__(self):
            # LocoClient fixes its service in the constructor. Keep its official
            # API registration and request methods for either firmware name.
            Client.__init__(self, service, False)
            self.first_shake_hand_stage_ = -1

    client = NamedLocoClient()
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


class TerminalKeys:
    """Accept one fresh key or standard arrow. Consume reports and pasted text."""

    commands = b"wasdqergfx?+-0123456789 \r\n\x03\x04"
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
        if key == "g":
            priority = "g"
        elif key == " " and priority != "g":
            priority = " "
        elif not priority:
            priority = "\x1b"
    return priority


def show(message):
    if message:
        print(message, flush=True)


def interact(controller):
    fd = sys.stdin.fileno()
    keys = TerminalKeys()
    with keyboard_terminal(fd):
        try:
            show(HELP)
            show("준비 · f 상태 조회, r 활성화")
            pending = None
            while True:
                if pending is None:
                    message = controller.tick()
                    if message:
                        pending = poll_queued(fd, keys)
                        show(message)
                if pending is None:
                    if not select.select([fd], [], [], 0.05)[0]:
                        continue
                    pending = keys.read(os.read(fd, 4096))
                key, pending = pending, None
                if key == "x":
                    break
                message = controller.handle("\x1b" if key == "?" else key)
                pending = poll_queued(fd, keys)
                show(message)
                if key == "?":
                    show(HELP)
        finally:
            show(controller.close())


def main(argv=None):
    parser = argparse.ArgumentParser(description="G1 고수준 보행 키보드 제어")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="실제 G1 키보드 제어")
    mode.add_argument("--dry-run", action="store_true", help="오프라인 모의 제어 (기본값)")
    mode.add_argument("--status", action="store_true", help="실제 G1의 현재 FSM을 한 번 조회")
    parser.add_argument("--interface", metavar="NIC", help="G1 연결 인터페이스")
    parser.add_argument("--domain", type=int, default=os.getenv("ROS_DOMAIN_ID") or "0",
                        help="DDS 도메인 ID (기본 ROS_DOMAIN_ID 또는 0)")
    parser.add_argument("--service", choices=("auto", "sport", "loco"), default="auto",
                        help="GetFsmId로 확인할 로코모션 서비스 (기본 auto)")
    parser.add_argument("--waist-3dof", action="store_true", help="허리 3자유도 모델의 FSM 501 허용")
    args = parser.parse_args(argv)
    if (args.live or args.status) and not args.interface:
        parser.error("--live / --status 실행에는 --interface NIC가 필요합니다.")
    if args.domain < 0:
        parser.error("--domain은 0 이상의 정수여야 합니다.")
    if not args.status and not (sys.stdin.isatty() and sys.stdout.isatty()):
        parser.error("키보드 제어에는 대화형 TTY가 필요합니다. Docker에서는 -it를 사용하세요.")
    try:
        if args.live or args.status:
            network = f"NIC={args.interface} · DDS domain={args.domain}"
            try:
                client, service, fsm = connect(args.domain, args.interface, args.service)
            except Exception as error:
                raise RuntimeError(f"{network} · service={args.service} · {error}") from error
            show(f"현재 FSM={fsm} · {network} · service={service}")
            if args.status:
                return 0
        else:
            client = DryClient()
            show("오프라인 모의 제어 · 초기 FSM=4")
        interact(Controller(client, waist_3dof=args.waist_3dof))
    except EndSession:
        return 0
    except (OSError, ImportError, RuntimeError, termios.error) as error:
        print(f"텔레오퍼레이션 오류: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
