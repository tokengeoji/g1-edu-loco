# Author: Codex (IIC)
FROM scratch AS unpacker
# The pinned Docker Official Images submodule supplies the ARM64 tar utility.
# Classic Docker expands a local tarball but leaves a remote ADD compressed.
ADD docker/base/ubuntu-bootstrap/latest-1/musl/arm64v8/rootfs.tar.gz /
ADD https://partner-images.canonical.com/oci/focal/20250530.1/ubuntu-focal-oci-arm64-root.tar.gz /ubuntu-rootfs.tar.gz
ENV PATH=/bin
RUN set -eu; \
    echo 'fcd7f696f7a5f98e60b4e5a71869525ce185c8b3766d77be3388603e3e5083c7  /ubuntu-rootfs.tar.gz' | sha256sum -c -; \
    mkdir /ubuntu; \
    tar --numeric-owner -xzpf /ubuntu-rootfs.tar.gz -C /ubuntu

FROM scratch
COPY --from=unpacker /ubuntu/ /
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

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
      git iproute2 build-essential gcc-9 g++-9 cmake pkg-config libssl-dev \
      libyaml-cpp-dev libeigen3-dev libboost-all-dev libfmt-dev \
      python3-dev python3-pip python3-numpy python3-opencv; \
    rm -rf /var/lib/apt/lists/*; \
    test -f /opt/ros/foxy/setup.bash; \
    python3 -c 'import sys; assert sys.version_info[:2] == (3, 8)'

ENV CC=/usr/bin/gcc-9 CXX=/usr/bin/g++-9
WORKDIR /opt/unitree_ros2
ARG UNITREE_ROS2_REF=668d1ec5a05d1c38d3306bdca7d59f2ba3581a88
RUN git init -q . && \
    git fetch --depth 1 https://github.com/unitreerobotics/unitree_ros2.git "$UNITREE_ROS2_REF" && \
    git checkout -q --detach FETCH_HEAD

# Build Cyclone DDS before sourcing Foxy, then build the RMW and message
# packages against this copy. Limit compiler parallelism on the Orin.
WORKDIR /opt/unitree_ros2/cyclonedds_ws
ARG RMW_CYCLONEDDS_FOXY_REF=c12abc56983204f1d91f2d839d394528c7b29b42
RUN set -ex; \
    git init -q src/rmw_cyclonedds; \
    git -C src/rmw_cyclonedds fetch --depth 1 https://github.com/ros2/rmw_cyclonedds.git "$RMW_CYCLONEDDS_FOXY_REF"; \
    git -C src/rmw_cyclonedds checkout -q --detach FETCH_HEAD; \
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

# Use the same C++ SDK revision as the lab's working g1_health_monitor.
ARG UNITREE_SDK2_REF=aaf69cb56c9d5ed63d8b284008ec3a8ab999bec1
RUN set -eux; \
    git init -q /opt/unitree_sdk2; \
    git -C /opt/unitree_sdk2 fetch --depth 1 https://github.com/unitreerobotics/unitree_sdk2.git "$UNITREE_SDK2_REF"; \
    git -C /opt/unitree_sdk2 checkout -q --detach FETCH_HEAD; \
    cmake -S /opt/unitree_sdk2 -B /opt/unitree_sdk2/build \
      -DCMAKE_BUILD_TYPE=Release -DBUILD_EXAMPLES=OFF -DCMAKE_INSTALL_PREFIX=/opt/unitree_robotics; \
    cmake --build /opt/unitree_sdk2/build --parallel 2; \
    cmake --install /opt/unitree_sdk2/build; \
    rm -rf /opt/unitree_sdk2/build

ENV CYCLONEDDS_HOME=/opt/unitree_ros2/cyclonedds_ws/install
ARG UNITREE_SDK2_PYTHON_REF=814556d15970dd2ecf1c9984e845ca02ab07e206
RUN set -eux; \
    python3 -m pip install --upgrade --no-cache-dir 'pip==25.0.1'; \
    python3 -m pip install --no-cache-dir --no-binary=cyclonedds 'cyclonedds==0.10.2'; \
    git init -q /opt/unitree_sdk2_python; \
    git -C /opt/unitree_sdk2_python fetch --depth 1 https://github.com/unitreerobotics/unitree_sdk2_python.git "$UNITREE_SDK2_PYTHON_REF"; \
    git -C /opt/unitree_sdk2_python checkout -q --detach FETCH_HEAD; \
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

LABEL org.iic.g1.role="operator-tools"
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-foxy-rviz2 ros-foxy-rviz-default-plugins ros-foxy-sensor-msgs \
      ros-foxy-image-transport ros-foxy-compressed-image-transport \
      ros-foxy-compressed-depth-image-transport \
      libgl1-mesa-dri libglx-mesa0 libusb-1.0-0 libudev1 iproute2 \
      xvfb xauth x11-utils x11vnc novnc websockify curl \
    && rm -rf /var/lib/apt/lists/*

# Official librealsense wheel for CPython 3.8 on aarch64.
RUN printf '%s\n' 'pyrealsense2==2.54.1.5217 --hash=sha256:933b6948bb995d8b98b063bd7d555b3b9c043d8f041352c035b0fdb0902e13e7' \
      | python3 -m pip install --no-cache-dir --no-deps --only-binary=:all: --require-hashes -r /dev/stdin

WORKDIR /opt/g1-tools
COPY src/g1_health_monitor/ ./g1_health_monitor/
# Build the unchanged monitor against the same Unitree C++ SDK it uses at run time.
RUN cmake -S g1_health_monitor -B /tmp/g1-health-build \
        -Dunitree_sdk2_DIR=/opt/unitree_robotics/lib/cmake/unitree_sdk2 && \
    cmake --build /tmp/g1-health-build --parallel 2 && \
    install -D -m 0755 /tmp/g1-health-build/g1_health_monitor /opt/g1-tools/bin/g1_health_monitor && \
    rm -rf /tmp/g1-health-build
COPY docker/tools/health-monitor.sh /usr/local/bin/g1_health_monitor
RUN chmod 0755 /usr/local/bin/g1_health_monitor && \
    LD_LIBRARY_PATH=/opt/unitree_robotics/lib ldd /opt/g1-tools/bin/g1_health_monitor > /tmp/health-libs && \
    ! grep -q 'not found' /tmp/health-libs

COPY src/g1_teleop/ ./g1_teleop/
COPY src/g1stairs/ ./g1stairs/
COPY config/ ./config/
COPY docker/tools/g1 /usr/local/bin/g1
COPY docker/tools/pc2.sh /usr/local/bin/g1-pc2-create-command

ENV LIBGL_ALWAYS_SOFTWARE=1 QT_X11_NO_MITSHM=1 \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/g1-tools:${PYTHONPATH}
RUN set -e; chmod 0755 /usr/local/bin/g1 /usr/local/bin/g1-pc2-create-command; mkdir -p /run/g1-tools /workspace/runs; \
    bash -n /usr/local/bin/g1; bash -n /usr/local/bin/g1-pc2-create-command; bash -n g1stairs/camera/resources/rviz-web.sh; \
    test -s g1stairs/camera/resources/image.rviz; test -s /usr/share/novnc/vnc.html; \
    for tool in rviz2 Xvfb xvfb-run xauth xwininfo x11vnc websockify; do command -v "$tool" >/dev/null; done; \
    python3 -c 'from importlib.metadata import version; from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient; assert version("pyrealsense2") == "2.54.1.5217"'; \
    g1 monitor --help >/dev/null; g1 teleop --help >/dev/null; \
    g1 camera --help >/dev/null; g1 stairs --help >/dev/null

# Exercise the real input-to-command logic with local test doubles during the build.
RUN python3 -m unittest -q g1_teleop.test_control g1_teleop.test_preview g1_teleop.test_status

# Mark G1 operator shells so interactive commands are entered in the right place.
RUN printf '%s\n' 'PS1="[jsj-g1-tools] \w\\$ "' >> /root/.bashrc

WORKDIR /workspace
CMD ["sleep", "infinity"]
