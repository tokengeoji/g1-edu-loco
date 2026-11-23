# Author: Codex (IIC)
FROM scratch AS unpacker
# Executable and Focal rootfs come directly from their publishers.
ADD --chmod=0755 --checksum=sha256:6e123e7f3202a8c1e9b1f94d8941580a25135382b99e8d3e34fb858bba311348 https://busybox.net/downloads/binaries/1.35.0-x86_64-linux-musl/busybox /bin/busybox
ADD --checksum=sha256:c6ec2e65a2a30147a452986b0835bf36e8108bb8bf80e9989482023f1ece715c https://partner-images.canonical.com/oci/focal/20250530.1/ubuntu-focal-oci-amd64-root.tar.gz /ubuntu.tar.gz
RUN ["/bin/busybox", "mkdir", "/ubuntu"]
RUN ["/bin/busybox", "tar", "--numeric-owner", "-xzpf", "/ubuntu.tar.gz", "-C", "/ubuntu"]

FROM scratch
COPY --from=unpacker /ubuntu/ /
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG DEBIAN_FRONTEND=noninteractive
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8
LABEL org.iic.g1.role="development-viewer"

RUN set -eu; \
    . /etc/os-release; test "$ID:$VERSION_ID:$(dpkg --print-architecture)" = ubuntu:20.04:amd64; \
    apt-get update; apt-get install -y --no-install-recommends ca-certificates curl; \
    curl -fL --retry 3 -o /tmp/ros.deb https://github.com/ros-infrastructure/ros-apt-source/releases/download/1.3.0/ros2-apt-source_1.3.0.focal_all.deb; \
    echo '14c22046f6aae248a37a7bb52000ad1fae29aa1d7ae9fb7aead90bb01ad99355  /tmp/ros.deb' | sha256sum -c -; \
    apt-get install -y /tmp/ros.deb; rm /tmp/ros.deb; apt-get update; \
    apt-get install -y --no-install-recommends \
      git iproute2 openssh-client build-essential cmake pkg-config libssl-dev libyaml-cpp-dev \
      python3-colcon-common-extensions python3-numpy ros-foxy-ros-base ros-foxy-sensor-msgs ros-foxy-geometry-msgs \
      ros-foxy-rmw-cyclonedds-cpp ros-foxy-rosidl-generator-dds-idl ros-foxy-rosidl-default-generators \
      ros-foxy-rviz2 ros-foxy-rviz-default-plugins ros-foxy-image-transport \
      libgl1-mesa-dri libglx-mesa0 xvfb xauth x11-utils x11vnc novnc websockify; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/unitree_ros2
ARG UNITREE_ROS2_REF=668d1ec5a05d1c38d3306bdca7d59f2ba3581a88
RUN set -e; \
    git init -q .; git fetch --depth 1 https://github.com/unitreerobotics/unitree_ros2.git "$UNITREE_ROS2_REF"; \
    git checkout -q --detach FETCH_HEAD; cd cyclonedds_ws; \
    git clone --depth 1 --branch 0.10.2 https://github.com/eclipse-cyclonedds/cyclonedds.git src/cyclonedds; \
    export MAKEFLAGS=-j2 CMAKE_BUILD_PARALLEL_LEVEL=2; \
    colcon build --merge-install --executor sequential --packages-select cyclonedds \
      --cmake-args -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_LIBDIR=lib -DBUILD_TESTING=OFF; \
    source /opt/ros/foxy/setup.bash; source install/local_setup.bash; \
    colcon build --merge-install --executor sequential --packages-select unitree_go unitree_hg unitree_api \
      --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DCycloneDDS_DIR="$PWD/install/lib/cmake/CycloneDDS"; \
    rm -rf build log

# Include only the read-only client entry point from the operator toolbox.
COPY src/g1stairs/__init__.py /opt/g1-tools/g1stairs/
COPY src/g1stairs/camera/__init__.py src/g1stairs/camera/remote.py /opt/g1-tools/g1stairs/camera/
COPY src/g1stairs/camera/resources/ /opt/g1-tools/g1stairs/camera/resources/
COPY docker/windows/g1 /usr/local/bin/g1
COPY docker/windows/loopback.xml docker/windows/remote.rviz /opt/g1/
COPY docker/tools/verify-foxy.py /opt/g1/verify-foxy.py
ENV ROS_DISTRO=foxy ROS_VERSION=2 ROS_PYTHON_VERSION=3 ROS_DOMAIN_ID=0 \
    RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI=file:///opt/g1/loopback.xml \
    AMENT_PREFIX_PATH=/opt/unitree_ros2/cyclonedds_ws/install:/opt/ros/foxy \
    LD_LIBRARY_PATH=/opt/unitree_ros2/cyclonedds_ws/install/lib:/opt/ros/foxy/lib:/opt/ros/foxy/lib/x86_64-linux-gnu \
    PYTHONPATH=/opt/g1-tools:/opt/unitree_ros2/cyclonedds_ws/install/lib/python3.8/site-packages:/opt/ros/foxy/lib/python3.8/site-packages \
    PATH=/opt/unitree_ros2/cyclonedds_ws/install/bin:/opt/ros/foxy/bin:${PATH} \
    G1_RVIZ_CONFIG=/opt/g1/remote.rviz LIBGL_ALWAYS_SOFTWARE=1 QT_X11_NO_MITSHM=1 \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN set -e; \
    chmod 0755 /usr/local/bin/g1; \
    printf '%s\n' 'source /opt/ros/foxy/setup.bash' 'source /opt/unitree_ros2/cyclonedds_ws/install/local_setup.bash' > /opt/g1/ros_env.sh; \
    printf '\nsource /opt/g1/ros_env.sh\n' >> /root/.bashrc; source /opt/g1/ros_env.sh; \
    python3 /opt/g1/verify-foxy.py; \
    test "$(ros2 pkg prefix rmw_cyclonedds_cpp)" = /opt/ros/foxy; \
    dpkg-query -W -f='${Version}\n' ros-foxy-rmw-cyclonedds-cpp | grep -E '^0\.7\.11[-+]'; \
    ros2 interface show unitree_hg/msg/LowState >/dev/null; g1 camera remote receive --help >/dev/null; \
    test -s /usr/share/novnc/vnc.html; bash -n /opt/g1-tools/g1stairs/camera/resources/rviz-web.sh
WORKDIR /workspace
CMD ["sleep", "infinity"]
