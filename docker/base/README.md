<!-- Author: Codex (IIC) -->
# G1 PC2 통합 CPU 이미지 `g1-jsj:base`

## G1 호스트에서 한 번 빌드

처음 설치할 때는 G1-EDU PC2의 SSH 터미널에서 아래 한 줄을 실행한다. `g1-jsj:base` 하나에 SDK와 온도·배터리 모니터, 키보드 텔레옵, RealSense 카메라, 계단 치수 계산이 함께 들어간다. 같은 태그의 이전 SDK 전용 이미지나 기존 `jsj-g1-tools` 컨테이너가 있으면 빌드 전에 [기존 이미지·기록 보관](../../docs/previous-runs.md)을 확인한다.

**G1 호스트**

```bash
docker build --pull=false --platform linux/arm64 -f docker/base/Dockerfile -t g1-jsj:base 'https://github.com/tokengeoji/g1-edu-loco.git#jsj'
```

Docker가 공개 Git 저장소의 `jsj` 브랜치를 가져와 `g1-jsj:base`를 빌드한다. 처음 빌드할 때 Dockerfile이 Canonical의 Ubuntu 20.04 ARM64 루트 파일시스템을 받아 빌드 안에서 준비한다. PC2에 Ubuntu 부모 이미지나 Git 체크아웃을 미리 준비할 필요가 없고 Docker 로그인과 이미지 pull도 필요 없다. PC2에서 Canonical, GitHub 및 Ubuntu·ROS·Python 패키지 서버에 접근할 수 있어야 한다. [Canonical 배포 파일 목록](https://partner-images.canonical.com/oci/focal/20250530.1/)

빌드가 성공하면 다음 명령으로 `linux/arm64`, 이미지 ID와 역할 `operator-tools`를 확인한다. 실패하면 마지막 오류 앞에서 실패한 단계와 다운로드 주소를 확인한다. 이 이미지를 사용해 이름이 `jsj-g1-tools`인 컨테이너를 생성·시작한다. [컨테이너 생성과 시작](../../README.md#pc2)

**G1 호스트**

```bash
docker image inspect g1-jsj:base --format '{{.Os}}/{{.Architecture}} {{.Id}} {{with .Config.Labels}}{{index . "org.iic.g1.role"}}{{end}}'
```

| 구성 | `g1-jsj:base`에 포함되는 내용 |
|---|---|
| 운영체제·언어 | Ubuntu 20.04 ARM64, Python 3.8, GCC 9 |
| ROS 2 | Foxy ros-base, sensor_msgs, ros2 CLI |
| 통신 | Cyclone DDS C 및 Python 0.10.2, Foxy rmw_cyclonedds_cpp |
| Unitree | Unitree SDK2 C++ 및 Python, unitree_hg·unitree_go·unitree_api 메시지 |
| 운영 도구 | `g1 health` · `g1 teleop` · `g1 camera` · `g1 stairs` |

## G1 호스트에서 운영 컨테이너 접속

통합 이미지 빌드와 컨테이너 시작을 마친 뒤 PC2의 SSH 터미널에서 실행한다.

**G1 호스트**

```bash
docker exec -it jsj-g1-tools bash
```

## 컨테이너 내부에서 버전과 NIC 확인

방금 연 컨테이너 셸에서 다음 명령을 실행한다.

**컨테이너 내부**

```bash
cat /etc/os-release
dpkg --print-architecture
printenv ROS_DISTRO RMW_IMPLEMENTATION
python3 -c 'from importlib.metadata import version; import rclpy; print(version("cyclonedds"), rclpy.get_rmw_implementation_identifier())'
ros2 pkg prefix unitree_hg
g1 --help
g1 interfaces
```

출력에서 Ubuntu 20.04, arm64, foxy, 0.10.2, rmw_cyclonedds_cpp 및 Unitree 메시지 경로를 확인한다. NIC 목록에서는 로봇과 같은 네트워크에 연결된 유선 인터페이스를 확인한다. [공식 SDK 버전과 적용 범위](../../README.md#sdk)
