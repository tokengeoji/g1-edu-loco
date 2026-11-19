# Author: Codex (IIC)
"""Read one G1 state snapshot for an otherwise simulated keyboard session."""

import math
import time

from g1stairs.monitoring.telemetry import JOINT_NAMES, TOPIC, Receiver, serialize, subscribe


SNAPSHOT_TIMEOUT_NS = 3_000_000_000


def read_robot_snapshot(interface, domain, service, discover):
    """Return the service name, observed FSM and a summary of motor feedback."""
    receiver = Receiver(capacity=1)
    started_ns = time.monotonic_ns()
    deadline_ns = started_ns + SNAPSHOT_TIMEOUT_NS
    with subscribe(interface, domain, receiver):
        client, service_name, fsm = discover(service)
        del client  # The simulated controller receives only the observed FSM.
        sample, _ = receiver.snapshot()
        if sample is None:
            remaining = max(0, deadline_ns - time.monotonic_ns()) / 1e9
            first = receiver.wait(remaining)
            if first is None:
                raise RuntimeError(
                    f"{TOPIC} 3초 이내 수신 없음. NIC={interface}, DDS domain={domain}, 기체 전원을 확인하세요."
                )
            latest, _ = receiver.snapshot()
            sample = latest if latest is not None else first

    try:
        received_ns, message = sample
        joints = serialize(message, received_ns)["joints"]
        if len(joints) != len(JOINT_NAMES):
            raise ValueError(f"모터 피드백 슬롯 {len(joints)}개 (필요 {len(JOINT_NAMES)}개)")
        for joint in joints:
            for field in ("q_rad", "dq_rad_s"):
                value = joint[field]
                if value is None or isinstance(value, bool) or not math.isfinite(value):
                    raise ValueError(f"{joint['name']}의 {field} 값이 유효하지 않습니다")
        if type(received_ns) is not int:
            raise ValueError("수신 시각을 확인할 수 없습니다")
    except (AttributeError, IndexError, KeyError, OverflowError, TypeError, ValueError) as error:
        raise RuntimeError(f"{TOPIC} 모터 피드백을 확인하세요: {error}") from error

    age_ns = time.monotonic_ns() - received_ns
    if received_ns < started_ns or not 0 <= age_ns <= SNAPSHOT_TIMEOUT_NS:
        raise RuntimeError(f"{TOPIC} 수신 시각이 유효 범위(최근 3초)를 벗어났습니다. 모니터에서 수신을 확인하세요.")

    knee = joints[JOINT_NAMES.index("left_knee")]
    summary = (f"{TOPIC} · q/dq 수신 {len(joints)}/{len(JOINT_NAMES)} 슬롯 · 왼쪽 무릎(left_knee) "
               f"q={knee['q_rad']:.3f} rad, dq={knee['dq_rad_s']:.3f} rad/s · 수신 {age_ns / 1e6:.0f} ms 전")
    return service_name, fsm, summary
