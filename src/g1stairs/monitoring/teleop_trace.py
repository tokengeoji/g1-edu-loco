# Author: Codex (IIC)
"""Passively correlate locomotion requests and HG gait state with LowState."""

import json
import math
import queue
import threading
import time
from contextlib import ExitStack, contextmanager
from functools import partial

from g1stairs.session import dump_line


REQUEST_TOPICS = ("rt/api/sport/request", "rt/api/loco/request")
FSM_TOPIC = "rt/sportmodestate"
VELOCITY_API = 7105


def hg_sport_state_type():
    # The pinned Python SDK omits the HG type. These fields and their order
    # are from unitree_sdk2/include/unitree/idl/hg/SportModeState_.hpp.
    from dataclasses import dataclass
    from cyclonedds.idl import IdlStruct
    from cyclonedds.idl.annotations import autoid, final
    from cyclonedds.idl.types import float32, uint32

    @dataclass
    @final
    @autoid("sequential")
    class SportModeState_(IdlStruct, typename="unitree_hg.msg.dds_.SportModeState_"):
        fsm_id: uint32
        fsm_mode: uint32
        task_id: uint32
        task_time: float32

    return SportModeState_


class TeleopTrace:
    def __init__(self, stream, capacity=1024):
        self.stream = stream
        self.queue = queue.Queue(maxsize=capacity)
        self.lock = threading.Lock()
        self.last_fsm = None
        self.closed = False
        self.ready_ns = None
        self.stats = {
            topic: {"received": 0, "written": 0, "dropped": 0, "invalid": 0,
                    "max_internal_gap_ns": 0,
                    "first_host_rx_monotonic_ns": None, "last_host_rx_monotonic_ns": None}
            for topic in (*REQUEST_TOPICS, FSM_TOPIC)
        }

    def receive(self, topic, message):
        if topic == FSM_TOPIC:
            data = (message.fsm_id, message.fsm_mode)
        else:
            identity = message.header.identity
            if identity.api_id != VELOCITY_API:
                return
            data = (identity.id, message.parameter)
        with self.lock:
            if self.closed:
                return
            received_ns = time.monotonic_ns()
            stats = self.stats[topic]
            stats["received"] += 1
            if stats["first_host_rx_monotonic_ns"] is None:
                stats["first_host_rx_monotonic_ns"] = received_ns
            else:
                gap = received_ns - stats["last_host_rx_monotonic_ns"]
                stats["max_internal_gap_ns"] = max(stats["max_internal_gap_ns"], gap)
            stats["last_host_rx_monotonic_ns"] = received_ns
            if topic == FSM_TOPIC and data == self.last_fsm:
                return
            try:
                self.queue.put_nowait((received_ns, topic, data))
            except queue.Full:
                stats["dropped"] += 1
                return
            if topic == FSM_TOPIC:
                self.last_fsm = data

    def drain(self):
        for _ in range(self.queue.qsize()):
            received_ns, topic, data = self.queue.get_nowait()
            event = {"host_rx_monotonic_ns": received_ns, "topic": topic}
            if topic == FSM_TOPIC:
                event.update(fsm_id=data[0], fsm_mode=data[1])
            else:
                try:
                    parameter = json.loads(data[1])
                    velocity, duration = parameter["velocity"], parameter["duration"]
                    if (not isinstance(velocity, list) or len(velocity) != 3
                            or not all(type(v) in (float, int) and math.isfinite(v)
                                       for v in (*velocity, duration))):
                        raise ValueError("invalid velocity or duration")
                except (KeyError, TypeError, ValueError, OverflowError):
                    self.stats[topic]["invalid"] += 1
                    continue
                event.update(api_id=VELOCITY_API, request_id=data[0], velocity=velocity, duration=duration)
            dump_line(self.stream, event)
            self.stats[topic]["written"] += 1

    def finish(self):
        with self.lock:
            self.closed = True
        self.drain()
        self.stream.flush()


@contextmanager
def record_teleop(path, metadata):
    """Use the SDK participant already initialized by the LowState subscriber."""
    from unitree_sdk2py.core.channel import ChannelSubscriber
    from unitree_sdk2py.idl.unitree_api.msg.dds_ import Request_

    with (path / "teleop.jsonl").open("w", encoding="utf-8") as stream:
        trace = TeleopTrace(stream)
        with ExitStack() as readers:
            for topic in (*REQUEST_TOPICS, FSM_TOPIC):
                message_type = hg_sport_state_type() if topic == FSM_TOPIC else Request_
                try:
                    subscriber = ChannelSubscriber(topic, message_type)
                    readers.callback(subscriber.Close)
                    subscriber.Init(partial(trace.receive, topic), 0)
                except Exception as exc:
                    raise RuntimeError(f"Cannot subscribe to {topic}: {exc}") from exc
            trace.ready_ns = time.monotonic_ns()
            try:
                yield trace
            finally:
                trace.finish()
                metadata["teleop_trace"] = {
                    "file": "teleop.jsonl", "subscriptions_ready_host_monotonic_ns": trace.ready_ns,
                    "capture_end_host_monotonic_ns": time.monotonic_ns(), "topics": trace.stats,
                    "topics_without_samples": [t for t, stats in trace.stats.items() if not stats["received"]],
                }
