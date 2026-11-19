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
PROFILE_EXCLUSIONS = {
    "g1-29": (),
    "g1-29-waist-locked": (13, 14),
    "g1-23": (13, 14, 20, 21, 27, 28),
}


def number(value):
    """Preserve missing and non-finite SDK values as JSON null."""
    return None if value is None or not math.isfinite(value) else value


def active_indices(profile):
    return [i for i in range(len(JOINT_NAMES)) if i not in PROFILE_EXCLUSIONS[profile]]


def joint_name(index, mode_pr):
    if mode_pr == 1:
        return PARALLEL_JOINT_NAMES.get(index, JOINT_NAMES[index])
    if mode_pr != 0 and index in PARALLEL_JOINT_NAMES:
        return "motor_{}".format(index)
    return JOINT_NAMES[index]


def serialize(message, received_ns, profile):
    mode_pr = message.mode_pr
    imu = message.imu_state
    indices = active_indices(profile)
    if len(message.motor_state) <= indices[-1]:
        raise ValueError("LowState motor_state is too short for {}".format(profile))
    joints = []
    for index in indices:
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
    except ImportError as exc:
        raise RuntimeError(
            "Unitree SDK2 Python or its CycloneDDS binding is unavailable. "
            "See monitoring/README.md and use fixture for offline checks."
        ) from exc

    try:
        ChannelFactoryInitialize(domain, nic)
        subscriber = ChannelSubscriber(TOPIC, LowState_)
        subscriber.Init(receiver.on_sample, 0)
    except Exception as exc:
        raise RuntimeError("Cannot initialize read-only DDS on {} domain {}: {}".format(
            nic, domain, exc
        )) from exc

    try:
        yield
    finally:
        subscriber.Close()


def synthetic_sample(index, profile):
    phase = index / 10.0
    return {
        "host_rx_monotonic_ns": index * 100_000_000,
        "tick": None,
        "mode_machine": None,
        "mode_pr": 0,
        "imu": {
            "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            "gyroscope": [0.0, 0.0, 0.0],
            "accelerometer": [0.0, 0.0, 9.81],
            "rpy": [0.0, 0.0, 0.0],
            "temperature_c": 30,
        },
        "joints": [
            {
                "index": joint,
                "name": JOINT_NAMES[joint],
                "q_rad": round(0.1 * math.sin(phase + joint), 6),
                "dq_rad_s": round(0.1 * math.cos(phase + joint), 6),
                "tau_est_nm": 0.0,
                "temperature_casing_c": 31 + joint % 4,
                "temperature_winding_c": 38 + joint % 6,
                "motorstate": None,
            }
            for joint in active_indices(profile)
        ],
    }
