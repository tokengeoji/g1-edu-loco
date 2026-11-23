# Author: Codex (IIC)
"""Read the G1 state estimator independently of keyboard and locomotion RPCs."""

import math
import time

from g1stairs.monitoring.telemetry import Receiver


TOPIC = "rt/odommodestate"


def format_odometry(sample, origin):
    x, y = sample.position[:2]
    vx, vy = sample.velocity[:2]
    yaw_rate = sample.yaw_speed
    if not all(math.isfinite(value) for value in (x, y, vx, vy, yaw_rate)):
        raise ValueError("유한하지 않은 오도메트리 값")
    try:
        yaw = sample.imu_state.rpy[2]
        if not math.isfinite(yaw):
            yaw = None
    except (AttributeError, IndexError, TypeError):
        yaw = None
    if origin is None:
        origin = (x, y, yaw)
    dx, dy = x - origin[0], y - origin[1]
    start_yaw = origin[2]
    if start_yaw is None:
        axes = "시작 방위 없음 · 전후/좌우 변위 미확인"
    else:
        # Position is in world coordinates. Keep the first heading fixed so a
        # turn in place cannot change the forward or lateral displacement.
        c, s = math.cos(start_yaw), math.sin(start_yaw)
        forward, left = c * dx + s * dy, -s * dx + c * dy
        axes = f"시작 전방 Δ={forward:+.3f} m · 좌측 Δ={left:+.3f} m"
        if yaw is not None:
            change = math.remainder(yaw - start_yaw, 2 * math.pi)
            axes += f" · 방위 변화={math.degrees(change):+.1f}°"
    displacement = math.hypot(dx, dy)
    return (f"월드 x={x:.3f} y={y:.3f} m · 시작점과 수평거리={displacement:.3f} m · "
            f"{axes} · 수평 속력={math.hypot(vx, vy):.3f} m/s · 회전속도={yaw_rate:.3f} rad/s"), origin


def watch_odometry(interface, domain):
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_

    receiver = Receiver(capacity=0)
    try:
        ChannelFactoryInitialize(domain, interface)
        reader = ChannelSubscriber(TOPIC, SportModeState_)
        reader.Init(receiver.on_sample, 0)
    except Exception as error:
        raise RuntimeError(f"{TOPIC} 구독 실패 · NIC={interface} · domain={domain} · {error}") from error
    try:
        print(f"[읽기 전용] {TOPIC} · NIC={interface} · domain={domain} · Ctrl+C 종료", flush=True)
        print("첫 샘플의 위치·방위가 기준입니다. 전방 Δ의 +는 전진, −는 후진입니다. "
              "각 시험을 새로 측정하려면 정지 상태에서 다시 실행하세요.", flush=True)
        origin = None
        last = None
        last_warning = -math.inf
        started = time.monotonic()
        while True:
            time.sleep(0.25)
            now = time.monotonic()
            item, _ = receiver.snapshot()
            if item is None or now - item[0] / 1e9 > 1:
                if now - started >= 1 and now - last_warning >= 2:
                    print("새 오도메트리 샘플 대기 중 · 이동 여부 미확인", flush=True)
                    last_warning = now
                continue
            if item[0] == last:
                continue
            last, sample = item
            try:
                line, origin = format_odometry(sample, origin)
            except (AttributeError, IndexError, ValueError, TypeError) as error:
                line = f"오도메트리 값 확인 불가 · {error}"
            print(f"[{now-started:.2f} s] {line}", flush=True)
    finally:
        reader.Close()
