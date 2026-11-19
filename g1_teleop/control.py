# Author: Codex (IIC)
"""Keyboard commands for a G1 high-level LocoClient. All durations are in seconds."""

import time


PULSE_SECONDS = 0.25
CONFIRM_SECONDS = 4.0
# Forward and left are positive (m/s). Positive yaw is a left turn (rad/s).
VELOCITY = {
    "w": (0.15, 0.0, 0.0), "s": (-0.15, 0.0, 0.0),
    "a": (0.0, 0.10, 0.0), "d": (0.0, -0.10, 0.0),
    "q": (0.0, 0.0, 0.30), "e": (0.0, 0.0, -0.30),
}
# An explicit Enter confirms the selected request. Never interpret an arbitrary
# integer or a repeated key as an FSM command.
MODES = {
    "1": ("fsm", 4, "잠금 기립 · 균형 제어 없음 · 기체 지지 확인"),
    "2": ("fsm", 500, "기본 보행"),
    "3": ("fsm", 2, "위치 제어 쪼그림 · 균형 제어 없음 · 기체 지지 확인"),
    "4": ("balance", 0, "균형 기립 · 정지·안정 시 제자리걸음 해제"),
    "5": ("balance", 1, "연속 제자리걸음 · 속도 0에서도 발 디딤"),
    "6": ("fsm", 706, "균형 쪼그림 ↔ 기립 전환 · 현재 자세 확인"),
    "7": ("fsm", 3, "의자에 앉기 · 의자 위치와 기체 지지 확인"),
    "8": ("fsm", 501, "허리 3자유도 보행"),
    "9": ("fsm", 3, "의자에 앉기 · 의자 위치와 기체 지지 확인"),
    "0": ("fsm", 1, "댐핑 · 균형 제어가 해제되므로 기체 지지 확인"),
}


