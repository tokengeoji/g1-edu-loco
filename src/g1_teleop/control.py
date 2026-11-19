# Author: Codex (IIC)
"""Keyboard commands for a G1 high-level LocoClient. All durations are in seconds."""

import time


# LocoClient.Move(..., continous_move=False) uses a one-second SetVelocity.
# Keep that upper bound on the robot even if the SSH session disappears.
PULSE_SECONDS = 1.0
REPEAT_INTERVAL = 0.1
CONFIRM_SECONDS = 4.0
# ROS 2 teleop_twist_keyboard's planar keys. Axes: forward (m/s), left (m/s),
# left turn (rad/s). G1 retains its existing, conservative starting velocities.
VELOCITY = {
    "u": (0.15, 0.0, 0.3), "i": (0.15, 0.0, 0.0), "o": (0.15, 0.0, -0.3),
    "j": (0.0, 0.0, 0.3),                           "l": (0.0, 0.0, -0.3),
    "m": (-0.15, 0.0, -0.3), ",": (-0.15, 0.0, 0.0), ".": (-0.15, 0.0, 0.3),
    "U": (0.15, 0.10, 0.0), "I": (0.15, 0.0, 0.0), "O": (0.15, -0.10, 0.0),
    "J": (0.0, 0.10, 0.0),                           "L": (0.0, -0.10, 0.0),
    "M": (-0.15, 0.10, 0.0), "<": (-0.15, 0.0, 0.0), ">": (-0.15, -0.10, 0.0),
}
SPEED_FACTORS = {
    "q": (1.1, 1.1), "z": (0.9, 0.9),
    "w": (1.1, 1.0), "x": (0.9, 1.0),
    "e": (1.0, 1.1), "c": (1.0, 0.9),
}
# An explicit Enter confirms the selected request. Never interpret an arbitrary
# integer or a repeated key as an FSM command.
MODES = {
    "1": ("fsm", 4, "잠금 기립 · 균형 제어 없음 · 기체 지지 확인"),
    "2": ("fsm", 802, "이 기체의 이동 모드 · FSM 802"),
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
        self.linear_scale = self.turn_scale = 1.0
        self._last_move_sent = 0.0
        self._moving_key = None
        self._motion_deadline = 0.0
        self._pending = None
        self._confirm_deadline = 0.0
        self._awaiting_fsm = None

    @property
    def moving_key(self):
        return self._moving_key

    @staticmethod
    def _check(operation, code):
        if code != 0:
            raise RuntimeError(f"{operation} RPC code={code}")

    def _fsm(self):
        code, value = self.client.GetFsmId()
        self._check("GetFsmId", code)
        if type(value) is not int or value < 0:
            raise RuntimeError(f"GetFsmId 응답에 유효한 ID가 없습니다: {value!r}")
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
        text = f"현재 FSM={current} · 선속도 {self.linear_scale:g}배 · 회전 {self.turn_scale:g}배"
        if current == 500:
            text += " · 이 기체에서 FSM 500 이동은 확인되지 않았습니다. 2 → Enter로 802를 선택하세요."
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
        current = self._fsm()
        if current == 1000:
            return "FSM 1000(사용자 제어)입니다. 내장 보행기 명령을 전송하지 않았습니다."
        if kind == "balance":
            blocked = self._check_mode(current, (500, 501), "제자리걸음 설정은 Walk Motion(500/501)에서 사용하세요.")
            if blocked:
                return blocked
            self._check("SetBalanceMode", self.client.SetBalanceMode(value))
            return f"보행 설정 요청 수락: {label} (SetBalanceMode={value}). 실제 발 디딤을 확인하세요."

        if value in GAIT_IDS and current == value and self._awaiting_fsm is None:
            return self._status(current)
        # Remember the request even when its acknowledgment is lost.
        self._awaiting_fsm = value
        self._check("SetFsmId", self.client.SetFsmId(value))
        if value == 706:
            # This is a toggle, so never retry it automatically. Re-select a
            # gait after the robot settles if the transient ID was not observed.
            return f"{label} 요청 수락. 자세를 확인하고 이동할 보행 모드를 선택하세요."
        return f"FSM {value} 요청 수락 · {self._status(self._fsm())}"

    def _move(self, key, received_at):
        now = self.clock()
        deadline = min(now, received_at) + PULSE_SECONDS
        if now >= deadline:
            self._stop()
            return "이동 입력 시간이 만료되었습니다. 키를 다시 누르세요."
        repeated = key == self._moving_key
        if repeated and now - self._last_move_sent < REPEAT_INTERVAL:
            return None
        current = self._fsm()
        blocked = self._check_mode(current, GAIT_IDS, "이 기체의 이동 모드는 2 → Enter로 FSM 802를 선택하세요.")
        if blocked:
            self._stop()
            return blocked
        now = self.clock()
        duration = deadline - now
        if duration <= 0:
            self._stop()
            return "상태 조회 중 이동 입력 시간이 만료되었습니다. 키를 다시 누르세요."
        # The request may reach the server even if the reply is lost.
        self._moving_key = key
        self._motion_deadline = deadline
        self._last_move_sent = now
        vx, vy, yaw = VELOCITY[key]
        vx, vy, yaw = vx * self.linear_scale, vy * self.linear_scale, yaw * self.turn_scale
        self._check("SetVelocity(7105)", self.client.SetVelocity(vx, vy, yaw, duration))
        if not repeated:
            return (f"SetVelocity(7105) 수락 · FSM={current} · "
                    f"vx={vx:.3f} vy={vy:.3f} m/s yaw={yaw:.3f} rad/s · {duration:.2f}초")
        return None

    def _adjust_speed(self, key):
        if key in SPEED_FACTORS:
            linear_factor, turn_factor = SPEED_FACTORS[key]
            linear = self.linear_scale * linear_factor
            turn = self.turn_scale * turn_factor
        else:
            change = -0.25 if key == "-" else 0.25
            linear = self.linear_scale + change
            turn = self.turn_scale + change
        self.linear_scale = min(2.0, max(0.5, linear))
        self.turn_scale = min(2.0, max(0.5, turn))
        return (f"선속도 {self.linear_scale:g}배 · 회전 {self.turn_scale:g}배 · "
                "다음 이동 입력부터 적용합니다.")

    def handle(self, key, *, received_at=None):
        """Dispatch a single operator event. Never renew a command from an expired input."""
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
            if key in (" ", "k", "K"):
                self._stop(force=True)
                return "속도 0 요청 수락."
            if key == "f":
                return self._status(self._fsm())
            if previous is not None and key not in MODES:
                return "모드 선택을 취소했습니다."
            if key in SPEED_FACTORS or key in ("+", "-", "="):
                return self._adjust_speed(key)
            if key in SPEED_LIMITS:
                current = self._fsm()
                blocked = self._check_mode(current, (802,), "달리기 속도 상한은 FSM 802에서 설정하세요.")
                if blocked:
                    return blocked
                mode, limit = SPEED_LIMITS[key]
                self._check("SetSpeedMode", self.client.SetSpeedMode(mode))
                return f"SetSpeedMode({mode}) 수락 · 달리기 속도 상한 {limit:.1f} m/s."
            if key not in VELOCITY and key not in MODES:
                if self._moving_key:
                    self._stop()
                    return "이동 중단 · 속도 0 요청 수락."
                return None
            if key in MODES:
                self._stop()
                if key == "8" and not self.waist_3dof:
                    return "허리 3자유도 모델 확인 후 --waist-3dof로 실행하세요."
                self._pending = key
                self._confirm_deadline = self.clock() + CONFIRM_SECONDS
                return f"{MODES[key][2]} · 4초 이내 Enter로 요청, Esc로 취소."
            return self._move(key, self.clock() if received_at is None else received_at)
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
        try:
            self._stop()
        except Exception as error:
            return self._fault(error)
        return "텔레옵을 종료했습니다."
