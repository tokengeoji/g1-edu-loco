<!-- Author: Codex (IIC) -->
# G1-EDU PC2 운영 도구

G1-EDU PC2에서 CPU 이미지 **`g1-jsj:base`**를 한 번 빌드하면 Ubuntu·ROS 2·공식 SDK와 운영 도구가 함께 설치된다. **`jsj-g1-tools`**는 이 이미지로 생성하는 컨테이너 이름이다. 각 G1 터미널에서 같은 컨테이너에 접속해 배터리·모터 온도, 키보드 텔레옵, RealSense D435i와 계단 치수를 확인한다. 텔레옵은 기체의 Unitree 고수준 보행기에 명령을 보낸다. [IIC 작업 규칙](AGENTS.md)

**처음 키보드를 연결한다면 [로봇을 움직이기 전 텔레옵 점검](docs/teleop-preflight.md)을 따른다.** 실제 모터·보행 상태를 읽고 방향키와 정지를 모의 입력하는 현장 절차다.

[이미지 빌드](#pc2) · [컨테이너 생성](#create) · [온도·텔레옵](#monitoring) · [카메라](#camera) · [계단 계산](#geometry) · [재개·기록 보관](#resume)

| 실행 위치 | 입력할 명령 |
| --- | --- |
| **G1 호스트** | G1-EDU PC2 터미널에서 Docker로 이미지를 빌드하고 컨테이너를 생성·시작하거나 내부 셸을 연다. |
| **컨테이너 내부** | 호스트에서 `docker exec -it jsj-g1-tools bash`를 실행한 다음 `g1` 도구와 데이터 처리 명령을 입력한다. 내부 셸에서 `exit`를 입력하면 G1 호스트로 돌아온다. |

<a id="pc2"></a>

## PC2에서 이미지 빌드

최초 설치와 업데이트에 같은 명령을 사용한다. G1-EDU PC2의 Docker가 공개 Git 브랜치를 빌드 컨텍스트로 가져오고, 최초 빌드에서 Canonical의 Ubuntu 20.04 ARM64 루트 파일시스템을 준비한다. 맥북 작업, PC2 호스트 체크아웃, Docker 로그인이나 이미지 pull은 필요 없다. [이미지 구성과 버전 확인](docker/base/README.md)

**G1 호스트 · 운영 도구까지 포함한 이미지 빌드**

```bash
docker build --pull=false --platform linux/arm64 -f docker/base/Dockerfile -t g1-jsj:base 'https://github.com/tokengeoji/g1-edu-loco.git#jsj'
```

**G1 호스트 · 기존 컨테이너 확인**

```bash
docker ps -a --filter 'name=^/jsj-g1-tools$'
```

<a id="create"></a>

## 컨테이너 생성과 시작

위 목록에 `jsj-g1-tools`가 있으면 [이미지 ID 확인과 기존 컨테이너 재개·교체](#resume)를 따른다. 이름이 비어 있으면 카메라 연결 방식에 따라 다음 중 하나를 고른다.

**로봇 네트워크의 ROS 2·DDS 카메라**를 쓸 때는 아래와 같이 생성한다. 이 구성에서 온도, 텔레옵, 카메라 토픽 탐색, 계단 계산을 모두 실행할 수 있다.

**G1 호스트 · 네트워크 카메라 구성으로 처음 생성**

```bash
docker create --name jsj-g1-tools --pull never --init --runtime=runc --network host --cap-drop ALL --security-opt no-new-privileges:true --log-driver none g1-jsj:base && docker start jsj-g1-tools
```

**PC2에 USB로 직접 연결한 D435i**에서 촬영하려면 카메라를 연결한 뒤 아래 명령을 먼저 실행한다. 출력에 표시된 D435i 장치 경로를 확인하고, 도구가 출력한 Docker 생성·시작 명령을 G1 호스트에 입력한다. 이렇게 생성한 컨테이너에서도 ROS 2·DDS 탐색과 나머지 기능을 함께 사용한다.

**G1 호스트 · USB 카메라 구성으로 처음 생성**

```bash
docker run --pull never --rm --runtime=runc --network none --cap-drop ALL --security-opt no-new-privileges:true --entrypoint /usr/local/bin/g1-pc2-create-command g1-jsj:base
```

<a id="shell"></a>

## 각 터미널에서 컨테이너 내부로 들어가기

온도 모니터는 **터미널 1**, 텔레옵은 **터미널 2**, 카메라 탐색·기록은 **터미널 3**을 사용한다. RViz2나 상태 기록을 함께 켤 때는 터미널을 하나 더 연다. **새 G1 터미널마다 다음 한 줄을 먼저 입력한다.** 같은 컨테이너에 셸이 하나씩 열린다. 새 이미지에서 진입 직후 프롬프트는 `[jsj-g1-tools] /workspace#`로 표시된다.

**G1 호스트 · 각 터미널에서 한 번**

```bash
docker exec -it jsj-g1-tools bash
```

**컨테이너 내부 · 사용 명령과 로봇 NIC 확인**

```bash
g1 --help
g1 interfaces
```

이후 예시에서 `eth0`는 원본 온도 모니터가 정상 수신한 로봇용 유선 인터페이스 이름으로 바꾼다.

<a id="monitoring"></a>

## 온도 측정과 키보드 조작

**컨테이너 내부 · 터미널 1 · 온도·배터리 모니터**

```bash
g1 health eth0
```

원본 C++ 모니터는 DDS 도메인 0을 사용한다. 모터·배터리의 최신 샘플과 온도를 확인하고 측정 중에는 이 터미널을 열어 둔다. [관절·IMU 대시보드와 상태 기록](src/g1stairs/monitoring/README.md)

**컨테이너 내부 · 터미널 2 · 실제 상태로 키보드 미리보기**

```bash
g1 teleop --preview --interface eth0 --domain 0
```

시작 시 실제 FSM과 29개 관절의 위치·속도를 읽는다. 이어지는 `[모의]` 화면에서는 시작값이 802이면 바로 `i`, 시작값이 0이나 4이면 `2` → `Enter` → `i`로 전진 요청을 확인한다. `k`는 정지, `Ctrl+C`는 종료다. [보행 전 점검과 기존 컨테이너에서 새 버전 사용](docs/teleop-preflight.md)

**컨테이너 내부 · 터미널 2 · 실제 키보드 조작**

첫 실기체 조작은 숙련자 입회하에 모터·배터리, 기체 지지, 공간, 물리 조종기를 확인한 뒤 시작한다. FSM 802에서는 내장 보행기가 팔을 흔들 수 있다. 팔 고정이 필요한 실험에서는 이 모드를 사용하기 전에 해당 조건을 확인한다.

```bash
g1 teleop --live --interface eth0 --domain 0
```

| 키 | 동작 |
| --- | --- |
| `i` / `,` 또는 `↑` / `↓` | 전진 / 후진 |
| `j` / `l` 또는 `←` / `→` | 제자리 좌회전 / 우회전 |
| `Shift+J` / `Shift+L` | 왼쪽 / 오른쪽 옆걸음 |
| `k` 또는 스페이스 / `Ctrl+C` | 정지 / 종료 |
| `q` / `z` | 다음 이동의 선속도·회전속도 10% 증가 / 감소 |
| `2` → `Enter` / `f` / `?` | FSM 802 요청 / 현재 FSM 조회 / 전체 키 안내 |

키 배치는 ROS 2 `teleop_twist_keyboard`를 따른다. 기체에는 Unitree 고수준 SDK의 `SetVelocity`를 보낸다. `i` 한 번의 기본 전진 요청은 0.15 m/s이고 입력 유효시간은 최대 1초다. 키를 누르고 있으면 키 반복 입력으로 명령이 갱신된다. `SetVelocity(7105) 수락`은 서비스 응답이며 실제 발걸음은 별도로 확인한다. 이 기체에서 작동하지 않은 FSM 500 전환 키는 제거했다. 특히 예전 버전과 달리 **`w`는 선속도 증가, `m`은 후진 선회, `x`는 선속도 감소**다. [전체 배치와 무반응 진단](src/g1_teleop/README.md)

<a id="camera"></a>

## 카메라 토픽 확인과 깊이 기록

발행자, 실제 수신 샘플의 타입과 광학 프레임으로 헤드 D435i 스트림을 식별한다. ROS 2 영상 하나가 ROS 그래프와 DDS 목록에 모두 나타날 수 있다. 아래 NIC와 도메인은 카메라가 연결된 네트워크에 맞춘다. 여러 내부 셸에서 카메라를 쓸 때는 **각 셸에서 같은 두 환경 변수**를 설정한다.

**컨테이너 내부 · 터미널 3 · 카메라 네트워크와 실제 토픽 확인**

```bash
export G1_CAMERA_IFACE=eth0 G1_CAMERA_DOMAIN=0
g1 camera discover --seconds 8
```

| 탐색 결과 | 선택할 도구 |
| --- | --- |
| ROS 2 `sensor_msgs/msg/Image` 실제 수신 | RViz2에서 해당 영상 토픽을 선택한다. |
| 지원되는 `sensor_msgs/msg/CompressedImage` 실제 수신 | 압축 영상을 푸는 명령을 한 터미널에 켜 두고, RViz2에서 `/g1_jsj/view_image`를 선택한다. |
| 네이티브 DDS 카메라 발행자 발견 | TTY에서 해당 토픽과 타입의 샘플을 읽는다. XTypes 정보가 없으면 발행자의 공식 IDL 클래스를 지정한다. |
| D435i가 PC2 USB에 직접 연결됨 | USB 장치를 포함한 컨테이너에서 프로필과 실제 샘플을 확인한다. 이미 장치를 점유한 프로그램이 있으면 해당 프로그램의 영상 토픽을 사용한다. |

**컨테이너 내부 · ROS 영상 보기 · 별도 터미널**

```bash
export G1_CAMERA_IFACE=eth0 G1_CAMERA_DOMAIN=0
g1 camera rviz
```

G1의 브라우저에서 터미널에 출력된 로컬 주소를 열고 **Camera image → Topic**에서 수신 토픽을 선택한다. 센서 QoS는 Best Effort다.

**컨테이너 내부 · 압축 영상인 경우에만 · 터미널 3**

```bash
read -rp '탐색한 압축 영상 토픽 이름: ' IMAGE_TOPIC
g1 camera compressed-view "$IMAGE_TOPIC"
```

**컨테이너 내부 · 네이티브 DDS인 경우 · 터미널 3**

```bash
read -rp 'DDS 카메라 발행 행의 topic: ' DDS_TOPIC
read -rp '같은 행의 type: ' DDS_TYPE
g1 camera tty-dds --topic "$DDS_TOPIC" --type "$DDS_TYPE" --seconds 5
```

**컨테이너 내부 · USB 직접 연결인 경우 · 터미널 3**

```bash
g1 camera probe-usb
g1 camera tty-usb --seconds 5
```

### 깊이와 기체 상태 기록

계단 촬영 전 기체를 보정 때와 같은 자세로 정지시킨다. 한 실험에는 ROS 2와 USB 중 한 경로로 깊이를 기록한다. 아래 예시의 `stairs-01`을 새 실험마다 고유한 이름으로 바꾸고, 해당 실험의 다른 셸에서도 같은 이름을 사용한다.

**컨테이너 내부 · 터미널 3 · ROS 2 깊이 기록을 선택한 경우**

```bash
RUN_ID=stairs-01
read -rp '16UC1 원시 깊이 영상 토픽: ' DEPTH_TOPIC
read -rp '같은 촬영 시각·광학 프레임의 CameraInfo 토픽: ' INFO_TOPIC
read -rp '발행자에서 확인한 깊이 1단위당 미터: ' DEPTH_SCALE
g1 camera record-ros --run "$RUN_ID" --seconds 10 --depth-topic "$DEPTH_TOPIC" --info-topic "$INFO_TOPIC" --depth-scale-m "$DEPTH_SCALE"
```

**컨테이너 내부 · 터미널 3 · USB 깊이 기록을 선택한 경우**

```bash
RUN_ID=stairs-01
g1 camera record --run "$RUN_ID" --seconds 10
```

USB 기본 프로필은 640×480, 60 Hz, Z16이다. `probe-usb`에서 지원을 확인한 프로필을 사용한다. 깊이 단위는 RealSense SDK가 장치에서 읽는다.

**컨테이너 내부 · 별도 터미널 · 같은 10초 동안 기체 상태도 기록할 경우**

```bash
RUN_ID=stairs-01
g1 monitor record --nic eth0 --domain 0 --run "$RUN_ID" --seconds 10
```

<a id="geometry"></a>

## 같은 기록으로 계단 높이·디딤면 깊이·폭 계산

실험 디렉터리 `/workspace/runs/stairs-01/`의 `depth/`에 깊이, `state/`에 상태, `geometry/`에 계산 결과가 저장된다. 깊이 기록을 마친 터미널에서 같은 `RUN_ID`로 진행한다. 새 내부 셸을 열었다면 그 셸에서 `RUN_ID=stairs-01`을 실제 기록 이름으로 다시 설정한다.

광학 좌표를 **앞·왼쪽·위** 기준으로 바꾸려면 실측 회전·이동이 필요하다. `source_frame`은 깊이 기록의 `frame_id`와 맞아야 한다. 기체 자세나 센서 장착이 바뀌면 다시 보정한다. 다음 명령이 입력을 기다리면 실측 JSON을 붙여넣고 새 줄에서 Ctrl+D를 누른다. 이미 같은 실험에 저장한 보정 파일이 있으면 파일 입력을 건너뛴다. [보정 JSON 형식](config/calibration.example.json)

**컨테이너 내부 · 실측 보정 파일을 처음 저장할 때**

```bash
CAL="/workspace/runs/$RUN_ID/measured-calibration.json"
python3 -c '
import json, sys
from g1stairs.geometry.projection import Calibration
data = json.load(sys.stdin)
Calibration.from_mapping(data)
with open(sys.argv[1], "x") as f:
    json.dump(data, f)
' "$CAL"
```

**컨테이너 내부 · 보정한 깊이로 계단 계산과 결과 확인**

```bash
g1 stairs measure --run "$RUN_ID" --calibration "/workspace/runs/$RUN_ID/measured-calibration.json"
head -n 1 "/workspace/runs/$RUN_ID/geometry/stairs.jsonl"
```

기록 때 `--calibration`을 제공했다면 측정 단계에서 보정 인자를 생략할 수 있다. 기본은 첫 프레임이며 전체는 `--all-frames`다. `riser_height_m`, `tread_depth_m`, `width_m`는 미터 단위다. 양쪽 경계가 보이지 않아 폭을 결정할 수 없으면 `width_m`은 `null`이다.

<a id="sdk"></a>

## 기능별 디렉터리와 공식 SDK

| 디렉터리 | 역할과 사용 API |
| --- | --- |
| [src/g1_health_monitor](src/g1_health_monitor/) | 동작을 확인한 연구실 C++ 소스·CMake를 사용한다. Unitree SDK2의 `ChannelSubscriber`, `LowState_`, `BmsState_`로 모터·배터리 상태를 수신한다. [공식 C++ SDK](https://github.com/unitreerobotics/unitree_sdk2/tree/aaf69cb56c9d5ed63d8b284008ec3a8ab999bec1) |
| [src/g1_teleop](src/g1_teleop/) | 공식 Python `LocoClient`의 `GetFsmId`, `SetFsmId`, `SetBalanceMode`, `SetVelocity`, `SetSpeedMode`를 호출하는 키보드 입력기. [공식 Python SDK](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/unitree_sdk2py/g1/loco/g1_loco_client.py) |
| [src/g1stairs/monitoring](src/g1stairs/monitoring/) | Unitree SDK2 Python 상태 구독, 기록, 웹 대시보드 |
| [src/g1stairs/camera](src/g1stairs/camera/) | USB는 RealSense SDK 2.0(`pyrealsense2`), ROS 영상은 Foxy `rclpy`와 `sensor_msgs`, DDS 진단은 Eclipse Cyclone DDS. [Unitree 카메라 가이드](https://support.unitree.com/home/en/G1_developer/depth_camera_instruction) · [ROS 2 CameraInfo](https://github.com/ros2/common_interfaces/blob/foxy/sensor_msgs/msg/CameraInfo.msg) |
| [src/g1stairs/geometry](src/g1stairs/geometry/) | 공식 RealSense SDK의 역투영으로 미터 단위 3D 좌표를 구한 뒤, 프로젝트 알고리즘이 수평면과 관측된 경계를 찾아 계단 치수를 계산한다. [RealSense 좌표 변환](https://github.com/realsenseai/librealsense/wiki/Projection-in-RealSense-SDK-2.0) |
| [config](config/) · [docker/base](docker/base/) · [docker/tools](docker/tools/) | 보정 형식, 전체 운영 이미지를 빌드하는 Dockerfile, CLI·USB 장치 선택 스크립트 |

`g1-jsj:base`에는 공식 C++ SDK `aaf69cb`, Python SDK `814556d`, Unitree ROS 2 메시지 `668d1ec`, Foxy Cyclone RMW `c12abc5`와 Cyclone DDS `0.10.2`가 들어간다. 빌드할 때 RealSense Python SDK `2.54.1.5217`의 ARM64 배포 파일을 해시로 확인한다. [Unitree ROS 2](https://github.com/unitreerobotics/unitree_ros2/tree/668d1ec5a05d1c38d3306bdca7d59f2ba3581a88) · [Cyclone DDS](https://github.com/eclipse-cyclonedds/cyclonedds/tree/0.10.2)

PC2에서 이미지 설치 후 회귀 테스트는 아래 명령으로 실행한다. 테스트는 실제 보행 명령을 보내지 않는다. 물리 카메라 수신 여부와 계단 치수 정확도는 해당 기체의 프레임과 계단 실측으로 확인한다.

**컨테이너 내부 · 회귀 테스트**

```bash
python3 -m unittest discover -s /opt/g1-tools -t /opt/g1-tools
```

<a id="resume"></a>

## 기존 컨테이너 재개와 기록 보관

다음 실험을 재개하거나 이미지를 새로 빌드했다면 먼저 확인한다. 컨테이너는 생성 당시의 이미지 ID를 계속 사용한다.

**G1 호스트 · 현재 이미지 ID와 기존 컨테이너의 실제 이미지 ID 비교**

```bash
docker image inspect --format '{{.Id}}' g1-jsj:base
docker container inspect --format '{{.Image}} {{.Name}} {{.Config.Image}} {{index .Config.Labels "org.iic.g1.role"}} {{.State.Status}}' jsj-g1-tools
```

두 줄의 첫 번째 값(`sha256:…`)이 같고, 두 번째 줄이 본인의 `/jsj-g1-tools`, `g1-jsj:base`, `operator-tools`이면 이어서 사용한다. ID가 다르거나 예전 `jsj-g1-tools:foxy`로 만든 컨테이너면 먼저 기존 기록을 보관한 뒤 새 이미지로 다시 생성한다. [기존 실험 보관·가져오기](docs/previous-runs.md)

**G1 호스트 · 확인한 컨테이너 재개** (상태가 `running`이면 둘째 줄만 입력)

```bash
docker start jsj-g1-tools
docker exec -it jsj-g1-tools bash
```

**컨테이너 내부 · 보관된 실험 이름 확인**

```bash
ls /workspace/runs
```

같은 컨테이너를 다시 시작하면 쓰기 레이어의 기록이 유지된다. **새 이미지나 변경된 USB 장치 경로로 다시 생성할 때**는 기존 컨테이너를 보관하고 새 컨테이너로 필요한 기록을 가져온다. 이전 기능별 컨테이너에 남은 기록도 이 절차로 가져올 수 있다. [기존 실험 보관·가져오기](docs/previous-runs.md)

### 실험 종료

텔레옵에서 `k`로 속도 0을 요청하고 `Ctrl+C`로 종료한다. 카메라와 상태 녹화가 끝났는지 확인하고 열어 둔 뷰어나 모니터는 각 터미널에서 Ctrl+C로 끝낸다.

**컨테이너 내부 · 해당 셸에서 나가기**

```bash
exit
```

**G1 호스트 · 실험을 모두 마친 뒤 정지**

```bash
docker stop jsj-g1-tools
```
