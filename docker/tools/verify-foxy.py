# Author: Codex (IIC)
"""Check the ROS 2 middleware and message types in both operator images."""
from pathlib import Path

import rclpy
from rclpy.serialization import deserialize_message, serialize_message
from sensor_msgs.msg import CameraInfo, Image
from unitree_hg.msg import LowState


def main():
    if rclpy.get_rmw_implementation_identifier() != "rmw_cyclonedds_cpp":
        raise RuntimeError("Expected the ROS 2 Cyclone DDS middleware")
    for message_type in (Image, CameraInfo, LowState):
        message = message_type()
        if message_type is Image:
            message.width, message.height, message.step = 3, 1, 3
            message.encoding = "mono8"
            message.data = [1, 2, 3]
        received = deserialize_message(serialize_message(message), message_type)
        if received != message:
            raise RuntimeError(f"ROS serialization mismatch for {message_type.__name__}")
    maps = Path("/proc/self/maps").read_text().splitlines()
    loaded = {line.split()[-1] for line in maps}
    expected = (
        Path("/opt/ros/foxy/lib/librmw_cyclonedds_cpp.so"),
        Path("/opt/unitree_ros2/cyclonedds_ws/install/lib/libddsc.so.0.10.2"),
    )
    for library in expected:
        if str(library.resolve()) not in loaded:
            raise RuntimeError(f"Expected the process to load {library}")
        print(library.resolve())


if __name__ == "__main__":
    main()
