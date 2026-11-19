ARG BASE_IMAGE=g1-jsj-ubuntu:20.04
FROM ${BASE_IMAGE}

USER root
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8 BASH_ENV=/dev/null

# Start with plain ARM64 Ubuntu. The official Focal ROS repository package
# supplies its signing key and source, so Foxy does not need to be in the parent.
RUN set -eux; \
    . /etc/os-release; \
    test "$ID:$VERSION_ID:$(dpkg --print-architecture)" = ubuntu:20.04:arm64; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    curl -fL --retry 3 -o /tmp/ros2-apt-source.deb \
      https://github.com/ros-infrastructure/ros-apt-source/releases/download/1.3.0/ros2-apt-source_1.3.0.focal_all.deb; \
    echo '14c22046f6aae248a37a7bb52000ad1fae29aa1d7ae9fb7aead90bb01ad99355  /tmp/ros2-apt-source.deb' | sha256sum -c -; \
    apt-get install -y --no-install-recommends /tmp/ros2-apt-source.deb; \
    rm /tmp/ros2-apt-source.deb; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      ros-foxy-ros-base ros-foxy-sensor-msgs ros-foxy-geometry-msgs \
      ros-foxy-rmw-cyclonedds-cpp ros-foxy-rosidl-generator-dds-idl \
      ros-foxy-rosidl-default-generators python3-colcon-common-extensions \
      git build-essential gcc-9 g++-9 cmake pkg-config libssl-dev \
      libyaml-cpp-dev libeigen3-dev libboost-all-dev libfmt-dev \
      python3-dev python3-pip python3-numpy python3-opencv; \
    rm -rf /var/lib/apt/lists/*; \
    test -f /opt/ros/foxy/setup.bash; \
    python3 -c 'import sys; assert sys.version_info[:2] == (3, 8)'

ENV CC=/usr/bin/gcc-9 CXX=/usr/bin/g++-9
WORKDIR /opt/unitree_ros2
RUN git clone --depth 1 https://github.com/unitreerobotics/unitree_ros2.git .

# Build Cyclone DDS before sourcing Foxy, then build the RMW and message
# packages against this copy. Limit compiler parallelism on the Orin.
WORKDIR /opt/unitree_ros2/cyclonedds_ws
RUN set -ex; \
    git clone --depth 1 --branch foxy https://github.com/ros2/rmw_cyclonedds.git src/rmw_cyclonedds; \
    git clone --depth 1 --branch 0.10.2 https://github.com/eclipse-cyclonedds/cyclonedds.git src/cyclonedds; \
    export MAKEFLAGS=-j2 CMAKE_BUILD_PARALLEL_LEVEL=2; \
    colcon build --merge-install --executor sequential --packages-select cyclonedds \
      --cmake-args -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_LIBDIR=lib -DBUILD_TESTING=OFF; \
    source /opt/ros/foxy/setup.bash; \
    source install/local_setup.bash; \
    colcon build --merge-install --executor sequential \
      --packages-select rmw_cyclonedds_cpp unitree_go unitree_hg unitree_api \
      --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
      -DCycloneDDS_DIR=/opt/unitree_ros2/cyclonedds_ws/install/lib/cmake/CycloneDDS; \
    rm -rf build log

RUN set -eux; \
    git clone --depth 1 https://github.com/unitreerobotics/unitree_sdk2.git /opt/unitree_sdk2; \
    cmake -S /opt/unitree_sdk2 -B /opt/unitree_sdk2/build \
      -DCMAKE_BUILD_TYPE=Release -DBUILD_EXAMPLES=OFF -DCMAKE_INSTALL_PREFIX=/opt/unitree_robotics; \
    cmake --build /opt/unitree_sdk2/build --parallel 2; \
    cmake --install /opt/unitree_sdk2/build; \
    rm -rf /opt/unitree_sdk2/build

ENV CYCLONEDDS_HOME=/opt/unitree_ros2/cyclonedds_ws/install
RUN set -eux; \
    python3 -m pip install --upgrade --no-cache-dir 'pip==25.0.1'; \
    python3 -m pip install --no-cache-dir --no-binary=cyclonedds 'cyclonedds==0.10.2'; \
    git clone --depth 1 https://github.com/unitreerobotics/unitree_sdk2_python.git /opt/unitree_sdk2_python; \
    python3 -m pip install --no-cache-dir --no-deps /opt/unitree_sdk2_python

# Direct docker exec commands (including python3) inherit the same overlay
# as a Bash shell. Set the live DDS domain and NIC when starting the camera.
ENV ROS_DISTRO=foxy ROS_VERSION=2 ROS_PYTHON_VERSION=3 ROS_DOMAIN_ID=0 \
    RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    AMENT_PREFIX_PATH=/opt/unitree_ros2/cyclonedds_ws/install:/opt/ros/foxy \
    CMAKE_PREFIX_PATH=/opt/unitree_ros2/cyclonedds_ws/install:/opt/ros/foxy:/opt/unitree_robotics \
    LD_LIBRARY_PATH=/opt/unitree_ros2/cyclonedds_ws/install/lib:/opt/ros/foxy/lib:/opt/ros/foxy/lib/aarch64-linux-gnu \
    PYTHONPATH=/opt/unitree_ros2/cyclonedds_ws/install/lib/python3.8/site-packages:/opt/ros/foxy/lib/python3.8/site-packages \
    PATH=/opt/unitree_ros2/cyclonedds_ws/install/bin:/opt/ros/foxy/bin:${PATH}

RUN set -ex; \
    mkdir -p /opt/g1 /workspace; \
    printf '%s\n' \
      'source /opt/ros/foxy/setup.bash' \
      'source /opt/unitree_ros2/cyclonedds_ws/install/local_setup.bash' \
      > /opt/g1/ros_env.sh; \
    printf '\nsource /opt/g1/ros_env.sh\n' >> /root/.bashrc; \
    python3 -c 'from importlib.metadata import version; import cv2, numpy, rclpy; from unitree_sdk2py.core.channel import ChannelSubscriber; from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_; assert version("cyclonedds") == "0.10.2"; assert rclpy.get_rmw_implementation_identifier() == "rmw_cyclonedds_cpp"'; \
    ros2 interface show sensor_msgs/msg/Image >/dev/null; \
    ros2 pkg prefix unitree_hg

ENV BASH_ENV=/opt/g1/ros_env.sh
WORKDIR /workspace
CMD ["/bin/bash"]
