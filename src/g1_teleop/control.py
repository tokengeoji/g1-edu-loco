# Author: Codex (IIC)
"""Keyboard commands for a G1 high-level LocoClient. All durations are in seconds."""

import math
import time


# LocoClient.Move(..., continous_move=False) uses a one-second SetVelocity.
# Keep that upper bound on the robot even if the SSH session disappears.
PULSE_SECONDS = 1.0
REPEAT_INTERVAL = 0.1
CONFIRM_SECONDS = 4.0
# Unitree's example forward speed is also the operator's pure-x limit.
MAX_STRAIGHT_SPEED = 0.30
# ROS 2 teleop_twist_keyboard's planar keys. Axes: forward (m/s), left (m/s),
# left turn (rad/s).
VELOCITY = {
    "u": (0.15, 0.0, 0.3), "i": (MAX_STRAIGHT_SPEED, 0.0, 0.0), "o": (0.15, 0.0, -0.3),
    "j": (0.0, 0.0, 0.3),                           "l": (0.0, 0.0, -0.3),
    "m": (-0.15, 0.0, -0.3), ",": (-MAX_STRAIGHT_SPEED, 0.0, 0.0), ".": (-0.15, 0.0, 0.3),
    "U": (0.15, 0.10, 0.0), "I": (MAX_STRAIGHT_SPEED, 0.0, 0.0), "O": (0.15, -0.10, 0.0),
    "J": (0.0, 0.10, 0.0),                           "L": (0.0, -0.10, 0.0),
    "M": (-0.15, 0.10, 0.0), "<": (-MAX_STRAIGHT_SPEED, 0.0, 0.0), ">": (-0.15, -0.10, 0.0),
}
SPEED_FACTORS = {
    "q": (1.1, 1.1), "z": (0.9, 0.9),
    "w": (1.1, 1.0), "x": (0.9, 1.0),
    "e": (1.0, 1.1), "c": (1.0, 0.9),
}
RUN_IDS = (801, 802)
LAB_RUN_FSM = 802  # Reported by GetFsmId on the lab G1.


def run_mode(fsm):
    return ("fsm", fsm, f"Run 보행 · FSM {fsm}")


# An explicit Enter confirms the selected request. Never interpret an arbitrary
# integer or a repeated key as an FSM command.
MODES = {
    "1": ("fsm", 4, "잠금 기립 · 균형 제어 없음 · 기체 지지 확인"),
    "2": run_mode(LAB_RUN_FSM),
    "3": ("fsm", 2, "위치 제어 쪼그림 · 균형 제어 없음 · 기체 지지 확인"),
    "4": ("balance", 0, "균형 기립 · 정지·안정 시 제자리걸음 해제"),
    "5": ("balance", 1, "연속 제자리걸음 · 속도 0에서도 발 디딤"),
    "6": ("fsm", 706, "균형 쪼그림 ↔ 기립 전환 · 현재 자세 확인"),
    "7": ("fsm", 3, "의자에 앉기 · 의자 위치와 기체 지지 확인"),
    "8": ("fsm", 501, "허리 3자유도 보행"),
    "9": ("fsm", 3, "의자에 앉기 · 의자 위치와 기체 지지 확인"),
    "v": ("fsm", 500, "일반 보행 · Unitree SDK Start의 FSM 500"),
    "0": ("fsm", 1, "댐핑 · 균형 제어가 해제되므로 기체 지지 확인"),
}


# Unitree SetSpeedMode selects a running-mode upper limit, independent of the
# velocities in individual SetVelocity requests. No speed setting is sent at startup.
SPEED_LIMITS = {"!": (0, 1.0), "@": (1, 2.0), "#": (2, 2.7), "$": (3, 3.0)}
GAIT_IDS = (*RUN_IDS, 500, 501)

FSM_NAMES = {
    value: label.partition(" · ")[0] for kind, value, label in MODES.values() if kind == "fsm"
}
FSM_NAMES.update({0: "제로 토크", 801: "Run 보행", 1000: "사용자 제어"})


def display_fsm(value):
    name = FSM_NAMES.get(value)
    return f"{value} ({name})" if name else str(value)


class EndSession(BaseException):
    """Leave the input loop after a deferred terminal signal."""


