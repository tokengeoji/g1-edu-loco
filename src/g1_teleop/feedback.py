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
    if origin is None:
        origin = (x, y)
    displacement = math.hypot(x - origin[0], y - origin[1])
    return (f"월드 x={x:.3f} y={y:.3f} m · 시작점과 수평거리={displacement:.3f} m · "
            f"수평 속력={math.hypot(vx, vy):.3f} m/s · 회전속도={yaw_rate:.3f} rad/s"), origin


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
