ARG BASE_IMAGE
FROM ${BASE_IMAGE}

USER root
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG DEBIAN_FRONTEND=noninteractive
ENV BASH_ENV=/dev/null

RUN set -eux; \
    . /etc/os-release; \
    test "$ID" = ubuntu; \
    test "$VERSION_ID" = 20.04; \
    test "$(dpkg --print-architecture)" = arm64; \
    test -f /opt/ros/foxy/setup.bash; \
    python3 -c 'import sys; assert sys.version_info[:2] == (3, 8)'

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git curl \
    build-essential gcc-9 g++-9 make cmake pkg-config \
    libyaml-cpp-dev libeigen3-dev libboost-all-dev libfmt-dev \
    python3 python3-dev python3-pip python3-numpy python3-opencv \
    python3-colcon-common-extensions \
    ros-foxy-rmw-cyclonedds-cpp \
    ros-foxy-rosidl-generator-dds-idl \
    && rm -rf /var/lib/apt/lists/*

ENV CC=/usr/bin/gcc-9 CXX=/usr/bin/g++-9

RUN git clone --depth 1 \
    https://github.com/unitreerobotics/unitree_ros2.git \
    /opt/unitree_ros2

# CycloneDDS는 Foxy 환경 source 전에 빌드
RUN set -eux; \
    cd /opt/unitree_ros2/cyclonedds_ws/src; \
    git clone --depth 1 --branch foxy \
      https://github.com/ros2/rmw_cyclonedds.git; \
    git clone --depth 1 --branch 0.10.2 \
      https://github.com/eclipse-cyclonedds/cyclonedds.git; \
    cd ..; \
    colcon build --merge-install --packages-select cyclonedds \
      --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF

# Foxy와 colcon 초기화 파일은 설정되지 않은 셸 변수를 읽을 수 있다.
RUN set -ex; \
    source /opt/ros/foxy/setup.bash; \
    source /opt/unitree_ros2/cyclonedds_ws/install/local_setup.bash; \
    cd /opt/unitree_ros2/cyclonedds_ws; \
    colcon build --merge-install \
      --packages-up-to rmw_cyclonedds_cpp unitree_go unitree_hg unitree_api \
      --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF

RUN set -eux; \
    git clone --depth 1 \
      https://github.com/unitreerobotics/unitree_sdk2.git \
      /opt/unitree_sdk2; \
    cmake -S /opt/unitree_sdk2 -B /opt/unitree_sdk2/build \
      -DCMAKE_BUILD_TYPE=Release -DBUILD_EXAMPLES=OFF \
      -DCMAKE_INSTALL_PREFIX=/opt/unitree_robotics; \
    cmake --build /opt/unitree_sdk2/build; \
    cmake --install /opt/unitree_sdk2/build

ENV CYCLONEDDS_HOME=/opt/unitree_ros2/cyclonedds_ws/install
RUN set -eux; \
    python3 -m pip install --no-cache-dir 'cyclonedds==0.10.2'; \
    git clone --depth 1 \
      https://github.com/unitreerobotics/unitree_sdk2_python.git \
      /opt/unitree_sdk2_python; \
    python3 -m pip install --no-cache-dir --no-deps \
      /opt/unitree_sdk2_python; \
    python3 -c 'import cyclonedds, unitree_sdk2py, numpy, cv2'

# 이미지 내부에만 스크립트·bashrc 내용 생성
RUN set -eux; \
    mkdir -p /opt/g1 /workspace; \
    printf '%s\n' \
      'source /opt/ros/foxy/setup.bash' \
      'source /opt/unitree_ros2/cyclonedds_ws/install/setup.bash' \
      'export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp' \
      > /opt/g1/ros_env.sh; \
    printf '\nsource /opt/g1/ros_env.sh\n' >> /root/.bashrc

ENV ROS_DOMAIN_ID=0 \
    RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    BASH_ENV=/opt/g1/ros_env.sh \
    CMAKE_PREFIX_PATH=/opt/unitree_robotics

WORKDIR /workspace
ENTRYPOINT []
CMD ["/bin/bash"]
