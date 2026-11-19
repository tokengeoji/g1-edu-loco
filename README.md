<!-- Author: Codex (IIC) -->
# G1-EDU PC2 운영 도구

배터리·모터 온도 확인, 키보드 텔레옵, 헤드 RealSense D435i 설정·기록, 계단 치수 계산을 PC2의 **`jsj-g1-tools` 컨테이너 하나**에서 실행한다. 여러 SSH 터미널이 같은 컨테이너와 실험 데이터를 사용한다. 텔레옵은 로봇에 탑재된 Unitree 보행기에 명령을 보낸다. 연구용 보행 정책의 학습·실행과 관절 저수준 제어는 별도 작업이다. [IIC 작업 규칙](AGENTS.md)

<a id="pc2"></a>

## PC2에서 한 번 준비

G1-EDU의 PC2에 SSH로 접속해 실행한다. PC2 호스트에 프로그램을 설치하거나 Git 저장소를 내려받을 필요가 없다. Docker Engine이 GitHub의 `jsj` 브랜치를 읽어서 **로컬 CPU 이미지**를 빌드한다. 최초 빌드에는 인터넷 연결이 필요하다.

1. `docker image inspect g1-jsj:base`로 공통 이미지가 있는지 확인한다. 없으면 [베이스 빌드 명령](docker/base/README.md)의 첫 코드 블록을 실행한다.
2. 아래 명령으로 온도·텔레옵·카메라·계단 계산이 들어 있는 통합 이미지를 빌드한다.
3. [PC2 컨테이너 시작 명령](docker/tools/pc2.sh)의 코드 전체를 PC2 Bash에 한 번 붙여넣어 실행한다. 다음 실험에도 같은 명령을 사용한다. USB 직접 촬영을 사용할 때는 D435i가 PC2에서 인식된 상태에서 처음 생성한다.

```bash
docker build --pull=false --platform linux/arm64 \
  -f docker/tools/Dockerfile -t jsj-g1-tools:foxy \
  'https://github.com/tokengeoji/g1-edu-loco.git#jsj'
```

```bash
docker exec jsj-g1-tools g1 --help
docker exec jsj-g1-tools g1 interfaces
```

아래부터는 모두 **같은 컨테이너**에 접속하는 명령이다. 각 SSH 터미널에서 쓸 NIC는 기존 온도 모니터가 정상 작동한 로봇용 유선 인터페이스다.

<a id="monitoring"></a>

## 온도 측정과 키보드 조작

**터미널 1**에서 원본 배터리·온도 모니터를 실행해 둔다. 모터·배터리 최신 수신 상태를 확인한다. 원본은 DDS 도메인 0을 사용한다. 관절·IMU 대시보드와 상태 기록은 [모니터 안내](src/g1stairs/monitoring/README.md)를 따른다.

```bash
read -rp '로봇 NIC: ' G1_IFACE
docker exec -it jsj-g1-tools g1 health "$G1_IFACE"
```

**터미널 2**에서 상태 조회부터 한다. 기체와 왕복 통신이 되면 실제 FSM, NIC, 도메인, 응답한 서비스(`sport` 또는 `loco`)가 표시된다. `--dry-run`에서 키 배치를 연습할 수 있다.

```bash
read -rp '같은 로봇 NIC: ' G1_IFACE
docker exec jsj-g1-tools g1 teleop --status --interface "$G1_IFACE" --domain 0
docker exec -it jsj-g1-tools g1 teleop --dry-run
```

실기체 첫 동작은 숙련자 입회하에 온도·배터리, 기체 지지와 물리 조종기를 확인한 뒤 진행한다. `--live` 시작 후 `r`로 활성화하고 `f`로 모드를 읽는다. 기본 보행 요청은 `2` → `Enter`이며 **실제 FSM 500**에서 이동한다. `w/s`는 전후, `a/d`는 좌우, `q/e`는 회전, `Space`는 이동 속도 0이다. 컨테이너 내부에서는 한 번에 한 터미널만 실기체 제어를 연다. 이전 텔레옵 컨테이너나 다른 PC의 보행 명령 송신기는 현장에서 별도로 종료 여부를 확인한다. [전체 키 배치와 모드 전환 조건](src/g1_teleop/README.md)

```bash
docker exec -it jsj-g1-tools g1 teleop --live --interface "$G1_IFACE" --domain 0
```

<a id="camera"></a>

## 카메라 설정 → 영상 확인 → 깊이 기록

**터미널 3**에서 먼저 실제 발행자와 수신 샘플을 확인한다. 같은 ROS 2 영상 스트림이 ROS 그래프와 DDS 목록에 함께 보일 수 있다. 발행자, 타입, 광학 프레임으로 헤드 D435i의 깊이 영상인지 대조한다.

```bash
docker exec jsj-g1-tools g1 camera discover --seconds 8
```

