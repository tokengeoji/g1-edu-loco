"""Translate the official Unitree HG LowState DDS message into session samples."""

import math
import queue
import threading
import time
from contextlib import contextmanager

TOPIC = "rt/lowstate"
JOINT_NAMES = (
    "left_hip_pitch", "left_hip_roll", "left_hip_yaw", "left_knee",
    "left_ankle_pitch", "left_ankle_roll",
    "right_hip_pitch", "right_hip_roll", "right_hip_yaw", "right_knee",
    "right_ankle_pitch", "right_ankle_roll",
    "waist_yaw", "waist_roll", "waist_pitch",
    "left_shoulder_pitch", "left_shoulder_roll", "left_shoulder_yaw",
    "left_elbow", "left_wrist_roll", "left_wrist_pitch", "left_wrist_yaw",
    "right_shoulder_pitch", "right_shoulder_roll", "right_shoulder_yaw",
    "right_elbow", "right_wrist_roll", "right_wrist_pitch", "right_wrist_yaw",
)
PARALLEL_JOINT_NAMES = {
    4: "left_ankle_b", 5: "left_ankle_a",
    10: "right_ankle_b", 11: "right_ankle_a",
    13: "waist_a", 14: "waist_b",
}


def number(value):
    """Preserve missing and non-finite SDK values as JSON null."""
    return None if value is None or not math.isfinite(value) else value


def joint_name(index, mode_pr):
    if mode_pr == 1:
        return PARALLEL_JOINT_NAMES.get(index, JOINT_NAMES[index])
    if mode_pr != 0 and index in PARALLEL_JOINT_NAMES:
        return "motor_{}".format(index)
    return JOINT_NAMES[index]


def serialize(message, received_ns):
    mode_pr = message.mode_pr
    imu = message.imu_state
    if len(message.motor_state) < len(JOINT_NAMES):
        raise ValueError("G1 EDU monitoring requires all 29 body motor slots in LowState")
    joints = []
    for index in range(len(JOINT_NAMES)):
        motor = message.motor_state[index]
        temperatures = list(motor.temperature)
        joints.append({
            "index": index,
            "name": joint_name(index, mode_pr),
            "q_rad": number(motor.q),
            "dq_rad_s": number(motor.dq),
            "tau_est_nm": number(motor.tau_est),
            "temperature_casing_c": number(temperatures[0]) if temperatures else None,
            "temperature_winding_c": number(temperatures[1]) if len(temperatures) > 1 else None,
            "motorstate": getattr(motor, "motorstate", None),
        })
    return {
        "host_rx_monotonic_ns": received_ns,
        "tick": message.tick,
        "mode_machine": message.mode_machine,
        "mode_pr": mode_pr,
        "imu": {
            "quaternion_wxyz": [number(v) for v in imu.quaternion],
            "gyroscope": [number(v) for v in imu.gyroscope],
            "accelerometer": [number(v) for v in imu.accelerometer],
            "rpy": [number(v) for v in imu.rpy],
            "temperature_c": number(imu.temperature),
        },
        "joints": joints,
    }


class Receiver:
    """Bound SDK callbacks to an enqueue and keep disk writes out of the callback."""

    def __init__(self, capacity=1024):
        self.samples = queue.Queue(maxsize=capacity) if capacity else None
        self.lock = threading.Lock()
        self.latest = None
        self.dropped = 0

    def on_sample(self, message):
        item = (time.monotonic_ns(), message)
        with self.lock:
            self.latest = item
            if self.samples is not None:
                try:
                    self.samples.put_nowait(item)
                except queue.Full:
                    self.dropped += 1

    def snapshot(self):
        with self.lock:
            return self.latest, self.dropped

    def wait(self, timeout):
        try:
            return self.samples.get(timeout=timeout)
        except queue.Empty:
            return None


@contextmanager
def subscribe(nic, domain, receiver):
    try:
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "Cannot load Unitree SDK2 Python and CycloneDDS inside this container: {}".format(exc)
        ) from exc

    try:
        ChannelFactoryInitialize(domain, nic)
        subscriber = ChannelSubscriber(TOPIC, LowState_)
        subscriber.Init(receiver.on_sample, 0)
    except Exception as exc:
        raise RuntimeError("Cannot initialize read-only DDS on {} in domain {}: {}".format(
            nic or "the SDK default interface", domain, exc
        )) from exc

    try:
        yield
    finally:
        subscriber.Close()
