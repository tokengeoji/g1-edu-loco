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
    "2": ("fsm", 802, "이 기체의 이동 모드 · FSM 802"),
    "m": ("fsm", 500, "일반 보행 · Regular/Walk Motion · FSM 500"),
    "3": ("fsm", 2, "위치 제어 쪼그림 · 균형 제어 없음 · 기체 지지 확인"),
    "4": ("balance", 0, "균형 기립 · 정지·안정 시 제자리걸음 해제"),
    "5": ("balance", 1, "연속 제자리걸음 · 속도 0에서도 발 디딤"),
    "6": ("fsm", 706, "균형 쪼그림 ↔ 기립 전환 · 현재 자세 확인"),
    "7": ("fsm", 3, "의자에 앉기 · 의자 위치와 기체 지지 확인"),
    "8": ("fsm", 501, "허리 3자유도 보행"),
    "9": ("fsm", 3, "의자에 앉기 · 의자 위치와 기체 지지 확인"),
    "0": ("fsm", 1, "댐핑 · 균형 제어가 해제되므로 기체 지지 확인"),
}


# Unitree SetSpeedMode selects a running-mode upper limit, independent of the
# velocities in individual SetVelocity requests. No speed setting is sent at startup.
SPEED_LIMITS = {"!": (0, 1.0), "@": (1, 2.0), "#": (2, 2.7), "$": (3, 3.0)}
GAIT_IDS = (802, 501)


class Controller:
    """Dispatch one fresh key at a time. Merely constructing this class sends nothing."""

    def __init__(self, client, *, waist_3dof=False, clock=time.monotonic):
        self.client = client
        self.waist_3dof = waist_3dof
        self.clock = clock
        self.speed_scale = 1.0
        self._moving_key = None
        self._motion_deadline = 0.0
        self._pending = None
        self._confirm_deadline = 0.0
        self._awaiting_fsm = None
        self._regular_walk_selected = False

    @staticmethod
    def _check(operation, code):
        if code != 0:
            raise RuntimeError(f"{operation} RPC code={code}")

    def _fsm(self):
        code, value = self.client.GetFsmId()
        self._check("GetFsmId", code)
        if type(value) is not int or value < 0:
            raise RuntimeError(f"GetFsmId 응답에 유효한 ID가 없습니다: {value!r}")
        # While entering 500 the robot may still report its previous mode.
        # Once 500 is verified, any observed departure cancels that selection.
        if value != 500 and self._awaiting_fsm != 500:
            self._regular_walk_selected = False
        if value == self._awaiting_fsm:
            self._awaiting_fsm = None
        return value

    def _stop(self, force=False):
        if force or self._moving_key:
            self._check("SetVelocity(0)", self.client.SetVelocity(0.0, 0.0, 0.0, PULSE_SECONDS))
        self._moving_key = None

    def _fault(self, error):
        self._pending = None
        try:
            self._stop()
        except Exception as stop_error:
            self._moving_key = None
            return f"RPC 오류: {error}. 속도 0 응답도 확인하지 못했습니다: {stop_error}. 조종기를 확인하세요."
        return f"RPC 오류: {error}. 직전 명령을 중단했습니다. 다음 입력에서 기체 상태를 다시 확인합니다."

    def _status(self, current):
        text = f"현재 FSM={current} · 속도 {self.speed_scale:g}배"
        if current == 500:
            text += " · 일반 보행 선택됨" if self._regular_walk_selected else " · 일반 보행 선택: m → Enter"
        if self._awaiting_fsm is not None:
            text += f" · 요청한 FSM {self._awaiting_fsm} 진입 미확인"
        return text

    def _check_mode(self, current, allowed_modes, hint):
        if self._awaiting_fsm is not None:
            return self._status(current)
        if current == 501 and not self.waist_3dof:
            return "FSM 501입니다. 허리 3자유도 모델 확인 후 --waist-3dof로 실행하세요."
        if current not in allowed_modes:
            return f"현재 FSM={current}. {hint}"
        return None

    def _confirm(self, selected):
        kind, value, label = MODES[selected]
        if kind == "fsm":
            self._regular_walk_selected = False
        current = self._fsm()
        if current == 1000:
            return "FSM 1000(사용자 제어)입니다. 내장 보행기 명령을 전송하지 않았습니다."
        if kind == "balance":
            blocked = self._check_mode(current, (500, 501), "제자리걸음 설정은 Walk Motion(500/501)에서 사용하세요.")
            if blocked:
                return blocked
            self._check("SetBalanceMode", self.client.SetBalanceMode(value))
            return f"보행 설정 요청 수락: {label} (SetBalanceMode={value}). 실제 발 디딤을 확인하세요."

        if value == 500 and current == 500:
            self._regular_walk_selected = True
            self._awaiting_fsm = None
            return self._status(current)
        if value in GAIT_IDS and current == value and self._awaiting_fsm is None:
            return self._status(current)
        # Remember the request even when its acknowledgment is lost.
        self._awaiting_fsm = value
        self._check("SetFsmId", self.client.SetFsmId(value))
        self._regular_walk_selected = value == 500
        if value == 706:
            # This is a toggle, so never retry it automatically. Re-select a
            # gait after the robot settles if the transient ID was not observed.
            return f"{label} 요청 수락. 자세를 확인하고 이동할 보행 모드를 선택하세요."
        return f"FSM {value} 요청 수락 · {self._status(self._fsm())}"

    def _move(self, key):
        deadline = self.clock() + PULSE_SECONDS
        current = self._fsm()
        allowed = (*GAIT_IDS, 500) if self._regular_walk_selected else GAIT_IDS
        blocked = self._check_mode(current, allowed, "기본 보행 802는 2 → Enter, 일반 보행 500은 m → Enter로 선택하세요.")
        if blocked:
            self._stop()
            return blocked
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
        """Return an operator message or None. On RPC failure, discard motion and wait for a fresh input."""
        try:
            if key in ("\r", "\n"):
                selected, self._pending = self._pending, None
                if selected is None:
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
            if key == "x":
                return self.close()
            if key == "f":
                return self._status(self._fsm())
            if previous is not None and key not in MODES:
                return "모드 선택을 취소했습니다."
            if key in ("+", "-", "="):
                delta = -0.25 if key == "-" else 0.25
                self.speed_scale = max(0.5, min(2.0, self.speed_scale + delta))
                return f"속도 {self.speed_scale:g}배 · 다음 이동 입력부터 적용합니다."
            if key in SPEED_LIMITS:
                current = self._fsm()
                blocked = self._check_mode(current, (802,), "달리기 속도 상한은 FSM 802에서 설정하세요.")
                if blocked:
                    return blocked
                mode, limit = SPEED_LIMITS[key]
                self._check("SetSpeedMode", self.client.SetSpeedMode(mode))
                return f"SetSpeedMode({mode}) 수락 · 달리기 속도 상한 {limit:.1f} m/s."
            if key not in VELOCITY and key not in MODES:
                return None
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
        self._pending = self._awaiting_fsm = None
        self._regular_walk_selected = False
        try:
            self._stop()
        except Exception as error:
            return self._fault(error)
        return "텔레옵을 종료했습니다."
