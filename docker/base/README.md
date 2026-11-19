<!-- Author: Codex (IIC) -->
# G1 PC2 공통 CPU 이미지

SSH로 G1-EDU PC2에 접속해서 실행한다. Docker Engine이 PC2에 있는 Ubuntu 부모 이미지와 공개 Git 저장소의 Dockerfile로 `g1-jsj:base`를 빌드한다. Docker 로그인, 이미지 pull, 호스트의 Git 체크아웃은 필요 없다.

## 1. 부모 이미지 확인

```bash
docker image ls --no-trunc
```

- 본인 소유의 `jsj-ubuntu:20.04`가 있으면 2단계로 간다.
- 본인 소유의 Ubuntu 20.04 ARM64 이미지가 `jsj-g1-base:ubuntu20.04-cpu` 또는 `g1-jsj-ubuntu:20.04`라는 이름으로 있으면 2단계의 `BASE_IMAGE=` 뒤에 그 이름을 넣는다.
- 해당 이미지가 모두 없고 `jsj-ubuntu:20.04` 이름도 비어 있으면 다음 명령을 한 번 실행한다. Docker 데몬이 Canonical의 ARM64 Ubuntu 파일시스템을 직접 가져와 로컬 이미지를 만든다. [Canonical 배포 파일 목록](https://partner-images.canonical.com/oci/focal/20250530.1/)

```bash
docker import --change 'CMD ["/bin/bash"]' 'https://partner-images.canonical.com/oci/focal/20250530.1/ubuntu-focal-oci-arm64-root.tar.gz' jsj-ubuntu:20.04
```

## 2. 공통 이미지 빌드

PC2 기본 Docker Engine 빌더에서 실행한다. 기존 `g1-jsj:base`도 보관하려면 먼저 위 이미지 목록에서 `g1-jsj:base-saved-01` 이름이 비어 있는지 확인한 뒤 `docker image tag g1-jsj:base g1-jsj:base-saved-01`을 실행한다. 이미 사용 중인 보관 이름에는 새 번호를 쓴다.

```bash
docker build --pull=false --platform linux/arm64 --build-arg BASE_IMAGE=jsj-ubuntu:20.04 -f docker/base/Dockerfile -t g1-jsj:base 'https://github.com/tokengeoji/g1-edu-loco.git#jsj'
docker image inspect g1-jsj:base --format '{{.Os}}/{{.Architecture}} {{.Id}}'
```

첫 빌드 단계가 부모의 Ubuntu 20.04와 arm64를 검사한다. 빌드 중 GitHub, Ubuntu·ROS·Python 패키지 서버에 접근할 수 있어야 한다. 실패하면 `docker build` 출력의 첫 오류와 선택한 부모 태그를 확인한다. 검사가 끝나면 다음 단계에서 `jsj-g1-tools:foxy`를 빌드하고 운영 컨테이너 `jsj-g1-tools`를 시작한다. [통합 컨테이너 시작](../../README.md#pc2)

| 구성 | 공통 이미지에 포함되는 내용 |
|---|---|
| 운영체제·언어 | Ubuntu 20.04 ARM64, Python 3.8, GCC 9 |
| ROS 2 | Foxy ros-base, sensor_msgs, ros2 CLI |
| 통신 | Cyclone DDS C 및 Python 0.10.2, Foxy rmw_cyclonedds_cpp |
| Unitree | Unitree SDK2 C++ 및 Python, unitree_hg·unitree_go·unitree_api 메시지 |

## 운영 컨테이너에서 버전과 NIC 확인

```bash
docker exec jsj-g1-tools cat /etc/os-release
docker exec jsj-g1-tools dpkg --print-architecture
docker exec jsj-g1-tools printenv ROS_DISTRO RMW_IMPLEMENTATION
docker exec jsj-g1-tools python3 -c 'from importlib.metadata import version; import rclpy; print(version("cyclonedds"), rclpy.get_rmw_implementation_identifier())'
docker exec jsj-g1-tools ros2 pkg prefix unitree_hg
docker exec jsj-g1-tools g1 interfaces
```

출력에서 Ubuntu 20.04, arm64, foxy, 0.10.2, rmw_cyclonedds_cpp 및 Unitree 메시지 경로를 확인한다. NIC 목록에서는 로봇과 같은 네트워크에 연결된 유선 인터페이스를 확인한다. [공식 SDK 버전과 적용 범위](../../README.md#sdk)
