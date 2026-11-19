# G1 PC2 공통 CPU 이미지

PC2에 SSH로 접속해 아래 블록을 실행하면 **공통 이미지 `g1-jsj:base`만** 만듭니다. Docker가 공개 Git 브랜치를 빌드 컨텍스트로 가져옵니다. 호스트 체크아웃이나 Docker Hub 계정이 필요하지 않습니다. 로컬 부모 이미지를 읽는 PC2의 기본 Docker Engine 빌더를 사용하세요. 부모를 처음 준비할 때 Canonical에, 빌드할 때 GitHub 및 Ubuntu·ROS·Python 패키지 서버에 접근할 수 있어야 합니다. [Canonical Focal ARM64 rootfs](https://partner-images.canonical.com/oci/focal/20250530.1/)

```bash
(
  set -e
  parent=jsj-ubuntu:20.04
  if docker image inspect jsj-g1-base:ubuntu20.04-cpu >/dev/null 2>&1; then
    parent=jsj-g1-base:ubuntu20.04-cpu
  elif docker image inspect g1-jsj-ubuntu:20.04 >/dev/null 2>&1; then
    parent=g1-jsj-ubuntu:20.04
  elif ! docker image inspect "$parent" >/dev/null 2>&1; then
    docker import --change 'CMD ["/bin/bash"]' \
      'https://partner-images.canonical.com/oci/focal/20250530.1/ubuntu-focal-oci-arm64-root.tar.gz' "$parent"
  fi
  docker run --pull never --rm --name "jsj-base-check-$BASHPID" --runtime=runc --network none "$parent" sh -ec \
    '. /etc/os-release; echo "$PRETTY_NAME / $(dpkg --print-architecture)"; test "$ID:$VERSION_ID:$(dpkg --print-architecture)" = ubuntu:20.04:arm64'
  docker build --pull=false --platform linux/arm64 --build-arg BASE_IMAGE="$parent" \
    -f docker/base/Dockerfile -t g1-jsj:base 'https://github.com/tokengeoji/g1-edu-loco.git#jsj'
)
```

이미 빌드한 `jsj-g1-base:ubuntu20.04-cpu` 또는 `g1-jsj-ubuntu:20.04`가 있으면 그 로컬 이미지를 먼저 검사합니다. Ubuntu 20.04 ARM64인지 확인하는 단계가 실패하면 해당 이미지의 출처와 태그를 확인하세요. 소스를 갱신할 때도 같은 블록을 사용합니다. 빌드 첫 실패 지점과 상세 로그는 `docker build`의 터미널 출력에서 확인합니다.

| 구성 | `g1-jsj:base`에 들어가는 내용 |
|---|---|
| 운영체제·언어 | Ubuntu 20.04 ARM64, Python 3.8, GCC 9 |
| ROS 2 | Foxy ros-base, sensor_msgs, ros2 CLI |
| 통신 | Cyclone DDS C 및 Python 0.10.2, Foxy rmw_cyclonedds_cpp |
| Unitree | Unitree SDK2 C++ 및 Python, unitree_hg·unitree_go·unitree_api 메시지 |

카메라와 키보드 원격조종은 이 이미지에서 파생되는 별도 빌드입니다. [카메라](../../README.md#camera) · [키보드 원격조종 및 원본 상태 모니터](../../g1_teleop/README.md) · [Unitree ROS 2](https://github.com/unitreerobotics/unitree_ros2)

## PC2에서 버전과 NIC 확인

```bash
docker run --pull never --rm --name "jsj-base-version-$BASHPID" --runtime=runc --network none g1-jsj:base bash -ec '
  . /etc/os-release
  echo "$PRETTY_NAME / $(dpkg --print-architecture) / ROS $ROS_DISTRO"
  python3 -c "from importlib.metadata import version; import rclpy; print(version(\"cyclonedds\"), rclpy.get_rmw_implementation_identifier())"
  ros2 pkg prefix unitree_hg
'
docker run --pull never --rm --name "jsj-base-nic-$BASHPID" --runtime=runc --network host g1-jsj:base ip -br -4 addr
```

정상 출력에는 Ubuntu 20.04, arm64, foxy, 0.10.2, rmw_cyclonedds_cpp와 Unitree 메시지 설치 경로가 포함됩니다. NIC 출력에서 로봇 네트워크 주소를 가진 인터페이스를 찾습니다.
