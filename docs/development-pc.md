<!-- Author: Codex (IIC) -->
# G1 개발 PC에서 ROS 2 Foxy와 Cyclone DDS 사용하기

| 사용하려는 환경 | ROS 2를 준비할 위치 | 사용할 유선 NIC |
| --- | --- | --- |
| 외부 PC에서 SSH로 G1 조작 | PC2의 `jsj-g1-tools`에 이미 설치되어 있다. 외부 PC는 SSH 터미널만 연다. | 현장 로그에서 PC2는 `eth0`, `192.168.123.164/24` |
| 외부 Linux 개발 PC에서 ROS 2 노드를 직접 실행 | 별도의 Ubuntu 20.04 **amd64** 개발 컨테이너에 아래의 Foxy 환경을 준비한다. 외부 PC의 Ubuntu 22.04/Humble은 다른 실험에 계속 쓸 수 있다. | 개발 PC에서 스위치로 이어지는 Ethernet NIC. 이름은 PC마다 다르다. |

### 1. 연구실 기본 구성 — SSH로 PC2 사용

개발 PC를 연구실 유선 스위치에 연결한다. 개발 PC 유선 주소는 같은 `192.168.123.0/24`의 미사용 주소여야 한다. 기존 실험에서 PC2의 `eth0`에 관측한 주소는 `192.168.123.164`다. Unitree 문서의 개발 PC 주소 `192.168.123.99`는 예시다. [Unitree 유선 네트워크 설정](https://github.com/unitreerobotics/unitree_ros2#connect-to-unitree-robot)

**외부 Linux 개발 PC · 유선 경로 확인 후 SSH 접속**

```bash
ip -br -4 addr
ip route get 192.168.123.164
ssh unitree@192.168.123.164
```

`ip route get`의 `dev`가 로봇 스위치에 연결한 유선 포트이고 `src`가 그 포트의 주소인지 확인한다. Mac에서 SSH만 사용할 경우에는 터미널에서 마지막 줄을 실행한다.

**G1 호스트 · 실행 중인 운영 컨테이너 접속**

```bash
docker exec -it jsj-g1-tools bash
```

**컨테이너 내부 · 설치된 버전과 메시지 확인**

```bash
source /opt/g1/ros_env.sh
. /etc/os-release
printf 'Ubuntu %s, %s, ROS %s\n' "$VERSION_ID" "$(dpkg --print-architecture)" "$ROS_DISTRO"
python3 -c 'from importlib.metadata import version; import rclpy; print(rclpy.get_rmw_implementation_identifier(), version("cyclonedds"))'
ros2 pkg prefix unitree_hg
ros2 interface show unitree_hg/msg/LowState
g1 interfaces
```

이 이미지의 기대값은 `Ubuntu 20.04, arm64, ROS foxy`와 `rmw_cyclonedds_cpp 0.10.2`다. 두 번째 줄의 버전 숫자는 Python Cyclone DDS 패키지의 버전이다. 이미지에서 C 라이브러리도 0.10.2로 빌드한다. Bash 셸은 Foxy 다음에 Unitree 메시지 작업공간을 불러온다. 새 PC2의 최초 이미지 빌드 및 컨테이너 생성 순서는 [운영 이미지 가이드](../README.md#pc2), 고정한 버전은 [Dockerfile](../docker/base/Dockerfile)에서 확인한다.

### 2. 외부 Linux 개발 PC에서 직접 구독할 경우

SSH로만 접속한다면 3절로 넘어간다. 아래는 유선 DDS를 직접 사용할 **별도의 개발용** Ubuntu 20.04 amd64 컨테이너를 이미 보유한 경우다. Linux Docker의 host 네트워크 모드 등으로 해당 컨테이너에서 연구실 유선 NIC와 로봇 서브넷이 실제로 보여야 한다. PC2 운영 이미지는 ARM64 전용이다. PC2 배포용 이미지 빌드와 컨테이너 생성은 기존처럼 PC2에서 수행한다.

아래 최초 설치는 root인 개발 컨테이너 내부에서 수행한다. Ubuntu 공식 Focal 패키지 저장소(universe 포함)와 인터넷 접속을 사용한다. ROS 환경을 불러오지 않은 깨끗한 Bash에서 시작한다.

**컨테이너 내부 · 외부 개발 PC의 Focal amd64 전용 · ROS 2 Foxy 설치**

```bash
(
  set -e
  . /etc/os-release
  test "$ID:$VERSION_ID:$(dpkg --print-architecture)" = ubuntu:20.04:amd64
  test -z "${ROS_DISTRO:-}"
  apt-get update
  apt-get install -y ca-certificates curl
  curl -fL --retry 3 -o /tmp/iic-ros2-apt-source.deb \
    https://github.com/ros-infrastructure/ros-apt-source/releases/download/1.3.0/ros2-apt-source_1.3.0.focal_all.deb
  echo '14c22046f6aae248a37a7bb52000ad1fae29aa1d7ae9fb7aead90bb01ad99355  /tmp/iic-ros2-apt-source.deb' | sha256sum -c -
  apt-get install -y /tmp/iic-ros2-apt-source.deb
  apt-get update
  apt-get install -y git cmake build-essential iproute2 libssl-dev libyaml-cpp-dev \
    python3-colcon-common-extensions ros-foxy-ros-base ros-foxy-geometry-msgs \
    ros-foxy-rmw-cyclonedds-cpp ros-foxy-rosidl-generator-dds-idl ros-foxy-rosidl-default-generators
)
```

다음 블록은 처음 구성할 때 한 번 실행한다. Foxy용 RMW는 PC2와 같은 커밋을 사용한다. Cyclone DDS C 라이브러리를 먼저 빌드하고 Foxy를 불러온 뒤 RMW 및 G1 메시지를 빌드한다. [Unitree ROS 2 설치 순서](https://github.com/unitreerobotics/unitree_ros2#install-unitree-ros2-package) · [ROS 패키지 저장소 설정 파일](https://github.com/ros-infrastructure/ros-apt-source/releases/tag/1.3.0)

**컨테이너 내부 · 외부 개발 PC · Cyclone DDS와 Unitree 메시지 설치**

```bash
(
  set -e
  test -z "${ROS_DISTRO:-}"
  mkdir /opt/iic-unitree-ros2
  cd /opt/iic-unitree-ros2
  git init -q
  git fetch --depth 1 https://github.com/unitreerobotics/unitree_ros2.git 668d1ec5a05d1c38d3306bdca7d59f2ba3581a88
  git checkout -q --detach FETCH_HEAD
  cd cyclonedds_ws
  git clone --depth 1 --branch 0.10.2 https://github.com/eclipse-cyclonedds/cyclonedds.git src/cyclonedds
  git init -q src/rmw_cyclonedds
  git -C src/rmw_cyclonedds fetch --depth 1 https://github.com/ros2/rmw_cyclonedds.git c12abc56983204f1d91f2d839d394528c7b29b42
  git -C src/rmw_cyclonedds checkout -q --detach FETCH_HEAD
  colcon build --merge-install --executor sequential --packages-select cyclonedds \
    --cmake-args -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_LIBDIR=lib -DBUILD_TESTING=OFF
  source /opt/ros/foxy/setup.bash
  source install/local_setup.bash
  colcon build --merge-install --executor sequential --packages-select rmw_cyclonedds_cpp unitree_hg unitree_go unitree_api \
    --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
    -DCycloneDDS_DIR="$PWD/install/lib/cmake/CycloneDDS"
)
```

**컨테이너 내부 · 외부 개발 PC · 새 셸을 열 때마다**

```bash
source /opt/ros/foxy/setup.bash
source /opt/iic-unitree-ros2/cyclonedds_ws/install/local_setup.bash
ros2 pkg prefix unitree_hg
ros2 pkg prefix rmw_cyclonedds_cpp
```

두 패키지의 경로가 모두 `/opt/iic-unitree-ros2/cyclonedds_ws/install`이면 개발 작업공간의 패키지를 사용 중이다. 여기까지가 표준 ROS 2와 Unitree 메시지 구독에 필요한 구성이다.

### 3. 유선 NIC, 도메인, 실제 수신 확인

아래 명령은 PC2 운영 컨테이너와 외부 개발 컨테이너에서 공통으로 쓴다. NIC 이름은 **명령을 실행할 컨테이너**의 `ip -br -4 addr` 결과에서 선택한다. PC2 현장값은 `eth0`이고 로봇 상태 DDS 도메인은 `0`이다. 환경변수는 ROS 노드를 실행할 각 셸에서 설정한다. [Unitree Cyclone DDS 설정 예제](https://github.com/unitreerobotics/unitree_ros2/blob/668d1ec5a05d1c38d3306bdca7d59f2ba3581a88/setup.sh)

**컨테이너 내부 · 유선 인터페이스 선택**

```bash
ip -br -4 addr
read -rp 'G1 유선 NIC 이름: ' G1_NIC
if ip link show dev "$G1_NIC" >/dev/null; then
  export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  export CYCLONEDDS_URI="<CycloneDDS><Domain><General><Interfaces><NetworkInterface name=\"$G1_NIC\"/></Interfaces></General></Domain></CycloneDDS>"
  printf 'NIC=%s domain=%s RMW=%s\n' "$G1_NIC" "$ROS_DOMAIN_ID" "$RMW_IMPLEMENTATION"
else
  echo '유선 NIC를 다시 확인하세요.'
fi
```

**컨테이너 내부 · 읽기 전용 구독 확인**

```bash
ros2 topic list --no-daemon --spin-time 3 -t
timeout --signal=INT 8s ros2 topic hz /lowstate
```

`/lowstate [unitree_hg/msg/LowState]`가 목록에 있고 다음 명령에서 `average rate`가 출력되면 그 셸까지 실제 G1 상태 샘플이 연속 도착한 것이다. `timeout`은 8초에 관찰을 끝낸다. 토픽 이름만 표시되면 아직 샘플 수신은 미확인이다. PC2와 외부 개발 PC에서 결과가 다르면 각 컨테이너의 유선 주소·NIC·도메인과 개발 PC의 DDS 멀티캐스트 경로를 비교한다.

프로젝트 CLI를 사용할 때 카메라는 `G1_CAMERA_IFACE`와 `G1_CAMERA_DOMAIN`, 텔레옵은 `--interface`와 `--domain`으로 구독할 망을 선택한다. 아래 두 명령은 기체 상태와 카메라 발행자를 조회한다. 깊이 프레임 수신은 [카메라 가이드](../README.md#camera)에서 별도로 확인한다.

**컨테이너 내부 · G1 PC2의 jsj-g1-tools**

```bash
g1 teleop --status --interface "$G1_NIC" --domain 0
G1_CAMERA_IFACE="$G1_NIC" G1_CAMERA_DOMAIN=0 g1 camera discover --seconds 8
```
