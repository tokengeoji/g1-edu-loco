# Author: Codex (IIC)
"""Use Unitree's subscriber with the sender's actual discovered video type."""
import os
import signal
import subprocess
import time
from pathlib import Path

from cyclonedds.builtin import BuiltinDataReader, BuiltinTopicDcpsPublication
from cyclonedds.domain import DomainParticipant
from cyclonedds.dynamic import get_types_for_typeid
from cyclonedds.util import duration
from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber

ROOT = Path(__file__).resolve().parent
TOPIC = "rt/frontvideostream"
TYPENAME = "unitree_go::msg::dds_::Go2FrontVideoData_"
RUNNING = True

def stop(_signal, _frame):
    global RUNNING
    RUNNING = False

def discover_type(participant):
    reader = BuiltinDataReader(participant, BuiltinTopicDcpsPublication)
    deadline = time.monotonic() + 8
    while RUNNING and time.monotonic() < deadline:
        for ep in reader.take(256):
            if not ep.sample_info.valid_data or (ep.topic_name, ep.type_name) != (TOPIC, TYPENAME):
                continue
            if ep.type_id is None:
                raise RuntimeError("Writer did not advertise a type identifier")
            msg_type, _ = get_types_for_typeid(participant, ep.type_id, duration(seconds=3))
            if msg_type.__idl__.get_type_id() != ep.type_id:
                raise RuntimeError("Discovered video type differs from the writer identifier")
            if not {"resolution", "data"}.issubset(msg_type.__annotations__):
                raise RuntimeError("Writer type does not advertise the observed resolution and data fields")
            print("Verified the front video writer's advertised type", ep.type_id, flush=True)
            return msg_type
        time.sleep(0.05)
    raise RuntimeError("Front video writer unavailable")

def main():
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)
    ChannelFactoryInitialize(0, "eth0")
    discovery = DomainParticipant(0)
    msg_type = discover_type(discovery)
    sub = ChannelSubscriber(TOPIC, msg_type)
    sub.Init()
    worker = None
    try:
        worker = subprocess.Popen([str(ROOT / "build" / "front_color_bridge")],
                                  stdin=subprocess.PIPE, bufsize=0)
        print("Unitree ChannelSubscriber active; ROS image decoder PID", worker.pid, flush=True)
        waiting_for_headers = True
        while RUNNING and worker.poll() is None:
            sample = sub.Read(1)
            if sample is None or sample.resolution != 360 or not sample.data:
                continue
            packet = bytes(sample.data)
            if waiting_for_headers:
                if b"\x00\x00\x01\x67" not in packet:
                    continue
                waiting_for_headers = False
            remaining = memoryview(packet)
            while remaining:
                written = worker.stdin.write(remaining)
                if not written:
                    raise RuntimeError("Decoder pipe closed")
                remaining = remaining[written:]
        if RUNNING:
            raise RuntimeError("ROS image decoder stopped")
    finally:
        sub.Close()
        if worker:
            worker.stdin.close()
            try:
                worker.wait(timeout=3)
            except subprocess.TimeoutExpired:
                worker.terminate()
                worker.wait(timeout=3)

if __name__ == "__main__":
    main()