class Controller:
    """Dispatch one fresh key at a time. Merely constructing this class sends nothing."""

    def __init__(self, client, *, waist_3dof=False, clock=time.monotonic):
        self.client = client
        self.waist_3dof = waist_3dof
        self.clock = clock
        self.armed = False
        self.speed_scale = 1.0
        self._moving_key = None
        self._motion_deadline = 0.0
        self._pending = None
        self._confirm_deadline = 0.0
        self._awaiting_fsm = None

    @staticmethod
    def _check(operation, code):
        if code != 0:
            raise RuntimeError(f"{operation} RPC code={code}")

    def _fsm(self):
        code, value = self.client.GetFsmId()
        self._check("GetFsmId", code)
        if type(value) is not int or value < 0:
            raise RuntimeError(f"GetFsmId 응답에 유효한 ID가 없습니다: {value!r}")
        return value

    def _stop(self, force=False):
        if force or self._moving_key:
            self._check("SetVelocity(0)", self.client.SetVelocity(0.0, 0.0, 0.0, PULSE_SECONDS))
        self._moving_key = None

    def _fault(self, error):
        self.armed = False
        self._pending = self._awaiting_fsm = None
        try:
            self._stop()
        except Exception as stop_error:
            self._moving_key = None
            return f"RPC 오류: {error}. 속도 0 응답도 확인하지 못했습니다: {stop_error}. 조종기를 확인하세요."
        return f"RPC 오류: {error}. 키보드 제어를 해제했습니다. 상태를 확인하고 r로 재개하세요."

    def _walk_mode(self, current):
        if current not in (500, 501):
            return f"현재 FSM={current}. 보행 모드 500/501에서만 이동과 보행 설정을 적용합니다."
        if current == 501 and not self.waist_3dof:
            return "FSM 501입니다. 허리 3자유도 모델 확인 후 --waist-3dof로 실행하세요."
        return None

    def _status(self, current):
        if self._awaiting_fsm == current:
            self._awaiting_fsm = None
        text = f"현재 FSM={current} · 키보드 {'활성' if self.armed else '비활성'} · 속도 {self.speed_scale:g}배"
        if self._awaiting_fsm is not None:
            text += f" · 요청한 FSM {self._awaiting_fsm} 진입 미확인"
        return text

    def _confirm(self, selected):
        kind, value, label = MODES[selected]
        current = self._fsm()
        if current == 1000:
            self.armed = False
            return "FSM 1000(사용자 제어)입니다. 키보드 제어를 해제했습니다."
        if kind == "balance":
            blocked = self._walk_mode(current)
            if current == self._awaiting_fsm:
                self._awaiting_fsm = None
            if blocked or self._awaiting_fsm is not None:
                return blocked or self._status(current)
            self._check("SetBalanceMode", self.client.SetBalanceMode(value))
            return f"보행 설정 요청 수락: {label} (SetBalanceMode={value}). 실제 발 디딤을 확인하세요."

        self._check("SetFsmId", self.client.SetFsmId(value))
        if value == 706:
            # 706 is a posture toggle. Do not poll until 706 or repeat a request
            # when its terminal state is not 706.
            self.armed = False
            self._awaiting_fsm = None
            return f"{label} 요청 수락. 자세가 안정되면 f로 조회하고 r로 재개하세요."
        self._awaiting_fsm = value
        return f"FSM {value} 요청 수락 · {self._status(self._fsm())}"

    def _move(self, key):
        deadline = self.clock() + PULSE_SECONDS
        current = self._fsm()
        if self._awaiting_fsm == current:
            self._awaiting_fsm = None
        blocked = self._walk_mode(current)
        if blocked or self._awaiting_fsm is not None:
            self._stop()
            return blocked or self._status(current)
        duration = deadline - self.clock()
        if duration <= 0:
            self._stop()
            return "상태 조회 중 키 입력이 만료되었습니다. 다시 입력하세요."
        repeated = key == self._moving_key
        # The request may reach the server even if the reply is lost.
        self._moving_key = key
        self._motion_deadline = deadline
        velocity = tuple(axis * self.speed_scale for axis in VELOCITY[key])
        self._check("SetVelocity", self.client.SetVelocity(*velocity, duration))
        if not repeated:
            return f"{key.upper()} · 속도 (vx, vy, yaw)={velocity}"
        return None

    def handle(self, key):
        """Return an operator message or None. RPC failures disarm the controller."""
        try:
            if key in ("\r", "\n"):
                selected, self._pending = self._pending, None
                if selected is None or not self.armed:
                    return None
                if self.clock() >= self._confirm_deadline:
                    return "모드 선택 시간이 지났습니다."
                return self._confirm(selected)

            if self._pending is not None and self._pending == key:
                return None  # Key repeat neither confirms nor extends the deadline.
            previous, self._pending = self._pending, None
            if key == " ":
                self._stop(force=True)
                return "속도 0 요청 수락."
            if key in ("x", "g"):
                return self.close()
            if key == "f":
                return self._status(self._fsm())
            if key == "r":
                self._stop()
                state = self._fsm()
                if state == 1000:
                    self.armed = False
                    return "FSM 1000(사용자 제어)입니다. 내장 제어 모드를 확인하세요."
                self.armed = True
                return self._status(state)
            if previous is not None and key not in MODES:
                return "모드 선택을 취소했습니다."
            if key in ("+", "-", "="):
                delta = -0.25 if key == "-" else 0.25
                self.speed_scale = max(0.5, min(2.0, self.speed_scale + delta))
                return f"속도 {self.speed_scale:g}배 · 다음 이동 입력부터 적용합니다."
            if key not in VELOCITY and key not in MODES:
                return None
            if not self.armed:
                return "키보드 제어가 꺼져 있습니다. r로 현재 상태를 확인하고 활성화하세요."
            if key in MODES:
                self._stop()
                if key == "8" and not self.waist_3dof:
                    return "허리 3자유도 모델 확인 후 --waist-3dof로 실행하세요."
                self._pending = key
                self._confirm_deadline = self.clock() + CONFIRM_SECONDS
                return f"{MODES[key][2]} · 4초 이내 Enter로 요청, Esc로 취소."
            return self._move(key)
        except Exception as error:
            return self._fault(error)

    def tick(self):
        """Expire a pending action or stop on input timeout. Never resend motion."""
        now = self.clock()
        if self._pending is not None and now >= self._confirm_deadline:
            self._pending = None
            return "모드 선택 시간이 지났습니다."
        if self._moving_key and now >= self._motion_deadline:
            try:
                self._stop()
            except Exception as error:
                return self._fault(error)
            return "키 반복 입력 만료 · 속도 0 요청 수락."
        return None

    def close(self):
        self.armed = False
        self._pending = self._awaiting_fsm = None
        try:
            self._stop()
        except Exception as error:
            return self._fault(error)
        return "키보드 제어를 해제했습니다."