| 관측 결과 | 같은 컨테이너에서 할 일 |
| --- | --- |
| `sensor_msgs/msg/Image`에서 실제 영상 수신 | `docker exec -it jsj-g1-tools g1 camera rviz` 실행. PC2 브라우저에서 터미널에 나온 로컬 주소를 열고 RViz2의 **Camera image → Topic**에서 수신 토픽을 선택한다. 센서 QoS는 Best Effort다. |
| 지원되는 `sensor_msgs/msg/CompressedImage` 수신 | `docker exec -it jsj-g1-tools g1 camera compressed-view "$TOPIC"`으로 풀고 다른 터미널의 RViz2에서 `/g1_jsj/view_image`를 선택한다. |
| ROS 이미지가 없고 네이티브 DDS 발행자가 보임 | 탐색 출력의 실제 DDS 이름과 타입으로 `docker exec jsj-g1-tools g1 camera tty-dds --topic "$TOPIC" --type "$TYPE" --seconds 5`를 실행한다. XTypes가 없으면 발행자의 공식 IDL 클래스가 필요하다. |
| PC2의 USB에 D435i가 직접 연결됨 | `docker exec jsj-g1-tools g1 camera probe-usb`로 장치와 프로필을 확인하고 `docker exec jsj-g1-tools g1 camera tty-usb --seconds 5`로 샘플을 확인한다. USB를 점유 중인 다른 프로그램이 있으면 그 발행자의 영상을 쓴다. |

도메인이나 카메라 NIC를 지정하려면 각 카메라 명령의 `docker exec`에 `-e G1_CAMERA_DOMAIN=값 -e G1_CAMERA_IFACE=인터페이스명`을 추가한다. 예를 들어 `docker exec -e G1_CAMERA_DOMAIN=0 -e G1_CAMERA_IFACE="$G1_IFACE" jsj-g1-tools g1 camera discover`처럼 사용한다.

ROS 2에서 **보정된 원시 깊이 영상(`16UC1`)과 같은 촬영 시각·광학 프레임의 CameraInfo**가 발행되고 있을 때 다음과 같이 기록한다. 셸 변수에는 실제 값을 입력한다. 깊이 단위는 발행자의 설정에서 확인한다. USB 직접 기록은 SDK가 장치에서 깊이 스케일을 읽는다. 계단 측정용 녹화는 보정 때와 같은 자세로 기체를 정지시킨 상태에서 한다.

```bash
RUN_ID=$(docker exec jsj-g1-tools date -u +stairs-%Y%m%dT%H%M%SZ)
read -rp 'Depth Image topic: ' DEPTH_TOPIC
read -rp 'CameraInfo topic: ' INFO_TOPIC
read -rp '발행자에서 확인한 깊이 1단위당 미터: ' DEPTH_SCALE
docker exec jsj-g1-tools g1 camera record-ros --run "$RUN_ID" --seconds 10 \
  --depth-topic "$DEPTH_TOPIC" --info-topic "$INFO_TOPIC" --depth-scale-m "$DEPTH_SCALE"
```

USB에서 바로 기록할 때는 위 ROS 기록 명령 대신 아래 블록을 사용한다. 현장에서 `probe-usb`로 지원 여부를 확인한 뒤 가이드 기본값인 `640×480, 60 FPS, Z16` 또는 지원되는 다른 프로필을 사용한다.

```bash
RUN_ID=$(docker exec jsj-g1-tools date -u +stairs-%Y%m%dT%H%M%SZ)
docker exec jsj-g1-tools g1 camera record --run "$RUN_ID" --seconds 10
```

<a id="geometry"></a>

## 같은 기록으로 계단 높이·디딤면 깊이·폭 계산

촬영한 깊이와 분석 결과는 `/workspace/runs/<RUN_ID>/depth/`와 `geometry/`에 각각 저장된다. 기록 직후 같은 터미널에서 같은 `RUN_ID`를 사용한다. 모터 상태를 함께 기록하려면 다른 터미널에서 같은 실험 이름으로 `g1 monitor record`를 실행하면 `state/`에 저장된다.

광학 좌표를 **앞·왼쪽·위** 기준 좌표로 바꾸는 실측 회전·이동이 필요하다. [보정 JSON](config/calibration.example.json)은 필드 형식 예시다. `source_frame`은 해당 깊이 기록의 `frame_id`와 맞춰야 한다. 기체 자세·센서 장착이 바뀌면 이전 보정값을 재사용하지 않는다. 실측 JSON이 아직 컨테이너에 없으면 아래 블록을 실행한 뒤 JSON을 붙여넣고 새 줄에서 Ctrl+D를 누른다. 실험별 새 파일에만 저장한다.

