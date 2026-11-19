# G1 EDU loco 실행 가이드

처음 설정할 때는 G1-EDU의 **PC2에서 공통 베이스 이미지부터 빌드**합니다. 보행과 카메라는 필요한 이미지만 추가합니다. [IIC 절대규칙](AGENTS.md)

| 원하는 작업 | PC2에서 실행할 순서 |
| --- | --- |
| 연구실 C++ 배터리·모터 온도 모니터와 키보드 보행 | [PC2 빌드, 상태 조회와 조작 키](g1_teleop/README.md) |
| 외부 PC에서 전신 관절·모터 온도 보기 | [1. 베이스 빌드](#pc2) → [2. 모니터링](#monitoring) |
| 헤드 D435i의 실제 깊이 영상 기록 | [1. 베이스 빌드](#pc2) → [3. 카메라](#camera) |
| 촬영한 계단의 높이·디딤면 깊이·폭 측정 | [1. 베이스 빌드](#pc2) → [3. 카메라 기록](#camera) → [4. 계단 측정](#geometry) |

<a id="pc2"></a>

## 1. PC2에서 공통 베이스 이미지 만들기

G1-EDU 개발 보드 **PC2**에 SSH로 접속해 [공통 CPU 이미지 빌드 명령](docker/base/README.md)을 실행하세요. 이 단계에서 `g1-jsj:base` 한 개를 만듭니다. Docker가 공개 Git 브랜치의 소스를 받아 Ubuntu 20.04 ARM64, ROS 2 Foxy, Cyclone DDS 0.10.2와 Unitree SDK2를 로컬에서 빌드합니다. 같은 안내의 버전·NIC 확인 명령으로 결과를 확인하세요.

<a id="monitoring"></a>

## 2. 전신 모니터링

IIC에서 사용하던 **터미널 배터리·모터 온도 모니터**는 [원본 그대로 가져온 g1_health_monitor](g1_health_monitor/)입니다. PC2에서의 빌드와 실행은 [키보드 원격조종·상태 모니터 안내](g1_teleop/README.md)를 따르세요. 아래는 웹으로 관절과 IMU도 볼 때 사용하는 별도의 대시보드입니다.

**① 컨테이너 생성·시작 및 코드 다운로드**. 다음 실험에서도 이 블록을 그대로 사용하면 됩니다.

```bash
(
  set -e
  if docker container inspect jsj-monitor >/dev/null 2>&1; then
    [[ "$(docker inspect -f '{{.Config.Image}}' jsj-monitor)" =~ ^(g1-jsj:base|jsj-g1-base:foxy)$ ]] || {
      echo '같은 이름의 컨테이너가 다른 이미지를 사용합니다.' >&2
      exit 1
    }
    settings=$(docker inspect -f '{{len .Mounts}} {{.HostConfig.Privileged}} {{.HostConfig.NetworkMode}}' jsj-monitor)
    [[ $settings == '0 false host' ]] || {
      echo '기존 컨테이너의 마운트·권한·네트워크 설정을 확인하세요. 데이터를 보존하기 위해 시작을 중단합니다.' >&2
      exit 1
    }
    docker start jsj-monitor >/dev/null
  else
    docker run -d --name jsj-monitor --pull never --runtime=runc --platform linux/arm64 \
      --network host --ipc private --cap-drop ALL --security-opt no-new-privileges:true \
      g1-jsj:base sleep infinity
  fi
  docker exec jsj-monitor bash -ec '
    repo=/opt/g1-edu-loco
    if [[ ! -d "$repo/.git" ]]; then
      git clone --branch jsj --single-branch --sparse https://github.com/tokengeoji/g1-edu-loco.git "$repo"
    fi
    cd "$repo"
    if [[ ! -f g1stairs/monitoring/__main__.py ]]; then
      git sparse-checkout init --cone
      git sparse-checkout set g1stairs/monitoring
    fi
    git fetch origin jsj:refs/remotes/origin/jsj
    git switch jsj || git switch --track origin/jsj
    git merge --ff-only origin/jsj
    git rev-parse --short HEAD
  '
)
```

**② PC2에서 모니터링 서버를 실행하고 외부 PC에서 GUI 열기**

**PC2에서** 아래 블록을 실행합니다. 표시되는 주소 중 외부 PC에서 PC2에 접속할 때 쓰는 LAN 주소를 입력하세요. 이미 서버가 떠 있으면 그 터미널에서 `Ctrl+C`로 종료한 뒤 실행하세요.

```bash
(
  set -e
  docker exec jsj-monitor ip -brief -4 address show up
  read -rp '외부 PC에서 접속할 PC2의 LAN IPv4 주소 (/24 제외): ' pc2_ip
  [[ -n "$pc2_ip" ]] || exit 1
  docker exec -it -w /opt/g1-edu-loco jsj-monitor bash -ec \
    'exec python3 -m g1stairs.monitoring serve --bind "$1"' _ "$pc2_ip"
)
```

**외부 PC에서** 같은 연구실 네트워크에 연결한 뒤 브라우저로 PC2 터미널의 `Monitoring dashboard at` 뒤에 출력된 URL을 여세요. 주소 형식은 `http://<PC2의 LAN IP>:8765/`입니다. 외부 PC에는 Python이나 Unitree SDK를 설치할 필요가 없습니다. 페이지의 `waiting`은 웹 연결에 성공했고 아직 `rt/lowstate` 첫 샘플을 기다린다는 뜻입니다. 실제 샘플을 받으면 다리 12축·허리 3축·팔 14축과 IMU가 표시됩니다.

**③ 기록이 필요할 때만** 별도 PC2 터미널에서 실행합니다. 기본 10초간 기록한 후 실제 세션 이름을 출력합니다. [모니터링 필드·SDK 기본 설정](g1stairs/monitoring/README.md)

```bash
STATE_RUN_ID=$(docker exec jsj-monitor date -u +state-%Y%m%dT%H%M%SZ)
docker exec -w /opt/g1-edu-loco jsj-monitor bash -ec \
  'python3 -m g1stairs.monitoring record --run "$1" --runs-dir /workspace/jsj-monitor/runs' _ "$STATE_RUN_ID"
```

<a id="camera"></a>

## 3. D435i 카메라

Unitree의 `Depth Camera Routine`은 개발 보드의 D435i를 librealsense로 열거나 ROS 카메라 드라이버로 발행하는 방법을 설명합니다. 기체에서 현재 실행 중인 발행자는 현장에서 확인합니다. ROS 2 역시 DDS를 사용하므로 같은 ROS 영상 스트림이 ROS 그래프와 DDS 발행 목록에 함께 나타날 수 있습니다. [Unitree Depth Camera Routine](https://support.unitree.com/home/en/G1_developer/depth_camera_instruction)

공통 베이스를 만든 뒤 PC2 SSH 터미널에서 카메라 이미지를 빌드합니다. 같은 명령을 다시 실행하면 Docker가 현재 `jsj` 브랜치로 빌드합니다.

```bash
docker image inspect g1-jsj:base >/dev/null &&
docker build --pull=false --platform linux/arm64 -f docker/camera/Dockerfile \
  -t g1-jsj:realsense 'https://github.com/tokengeoji/g1-edu-loco.git#jsj'
```

아래 함수를 카메라 작업용 PC2 Bash 터미널마다 한 번 정의합니다. 실행할 때 로컬에 빌드한 이미지에서 명령을 읽습니다. 녹화 파일과 프로그램은 컨테이너 안에 저장됩니다.

```bash
g1cam() (
  local camera_commands
  camera_commands=$(docker run --pull never --rm --name "jsj-camera-cli-$BASHPID" --runtime=runc --network none \
    --cap-drop ALL --security-opt no-new-privileges:true g1-jsj:realsense cat /opt/g1/pc2.sh) || exit 1
  eval "$camera_commands"
)
g1cam interfaces
read -rp '로봇 네트워크 NIC: ' G1_CAMERA_IFACE
g1cam discover --seconds 8
```

기본 DDS 도메인은 현재 셸의 `ROS_DOMAIN_ID`, 미설정이면 0입니다. 발행자가 다른 도메인에 있으면 `G1_CAMERA_DOMAIN`을 지정하고 다시 탐색하세요. 탐색은 임시 컨테이너에서 실행됩니다. 녹화할 때 생성하는 컨테이너 이름은 `jsj-realsense`입니다. 이전 이름의 호환되는 컨테이너가 있으면 재사용하며 `g1cam name`이 현재 이름을 표시합니다.

| 실제 출력 | PC2에서 확인하는 방법 |
|---|---|
| `ros_images`의 `sensor_msgs/msg/Image`에서 `samples_received > 0` | PC2에서 `g1cam rviz`를 실행합니다. 브라우저에 표시된 RViz의 **Camera image → Topic**에서 그 토픽을 선택합니다. Reliability Policy는 Best Effort입니다. |
| `sensor_msgs/msg/CompressedImage`에서 샘플 수신 | JPEG/PNG 또는 Foxy compressedDepth PNG이면 아래 변환을 별도 터미널에서 실행하고 RViz에서 `/g1_jsj/view_image`를 선택합니다. |
| `dds_publications`에서 카메라 발행자가 사용하는 DDS 토픽·타입을 확인 | 아래 `tty-dds`로 실제 샘플을 읽습니다. 영상 바이트는 길이로, 숫자 필드는 값으로 표시합니다. XTypes를 제공하지 않는 발행자는 동일한 Python IDL 클래스가 필요합니다. |
| `NO_CONFIRMED_ROS_IMAGE` 또는 카메라 DDS 타입이 불명확함 | 도메인·NIC·발행 프로그램을 확인합니다. USB D435i가 PC2에 있고 다른 프로그램이 장치를 점유하지 않을 때는 `probe-usb`와 `tty-usb`를 사용합니다. |

`frame_id`, 인코딩, 발행 노드를 센서 설정과 대조해 **헤드 D435i의 깊이**인지 확인하세요. 같은 네트워크의 다른 카메라도 목록에 포함될 수 있습니다. `16UC1`과 `32FC1`은 깊이에 사용할 수 있는 픽셀 형식입니다. 토픽 이름이나 픽셀 형식만으로 센서 또는 미터 환산 단위를 정할 수 없습니다.

```bash
# ROS 2 압축 영상. TOPIC에 실제 수신한 CompressedImage 토픽을 입력합니다.
read -rp 'CompressedImage topic: ' TOPIC
g1cam compressed-view "$TOPIC"

# 네이티브 DDS. 발견 결과와 발행자 문서에서 확인한 정확한 이름을 사용합니다.
read -rp 'DDS topic: ' TOPIC
read -rp 'DDS type: ' TYPE
g1cam tty-dds --topic "$TOPIC" --type "$TYPE" --seconds 8

# USB 직접 확인. probe는 장치와 지원 프로필을 읽고, tty-usb가 스트림을 엽니다.
g1cam probe-usb
g1cam tty-usb --seconds 5
```

**PC2에서 RViz2로 보기.** 탐색을 실행한 터미널에서 아래 명령을 실행합니다. RViz2와 가상 디스플레이가 별도 CPU 컨테이너에서 시작됩니다. 뷰어만 미리 점검하려면 `g1cam rviz --self-test`를 실행하세요. RViz 창, noVNC 페이지, VNC 연결을 확인하고 종료합니다.

```bash
g1cam rviz
```

PC2 브라우저에서 터미널에 출력된 `http://127.0.0.1:6080/vnc.html` 주소를 열고 이번 세션의 VNC 암호를 입력하세요. RViz 왼쪽 **Camera image → Topic**에서 실제 영상 토픽을 선택합니다. 웹과 VNC는 PC2의 루프백에서만 듣습니다. 포트가 사용 중이면 `G1_RVIZ_PORT=6081 g1cam rviz`처럼 포트를 바꿀 수 있습니다. 터미널에서 `Ctrl+C`를 누르면 뷰어가 종료됩니다.

PC2가 헤드리스이면 SSH 클라이언트에서 로컬 포트 6080을 PC2의 `127.0.0.1:6080`으로 포워딩하여 브라우저로 같은 화면을 열 수 있습니다. 이미 ROS 2 Foxy·RViz2가 있는 워크스테이션은 같은 로봇 LAN과 DDS 도메인으로 연결한 뒤 `rviz2`의 **Add → Image**에서 같은 토픽을 선택할 수도 있습니다.

USB는 공식 예제의 `640×480, 60 FPS, Z16`을 기본으로 사용합니다. `probe-usb` 출력에 따라 `--width`, `--height`, `--fps`를 바꿀 수 있습니다. `DEVICE_BUSY`가 뜨면 현재 장치를 여는 발행자를 확인하세요.

### 깊이 기록

보정된 `16UC1` 깊이 프레임과 같은 촬영 시각의 `sensor_msgs/msg/CameraInfo`가 발행되고 있을 때 PC2에서 실행합니다. 단위는 발행자 설정에 맞게 입력하세요.

```bash
RUN_ID=$(docker run --pull never --rm --name "jsj-camera-clock-$BASHPID" --runtime=runc --network none g1-jsj:realsense date -u +stairs-%Y%m%dT%H%M%SZ)
read -rp 'Depth Image topic: ' depth_topic
read -rp 'CameraInfo topic: ' info_topic
read -rp 'Metres per stored depth unit: ' depth_unit
g1cam record-ros --depth-topic "$depth_topic" --info-topic "$info_topic" \
  --depth-scale-m "$depth_unit" --run "$RUN_ID" --runs-dir /workspace/jsj-camera/runs
```

USB로 직접 기록할 실험은 컨테이너를 처음 만들 때 `g1cam start --usb`로 D435i를 연결합니다. 이후 아래 명령을 사용하세요. 관측만 필요한 `tty-usb`는 기존 컨테이너의 USB 설정과 관계없이 실행됩니다.

```bash
RUN_ID=$(docker run --pull never --rm --name "jsj-camera-clock-$BASHPID" --runtime=runc --network none g1-jsj:realsense date -u +stairs-%Y%m%dT%H%M%SZ)
docker exec "$(g1cam name)" python3 -m g1stairs.camera record \
  --run "$RUN_ID" --runs-dir /workspace/jsj-camera/runs --seconds 10
```

<a id="geometry"></a>

## 4. 촬영한 계단 치수 측정

**① 분석 컨테이너 준비 및 코드 다운로드**.

```bash
(
  set -e
  if docker container inspect jsj-footstep-workbench >/dev/null 2>&1; then
    [[ "$(docker inspect -f '{{.Config.Image}}' jsj-footstep-workbench)" =~ ^(g1-jsj:base|jsj-g1-base:foxy)$ ]] || {
      echo '같은 이름의 컨테이너가 다른 이미지를 사용합니다.' >&2
      exit 1
    }
    settings=$(docker inspect -f '{{len .Mounts}} {{.HostConfig.Privileged}} {{.HostConfig.NetworkMode}}' jsj-footstep-workbench)
    [[ $settings == '0 false bridge' ]] || {
      echo '기존 컨테이너의 마운트·권한·네트워크 설정을 확인하세요. 데이터를 보존하기 위해 시작을 중단합니다.' >&2
      exit 1
    }
    docker start jsj-footstep-workbench >/dev/null
  else
    docker run -d --name jsj-footstep-workbench --pull never --runtime=runc --platform linux/arm64 \
      --network bridge --ipc private --cap-drop ALL --security-opt no-new-privileges:true \
      g1-jsj:base sleep infinity
  fi
  docker exec jsj-footstep-workbench bash -ec '
    repo=/opt/g1-edu-loco
    if [[ ! -d "$repo/.git" ]]; then
      git clone --branch jsj --single-branch --sparse https://github.com/tokengeoji/g1-edu-loco.git "$repo"
    fi
    cd "$repo"
    if [[ ! -f g1stairs/geometry/__main__.py ]]; then
      git sparse-checkout init --cone
      git sparse-checkout set g1stairs/geometry config
    fi
    git fetch origin jsj:refs/remotes/origin/jsj
    git switch jsj || git switch --track origin/jsj
    git merge --ff-only origin/jsj
    git rev-parse --short HEAD
  '
) &&
docker exec jsj-footstep-workbench bash -ec '
  if ! python3 -c "import pyrealsense2" 2>/dev/null; then
    python3 -m pip install --user --no-cache-dir --only-binary=:all: --no-deps pyrealsense2==2.54.1.5217
  fi
  python3 -c "import pyrealsense2 as rs; print(rs.__file__)"
'
```

**② 기록 전달 및 측정**. 녹화에 썼던 PC2 터미널이면 같은 `RUN_ID`를 사용합니다. 새 터미널이면 카메라 절의 `g1cam` 함수를 먼저 정의하세요. 완료된 기록 목록이 나오고 실험 이름을 입력할 수 있습니다. 보정이 기록에 포함돼 있으면 바로 계산합니다. 보정이 없으면 **촬영 자세에서 실측한 보정 JSON**을 입력하라는 안내가 나옵니다. `rotation`과 `translation_m`은 카메라 광학 좌표에서 중력 정렬 좌표로의 변환입니다. [JSON 필드 예시](config/calibration.example.json)의 숫자는 형식 설명용입니다.

```bash
(
  set -euo pipefail
  camera=$(g1cam name)
  if [[ -z "${RUN_ID:-}" ]]; then
    docker exec "$camera" bash -c 'cd /workspace/jsj-camera/runs && ls -d */depth/manifest.json'
    read -rp '분석할 실험 이름: ' RUN_ID
  fi
  [[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]] || { echo '실험 이름을 확인하세요.' >&2; exit 1; }
  src="/workspace/jsj-camera/runs/$RUN_ID"
  dst="/workspace/jsj-footstep-workbench/runs/$RUN_ID"
  docker exec "$camera" test -s "$src/depth/manifest.json"
  docker exec jsj-footstep-workbench mkdir -p "$dst"
  if ! docker exec jsj-footstep-workbench test -e "$dst/depth"; then
    tmp=$(docker exec jsj-footstep-workbench mktemp -d "$dst/.incoming-XXXXXX")
    docker exec "$camera" tar -C "$src" -cf - depth \
      | docker exec -i jsj-footstep-workbench tar --no-same-owner -C "$tmp" -xf -
    docker exec jsj-footstep-workbench test -s "$tmp/depth/manifest.json"
    docker exec jsj-footstep-workbench mv -Tn "$tmp/depth" "$dst/depth"
    docker exec jsj-footstep-workbench rmdir "$tmp"
  fi
  docker exec jsj-footstep-workbench test -s "$dst/depth/manifest.json"

  cal="$dst/depth/calibration.json"
  if ! docker exec jsj-footstep-workbench test -s "$cal"; then
    cal="$dst/measured-calibration.json"
    if ! docker exec jsj-footstep-workbench test -s "$cal"; then
      echo '이 촬영 자세의 실측 보정 JSON을 붙여넣고 새 줄에서 Ctrl+D를 누르세요.'
      docker exec -i -w /opt/g1-edu-loco jsj-footstep-workbench python3 -c '
import json, sys
from g1stairs.geometry.projection import Calibration
data = json.load(sys.stdin)
Calibration.from_mapping(data)
with open(sys.argv[1], "x") as stream:
    json.dump(data, stream)
' "$cal"
    fi
  fi
  if ! docker exec jsj-footstep-workbench test -s "$dst/geometry/manifest.json"; then
    docker exec -w /opt/g1-edu-loco jsj-footstep-workbench bash -c \
      'python3 -m g1stairs.geometry measure --run "$1" --runs-dir /workspace/jsj-footstep-workbench/runs --calibration "$2"' _ "$RUN_ID" "$cal"
  fi
  docker exec jsj-footstep-workbench head -n 1 "$dst/geometry/stairs.jsonl"
)
```

결과의 `riser_height_m`, `tread_depth_m`, `width_m`을 실제 계단 실측값과 비교하세요. 기본 측정 대상은 첫 프레임이며, 관측되지 않은 경계의 치수는 `null`로 남습니다. [RealSense SDK 역투영](https://dev.realsenseai.com/docs/projection-in-realsense-sdk-2-0/)

<a id="resume"></a>

## 다음 실험 및 종료

GUI를 끝내려면 실행 터미널에서 `Ctrl+C`를 누릅니다. 컨테이너까지 정지하려면 아래에서 해당 기능의 명령 한 줄을 사용하세요. 다음에는 기능별 **① 준비 블록**을 다시 붙여넣으면 컨테이너 시작과 코드 갱신이 함께 이루어집니다.

```bash
g1stop() {
  local name=$1 network image settings
  case "$name" in
    jsj-monitor) network=host ;;
    jsj-footstep-workbench) network=bridge ;;
    jsj-realsense|g1-jsj-realsense) network=host ;;
    *) return 2 ;;
  esac
  image=$(docker inspect --type container -f '{{.Config.Image}}' "$name") || return 1
  case "$name:$image" in
    jsj-monitor:g1-jsj:base|jsj-monitor:jsj-g1-base:foxy|jsj-footstep-workbench:g1-jsj:base|jsj-footstep-workbench:jsj-g1-base:foxy|jsj-realsense:g1-jsj:realsense|g1-jsj-realsense:g1-jsj:realsense) ;;
    *) echo '이름과 이미지가 일치하지 않아 중단합니다.' >&2; return 1 ;;
  esac
  settings=$(docker inspect -f '{{len .Mounts}} {{.HostConfig.Privileged}} {{.HostConfig.NetworkMode}} {{json .Config.Cmd}}' "$name") || return 1
  [[ $settings == "0 false $network [\"sleep\",\"infinity\"]" ]] || {
    echo '설정이 예상과 달라 중단합니다.' >&2
    return 1
  }
  docker stop "$name"
}
# 정지할 작업에 해당하는 줄만 실행합니다.
g1stop jsj-monitor
g1stop "$(g1cam name)"
g1stop jsj-footstep-workbench
```

PC2에서의 실제 빌드, DDS·D435i 수신, 계단 실측 비교는 현장 확인 항목입니다.