class Controller:
    """Dispatch one fresh key at a time. Merely constructing this class sends nothing."""

    def __init__(self, client, *, waist_3dof=False, run_fsm=LAB_RUN_FSM, straight_speed=None,
                 timed_velocity=False, clock=time.monotonic):
        if type(run_fsm) is not int or run_fsm not in RUN_IDS:
            raise ValueError(f"지원하지 않는 Run FSM: {run_fsm}")
        if straight_speed is not None and not 0 < straight_speed <= MAX_STRAIGHT_SPEED:
            raise ValueError(f"--straight-speed는 0보다 크고 {MAX_STRAIGHT_SPEED:.2f} m/s 이하여야 합니다.")
        self.straight_speed = straight_speed
        self.timed_velocity = timed_velocity
        self.modes = {**MODES, "2": run_mode(run_fsm)}
        self.client = client
        self.waist_3dof = waist_3dof
        self.clock = clock
        self.linear_scale = self.turn_scale = 1.0
        self.exit_requested = False
        self._last_move_sent = 0.0
        self._last_motion_check = 0.0
        self._last_stop_at = None
        self._moving_key = None
        self._motion_fsm = None
        self._velocity = (0.0, 0.0, 0.0)
        self._motion_deadline = 0.0
        self._input_count = 0
        self._accepted_count = 0
        self._pending = None
        self._confirm_deadline = 0.0
        self._awaiting_fsm = None

    @property
    def moving_key(self):
        return self._moving_key

    @property
    def active_input_deadline(self):
        return self._motion_deadline if self._moving_key is not None else None

    @staticmethod
    def _check(operation, code):
        if type(code) is not int or code != 0:
            raise RuntimeError(f"{operation} RPC code={code}")

    def _fsm(self):
        code, value = self.client.GetFsmId()
        # A signal during GetFsmId invalidates the key that triggered the read.
        if self.exit_requested:
            raise EndSession()
        self._check("GetFsmId", code)
        if type(value) is not int or value < 0:
            raise RuntimeError(f"GetFsmId 응답에 유효한 ID가 없습니다: {value!r}")
        if value == self._awaiting_fsm:
            self._awaiting_fsm = None
        return value

    def _stop(self, force=False):
        if force or self._moving_key:
            self._last_stop_at = self.clock()
            if self.timed_velocity:
                self._check("SetVelocity(0)", self.client.SetVelocity(0.0, 0.0, 0.0, PULSE_SECONDS))
            else:
                self._check("StopMove", self.client.StopMove())
        self._moving_key = None
        summary = (f" · 이동 입력 {self._input_count}회 · 속도 RPC 수락 {self._accepted_count}회"
                   if self._input_count else "")
        self._input_count = self._accepted_count = 0
        return summary

    def _fault(self, error):
        self._pending = None
        try:
            self._stop()
        except Exception as stop_error:
            self._moving_key = None
            self._input_count = self._accepted_count = 0
            return f"RPC 오류: {error}. 속도 0 응답도 확인하지 못했습니다: {stop_error}. 조종기를 확인하세요."
        return f"RPC 오류: {error}. 직전 명령을 중단했습니다. 다음 입력에서 기체 상태를 다시 확인합니다."

    @property
    def effective_straight_speed(self):
        if self.straight_speed is not None:
            return self.straight_speed
        return min(VELOCITY["i"][0] * self.linear_scale, MAX_STRAIGHT_SPEED)

    def speed_summary(self):
        scales = f"선속도 {self.linear_scale:g}배 · 회전 {self.turn_scale:g}배"
        if self.straight_speed is not None:
            return f"{scales} · 직진·후진 고정 속도 ±{self.effective_straight_speed:.3f} m/s"
        return (f"{scales} · 직진·후진 ±{self.effective_straight_speed:.3f} m/s "
                f"(상한 {MAX_STRAIGHT_SPEED:.3f} m/s)")

    def _status(self, current):
        text = f"현재 FSM={display_fsm(current)} · {self.speed_summary()}"
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
        kind, value, label = self.modes[selected]
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

    def _move(self, key, received_at, cancel_requested):
        now = self.clock()
        if self._last_stop_at is not None and received_at < self._last_stop_at:
            return None  # A queued key from before StopMove cannot restart motion.
        deadline = min(now, received_at) + PULSE_SECONDS
        if key == self._moving_key and deadline < self._motion_deadline and now < self._motion_deadline:
            return None  # A buffered repeat cannot supersede a newer input.
        if now >= deadline:
            self._stop()
            return "이동 입력 시간이 만료되었습니다. 키를 다시 누르세요."
        if not self.timed_velocity and key == self._moving_key and deadline == self._motion_deadline:
            # Replaying the same event would start a new full SDK Move pulse.
            return None
        vx, vy, yaw = VELOCITY[key]
        velocity = (vx * self.linear_scale, vy * self.linear_scale, yaw * self.turn_scale)
        if vy == 0 and yaw == 0:
            velocity = (math.copysign(self.effective_straight_speed, vx), 0.0, 0.0)
        self._input_count += 1
        if key == self._moving_key and now - self._last_move_sent < REPEAT_INTERVAL:
            self._motion_deadline = deadline
            self._velocity = velocity
            return None
        return self._update_motion(key, deadline, velocity=velocity, cancel_requested=cancel_requested)

    def _update_motion(self, key, deadline, *, velocity=None, cancel_requested=None):
        current = self._fsm()
        walk_option = "허리 3자유도 보행(501)은 8 → Enter" if self.waist_3dof else "일반 보행(500)은 v → Enter"
        blocked = self._check_mode(current, GAIT_IDS, f"{walk_option}, Run은 메뉴의 ID를 확인하고 2 → Enter로 선택하세요.")
        if blocked:
            self._stop()
            return blocked
        if self._moving_key is not None and current != self._motion_fsm:
            self._stop()
            return f"보행 모드가 FSM {current}로 바뀌어 속도 0을 요청했습니다."
        # Check time after polling the TTY as both the poll and the FSM RPC can be delayed.
        cancelled = cancel_requested is not None and cancel_requested()
        now = self.clock()
        duration = deadline - now
        if duration <= 0:
            self._stop()
            return "상태 조회 중 이동 입력 시간이 만료되었습니다. 키를 다시 누르세요."
        if cancelled:
            return None  # The terminal will handle the queued stop or exit next.
        self._last_motion_check = now
        if velocity is None and not self.timed_velocity:
            return None  # Stock Move starts a new one-second pulse on every call.
        # The request may reach the server even if the reply is lost.
        repeated = key == self._moving_key
        self._moving_key = key
        self._motion_fsm = current
        self._motion_deadline = deadline
        self._last_move_sent = now
        if velocity is not None:
            self._velocity = velocity
        vx, vy, yaw = self._velocity
        if self.exit_requested:
            raise EndSession()
        if self.timed_velocity:
            self._check("SetVelocity(7105)", self.client.SetVelocity(vx, vy, yaw, duration))
        else:
            self._check("Move(7105)", self.client.Move(vx, vy, yaw))
        self._accepted_count += 1
        if not repeated:
            if self.timed_velocity:
                operation, timing = "SetVelocity(7105)", f"{duration:.2f}초"
            else:
                remaining = max(0.0, deadline - self.clock())
                operation, timing = "Move(7105)", f"SDK 명령 1초 · 입력 만료까지 {remaining:.2f}초"
            message = (f"{operation} 수락 · FSM={current} · "
                       f"vx={vx:.3f} vy={vy:.3f} m/s yaw={yaw:.3f} rad/s · {timing}")
            if current in RUN_IDS:
                message += f"\n{current}(Run)에서 발걸음이 없으면 k로 정지하세요. 속도 응답만으로 실제 이동을 확인할 수 없습니다."
            return message
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
        return self.speed_summary() + " · 다음 이동 입력부터 적용합니다."

    def handle(self, key, *, received_at=None, cancel_requested=None):
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
                return "속도 0 요청 수락." + self._stop(force=True)
            if key == "f":
                return self._status(self._fsm())
            if previous is not None and key not in MODES:
                return "모드 선택을 취소했습니다."
            if key in SPEED_FACTORS or key in ("+", "-", "="):
                return self._adjust_speed(key)
            if key in SPEED_LIMITS:
                current = self._fsm()
                blocked = self._check_mode(current, RUN_IDS, "달리기 속도 상한은 Run(801/802)에서 설정하세요.")
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
                return f"{self.modes[key][2]} · 4초 이내 Enter로 요청, Esc로 취소."
            return self._move(key, self.clock() if received_at is None else received_at, cancel_requested)
        except Exception as error:
            return self._fault(error)

    def tick(self, input_waiting=lambda: False):
        """Monitor the active gait; timed velocities also refresh until input expires."""
        now = self.clock()
        if self._pending is not None and now >= self._confirm_deadline:
            self._pending = None
            return "모드 선택 시간이 지났습니다."
        if self.exit_requested or not self._moving_key:
            return None
        try:
            if now >= self._motion_deadline:
                return "키 반복 입력 만료 · 속도 0 요청 수락." + self._stop()
            if now - self._last_motion_check >= REPEAT_INTERVAL and not input_waiting():
                return self._update_motion(self._moving_key, self._motion_deadline,
                                           cancel_requested=input_waiting) or ""
        except Exception as error:
            return self._fault(error)
        return None

    def close(self, *, force_stop=False):
        self._pending = self._awaiting_fsm = None
        if not (force_stop or self._moving_key):
            return "텔레옵을 종료했습니다."

        # A lost reply leaves the result uncertain. Retry only the idempotent
        # zero command, with the SDK's existing finite timeout on both attempts.
        for attempt in range(2):
            try:
                summary = self._stop(force=True)
                return "종료 정지 · 속도 0 요청 수락. 텔레옵을 종료했습니다." + summary
            except Exception as error:
                if attempt == 1:
                    raise RuntimeError(
                        f"종료 정지 미확인 · 속도 0 수락을 2회 모두 확인하지 못했습니다 ({error}). "
                        "물리 조종기로 정지를 확인하세요."
                    ) from error
