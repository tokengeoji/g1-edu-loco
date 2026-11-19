# PC2 공통 이미지 `jsj-g1-base:foxy`

세 기능 컨테이너가 사용하는 Ubuntu 20.04 ARM64 · ROS 2 Foxy · Python 3.8 이미지입니다. Unitree SDK2(C++·Python), Unitree ROS 2 메시지, CycloneDDS 0.10.2와 Git을 포함합니다. 기존 이미지가 이미 있으면 [기능별 실행 가이드](../../README.md#pc2)에서 바로 시작하세요. [Dockerfile](Dockerfile)

<a id="build"></a>

## 1. PC2 터미널에서 이미지 준비

아래 **블록 전체**를 복사해 붙여넣으세요. 같은 이름의 공통 이미지가 있으면 즉시 종료합니다. 새로 만드는 경우 프로젝트 문서의 R35.3.1 예시는 PC2가 해당 L4T 버전을 보고할 때 선택합니다. 다른 버전에서는 현장에서 호환성을 확인한 부모 이미지 태그를 입력합니다. Dockerfile은 표준입력으로 전달하고 Git 복제와 패키지 설치는 이미지 빌드 레이어 안에서 실행합니다. [Docker 표준입력 빌드](https://docs.docker.com/build/concepts/context/#empty-context) · [부모 이미지 배포처](https://hub.docker.com/r/dustynv/ros/tags)

```bash
(
  set -euo pipefail
  if docker image inspect jsj-g1-base:foxy >/dev/null 2>&1; then
    echo 'jsj-g1-base:foxy 준비됨'
    exit 0
  fi

  if grep -Eq '^#[[:space:]]+R35[[:space:]].*REVISION:[[:space:]]*3\.1([,[:space:]]|$)' /etc/nv_tegra_release 2>/dev/null; then
    parent='dustynv/ros:foxy-ros-base-l4t-r35.3.1'
  else
    cat /etc/nv_tegra_release 2>/dev/null || true
    read -rp '이 PC2의 L4T와 호환되는 ARM64 Ubuntu 20.04/Foxy 이미지 태그(미확인 시 Enter로 종료): ' parent
    [[ -n "$parent" ]] || exit 1
  fi

  if ! docker image inspect "$parent" >/dev/null 2>&1; then
    docker pull --platform linux/arm64 "$parent"
  fi
  [[ "$(docker image inspect --format '{{.Os}}/{{.Architecture}} {{len .Config.Volumes}}' "$parent")" == 'linux/arm64 0' ]] || {
    echo '부모 이미지의 플랫폼과 VOLUME 선언을 확인하세요.' >&2
    exit 1
  }

  docker build --pull=false --platform linux/arm64 --build-arg BASE_IMAGE="$parent" \
    -t jsj-g1-base:foxy - <<'DOCKERFILE'
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
DOCKERFILE
)
```

## 2. 이미지 안의 SDK 확인

PC2 터미널에 아래 블록을 붙여넣으세요. 일회성 컨테이너에서 실제 SDK와 메시지 타입을 불러옵니다. 마지막에 `Unitree SDK2 및 Foxy 메시지 확인 완료`가 출력되면 [기능별 컨테이너 생성](../../README.md#pc2)으로 진행합니다.

```bash
docker run --rm --name jsj-base-check --pull never --network none \
  --cap-drop ALL --security-opt no-new-privileges:true jsj-g1-base:foxy \
  bash -ec '
    python3 --version
    for pkg in unitree_go unitree_hg unitree_api; do ros2 pkg prefix "$pkg"; done
    python3 -c "import cyclonedds, numpy, cv2; from unitree_sdk2py.core.channel import ChannelSubscriber; from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_"
    echo "Unitree SDK2 및 Foxy 메시지 확인 완료"
  '
```

설치 순서와 구성은 프로젝트의 공통 베이스 정의를 따릅니다. Foxy를 불러오는 빌드 단계에서는 초기화 스크립트가 아직 설정되지 않은 셸 변수를 참조할 수 있어 Bash의 `nounset` 옵션을 사용하지 않습니다. 실제 PC2 빌드와 하드웨어 수신은 미확인입니다. [프로젝트 베이스 정의](https://app.notion.com/p/41a3c6661b7d8117a89cf15e9824c6fa) · [Unitree ROS 2](https://github.com/unitreerobotics/unitree_ros2) · [Unitree SDK2](https://github.com/unitreerobotics/unitree_sdk2) · [Unitree SDK2 Python](https://github.com/unitreerobotics/unitree_sdk2_python)