```bash
CAL="/workspace/runs/$RUN_ID/measured-calibration.json"
docker exec -i jsj-g1-tools python3 -c '
import json, sys
from g1stairs.geometry.projection import Calibration
data = json.load(sys.stdin)
Calibration.from_mapping(data)
with open(sys.argv[1], "x") as f:
    json.dump(data, f)
' "$CAL"
```

```bash
docker exec jsj-g1-tools g1 stairs measure --run "$RUN_ID" --calibration "$CAL"
docker exec jsj-g1-tools head -n 1 "/workspace/runs/$RUN_ID/geometry/stairs.jsonl"
```

기록 당시 `--calibration`을 제공했으면 측정 단계의 `--calibration "$CAL"`을 생략할 수 있다. 기본은 첫 프레임이며 전체는 `--all-frames`다. 결과의 `riser_height_m`, `tread_depth_m`, `width_m`는 미터 단위 추정치다. 양쪽 경계가 보이지 않아 전체 폭을 결정할 수 없으면 `width_m`은 `null`이다. 디딤 가능 여부와 보행 명령은 이 출력에 포함되지 않는다.

<a id="sdk"></a>

## 기능별 디렉터리와 공식 SDK

| 디렉터리 | 역할과 사용 API |
| --- | --- |
| [src/g1_health_monitor](src/g1_health_monitor/) | 동작 확인된 연구실 C++ 원본. Unitree SDK2의 `ChannelSubscriber`, `LowState_`, `BmsState_`로 상태 수신. 이 폴더의 README는 원본 자료이며 PC2 실행은 이 페이지를 따른다. [공식 C++ SDK](https://github.com/unitreerobotics/unitree_sdk2/tree/aaf69cb56c9d5ed63d8b284008ec3a8ab999bec1) |
| [src/g1_teleop](src/g1_teleop/) | 공식 Python `LocoClient`의 `GetFsmId`, `SetFsmId`, `SetBalanceMode`, `SetVelocity`를 호출하는 키보드 입력기. [공식 Python SDK](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/unitree_sdk2py/g1/loco/g1_loco_client.py) |
| [src/g1stairs/monitoring](src/g1stairs/monitoring/) | Unitree SDK2 Python 상태 구독, 기록, 웹 대시보드 |
| [src/g1stairs/camera](src/g1stairs/camera/) | USB는 RealSense SDK 2.0(`pyrealsense2`), ROS 영상은 Foxy `rclpy`와 `sensor_msgs`, DDS 진단은 Eclipse Cyclone DDS. [Unitree 카메라 가이드](https://support.unitree.com/home/en/G1_developer/depth_camera_instruction) · [ROS 2 CameraInfo](https://github.com/ros2/common_interfaces/blob/foxy/sensor_msgs/msg/CameraInfo.msg) |
| [src/g1stairs/geometry](src/g1stairs/geometry/) | 공식 RealSense SDK의 역투영으로 미터 단위 3D 좌표를 구한 뒤, 프로젝트 알고리즘이 수평면과 관측된 경계를 찾아 계단 치수를 계산한다. [RealSense 좌표 변환](https://github.com/realsenseai/librealsense/wiki/Projection-in-RealSense-SDK-2.0) |
| [config](config/) · [docker/base](docker/base/) · [docker/tools](docker/tools/) | 보정 형식, 공통 SDK 환경, 단일 실행 이미지·시작 스크립트 |

공통 베이스는 공식 C++ SDK `aaf69cb`, Python SDK `814556d`, Unitree ROS 2 메시지 `668d1ec`, Foxy Cyclone RMW `c12abc5`와 Cyclone DDS `0.10.2`를 사용한다. 통합 이미지는 RealSense Python SDK `2.54.1.5217`의 ARM64 배포 파일을 해시로 확인한다. [Unitree ROS 2](https://github.com/unitreerobotics/unitree_ros2/tree/668d1ec5a05d1c38d3306bdca7d59f2ba3581a88) · [Cyclone DDS](https://github.com/eclipse-cyclonedds/cyclonedds/tree/0.10.2)

PC2에서 이미지 설치 후 회귀 테스트는 아래 명령으로 실행한다. 테스트는 실제 보행 명령을 보내지 않는다. 물리 카메라 수신 여부와 계단 치수 정확도는 해당 기체의 프레임과 계단 실측으로 확인한다.

```bash
docker exec jsj-g1-tools python3 -m unittest discover -s /opt/g1-tools -t /opt/g1-tools
```

<a id="resume"></a>

## 종료와 기존 데이터

각 도구는 실행한 터미널에서 종료한다. 동작 중인 텔레옵을 종료하고 기록이 끝났는지 확인한 후 `docker stop jsj-g1-tools`로 컨테이너를 정지한다. 다시 시작하면 같은 쓰기 레이어의 `/workspace/runs`가 유지된다. 컨테이너를 삭제하면 이 데이터도 삭제된다. 이전 기능별 컨테이너의 기록은 [기존 실험 가져오기](docs/previous-runs.md)를 따른다.
