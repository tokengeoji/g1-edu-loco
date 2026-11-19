# G1 EDU loco 실행 가이드

처음 설정할 때는 **공통 베이스 이미지부터 빌드**합니다. RealSense 카메라 이미지는 카메라 프로그램을 포함합니다.

| 원하는 작업 | PC2에서 실행할 순서 |
| --- | --- |
| 외부 PC에서 전신 관절·모터 온도 보기 | [1. 베이스 빌드](#pc2) → [2. 모니터링](#monitoring) |
| 헤드 D435i의 실제 깊이 영상 기록 | [1. 베이스 빌드](#pc2) → [3. 카메라](#camera) |
| 촬영한 계단의 높이·디딤면 깊이·폭 측정 | [1. 베이스 빌드](#pc2) → [3. 카메라 기록](#camera) → [4. 계단 측정](#geometry) |

<a id="pc2"></a>

## 1. PC2에서 공통 베이스 이미지 만들기

G1-EDU의 개발 보드 **PC2**에서 실행합니다. `g1-jsj:base`에는 Ubuntu 20.04 ARM64, Python 3.8, ROS 2 Foxy, Cyclone DDS 0.10.2, Foxy용 `rmw_cyclonedds_cpp`와 Unitree SDK2가 들어갑니다. `g1-jsj:realsense`는 여기에 RealSense SDK, RViz2와 카메라 프로그램을 추가한 CPU 이미지입니다. PC2에서 GitHub와 Ubuntu·ROS 패키지 서버에 접근할 수 있어야 합니다. [공통 베이스 구성](docker/base/README.md)

PC2에 이미 Git이 있으면 개인 작업 폴더에서 실행하세요. 기존 체크아웃은 `jsj` 브랜치에서 `git pull --ff-only` 후 같은 빌드 명령을 사용합니다.

```bash
git clone --single-branch --branch jsj https://github.com/tokengeoji/g1-edu-loco.git g1-jsj-camera
cd g1-jsj-camera
bash docker/camera/pc2.sh build
bash docker/camera/pc2.sh discover --seconds 8
```

호스트에 체크아웃을 놓지 않을 때는 아래 함수를 PC2 Bash에 정의하고 `g1cam build`, `g1cam discover --seconds 8`을 실행합니다. 이 경로에서는 Docker가 공개 Git 저장소의 `jsj` 브랜치를 빌드 컨텍스트로 사용합니다.

```bash
g1cam() {
  local script
  script=$(curl -fsSL https://raw.githubusercontent.com/tokengeoji/g1-edu-loco/jsj/docker/camera/pc2.sh) &&
    bash -c "$script" g1cam "$@"
}
```

메시지 탐색과 터미널 확인 방법은 [카메라 실행 안내](#camera)에 있습니다.

<a id="monitoring"></a>

## 2. 전신 모니터링

**① 컨테이너 생성·시작 및 코드 다운로드**. 다음 실험에서도 이 블록을 그대로 사용하면 됩니다.

```bash
(
  set -e
  if docker container inspect jsj-monitor >/dev/null 2>&1; then
    [[ "$(docker inspect -f '{{.Config.Image}}' jsj-monitor)" =~ ^(g1-jsj:base|jsj-g1-base:foxy)$ ]] || {
      echo '같은 이름의 컨테이너가 다른 이미지를 사용합니다.' >&2
      exit 1
    }
    docker start jsj-monitor >/dev/null
  else
    docker run -d --name jsj-monitor --pull never --platform linux/arm64 \
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
  ip -brief -4 address show up
  read -rp '외부 PC에서 접속할 PC2의 LAN IPv4 주소 (/24 제외): ' pc2_ip
  [[ -n "$pc2_ip" ]] || exit 1
  docker exec -it -w /opt/g1-edu-loco jsj-monitor bash -ec \
    'exec python3 -m g1stairs.monitoring serve --bind "$1"' _ "$pc2_ip"
)
```

**외부 PC에서** 같은 연구실 네트워크에 연결한 뒤 브라우저로 PC2 터미널의 `Monitoring dashboard at` 뒤에 출력된 URL을 여세요. 주소 형식은 `http://<PC2의 LAN IP>:8765/`입니다. 외부 PC에는 Python이나 Unitree SDK를 설치할 필요가 없습니다. 페이지의 `waiting`은 웹 연결에 성공했고 아직 `rt/lowstate` 첫 샘플을 기다린다는 뜻입니다. 실제 샘플을 받으면 다리 12축·허리 3축·팔 14축과 IMU가 표시됩니다.

**③ 기록이 필요할 때만** 별도 PC2 터미널에서 실행합니다. 기본 10초간 기록한 후 실제 세션 이름을 출력합니다. [모니터링 필드·SDK 기본 설정](g1stairs/monitoring/README.md)

```bash
STATE_RUN_ID="state-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -w /opt/g1-edu-loco jsj-monitor bash -ec \
  'python3 -m g1stairs.monitoring record --run "$1" --runs-dir /workspace/jsj-monitor/runs' _ "$STATE_RUN_ID"
```

<a id="camera"></a>

## 3. D435i 카메라

Unitree의 `Depth Camera Routine`은 개발 보드의 D435i를 librealsense로 열거나 ROS 카메라 드라이버로 발행하는 방법을 설명합니다. 기체에서 현재 실행 중인 발행자는 현장에서 확인합니다. ROS 2 역시 DDS를 사용하므로 같은 ROS 영상 스트림이 ROS 그래프와 DDS 발행 목록에 함께 나타날 수 있습니다. [Unitree Depth Camera Routine](https://support.unitree.com/home/en/G1_developer/depth_camera_instruction)

```bash
bash docker/camera/pc2.sh discover --seconds 8
```

이 명령은 `g1-jsj-realsense` 컨테이너를 생성하거나 다시 시작합니다. 기본 도메인은 현재 셸의 `ROS_DOMAIN_ID`(미설정 시 0)입니다. 발행자의 도메인이 다르면 `G1_CAMERA_DOMAIN`으로 지정하세요. NIC가 여러 개라면 `ip -br -4 addr`로 확인한 로봇 네트워크 인터페이스명을 `G1_CAMERA_IFACE`에 지정한 뒤 같은 명령을 반복하세요.

| 실제 출력 | PC2에서 확인하는 방법 |
|---|---|
| `ros_images`의 `sensor_msgs/msg/Image`에서 `samples_received > 0` | 그래픽 터미널에서 `bash docker/camera/pc2.sh rviz`. RViz 왼쪽 **Camera image → Topic**에서 해당 이름을 선택합니다. 센서 QoS는 Best Effort로 설정되어 있습니다. |
| `sensor_msgs/msg/CompressedImage`에서 샘플 수신 | JPEG/PNG 또는 Foxy compressedDepth PNG이면 아래 변환을 별도 터미널에서 실행하고 RViz에서 `/g1_jsj/view_image`를 선택합니다. |
| `dds_publications`에서 카메라 발행자가 사용하는 DDS 토픽·타입을 확인 | 아래 `tty-dds`로 실제 샘플을 읽습니다. 영상 바이트는 길이로, 숫자 필드는 값으로 표시합니다. XTypes를 제공하지 않는 발행자는 동일한 Python IDL 클래스가 필요합니다. |
| `NO_CONFIRMED_ROS_IMAGE` 또는 카메라 DDS 타입이 불명확함 | 도메인·NIC·발행 프로그램을 확인합니다. USB D435i가 PC2에 있고 다른 프로그램이 장치를 점유하지 않을 때는 `probe-usb`와 `tty-usb`를 사용합니다. |

`frame_id`, 인코딩, 발행 노드를 센서 설정과 대조해 **헤드 D435i의 깊이**인지 확인하세요. 같은 네트워크의 다른 카메라도 목록에 포함될 수 있습니다. `16UC1`과 `32FC1`은 깊이에 사용할 수 있는 픽셀 형식입니다. 토픽 이름이나 픽셀 형식만으로 센서 또는 미터 환산 단위를 정할 수 없습니다.

```bash
# ROS 2 압축 영상. TOPIC에 실제 수신한 CompressedImage 토픽을 입력합니다.
read -rp 'CompressedImage topic: ' TOPIC
bash docker/camera/pc2.sh compressed-view "$TOPIC"

# 네이티브 DDS. 발견 결과와 발행자 문서에서 확인한 정확한 이름을 사용합니다.
read -rp 'DDS topic: ' TOPIC
read -rp 'DDS type: ' TYPE
bash docker/camera/pc2.sh tty-dds --topic "$TOPIC" --type "$TYPE" --seconds 8

# USB 직접 확인. probe는 장치와 지원 프로필을 읽고, tty-usb가 스트림을 엽니다.
bash docker/camera/pc2.sh probe-usb
bash docker/camera/pc2.sh tty-usb --seconds 5
```

RViz 실행에는 X11 디스플레이와 유효한 `DISPLAY`·`XAUTHORITY`가 필요합니다. PC2 화면이 없으면 같은 DDS 도메인에 연결된 Linux PC에서 RViz2를 열어 같은 영상 토픽을 선택할 수 있습니다. USB는 공식 예제의 `640×480, 60 FPS, Z16`을 기본으로 사용합니다. `probe-usb` 출력에 따라 `--width`, `--height`, `--fps`를 바꿀 수 있습니다. `DEVICE_BUSY`가 뜨면 현재 장치를 여는 발행자를 확인하세요.

### 깊이 기록

보정된 `16UC1` 깊이 프레임과 같은 촬영 시각의 `sensor_msgs/msg/CameraInfo`가 발행되고 있을 때 PC2에서 실행합니다. 단위는 발행자 설정에 맞게 입력하세요.

```bash
RUN_ID="stairs-$(date -u +%Y%m%dT%H%M%SZ)"
read -rp 'Depth Image topic: ' depth_topic
read -rp 'CameraInfo topic: ' info_topic
read -rp 'Metres per stored depth unit: ' depth_unit
bash docker/camera/pc2.sh record-ros --depth-topic "$depth_topic" --info-topic "$info_topic" \
  --depth-scale-m "$depth_unit" --run "$RUN_ID" --runs-dir /workspace/jsj-camera/runs
```

USB로 직접 기록할 실험은 컨테이너를 처음 만들 때 `bash docker/camera/pc2.sh start --usb`로 D435i를 연결합니다. 이후 아래 명령을 사용하세요. 관측만 필요한 `tty-usb`는 기존 컨테이너의 USB 설정과 관계없이 실행됩니다.

```bash
RUN_ID="stairs-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec g1-jsj-realsense python3 -m g1stairs.camera record \
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
    docker start jsj-footstep-workbench >/dev/null
  else
    docker run -d --name jsj-footstep-workbench --pull never --platform linux/arm64 \
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

**② 기록 전달 및 측정**. 녹화에 썼던 PC2 터미널이면 같은 `RUN_ID`를 사용합니다. 새 터미널이면 완료된 기록 목록이 나오고 실험 이름을 입력할 수 있습니다. 보정이 기록에 포함돼 있으면 바로 계산합니다. 보정이 없으면 **촬영 자세에서 실측한 보정 JSON**을 입력하라는 안내가 나옵니다. `rotation`과 `translation_m`은 카메라 광학 좌표에서 중력 정렬 좌표로의 변환입니다. [JSON 필드 예시](config/calibration.example.json)의 숫자는 형식 설명용입니다.

```bash
(
  set -euo pipefail
  if [[ -z "${RUN_ID:-}" ]]; then
    docker exec g1-jsj-realsense bash -c 'cd /workspace/jsj-camera/runs && ls -d */depth/manifest.json'
    read -rp '분석할 실험 이름: ' RUN_ID
  fi
  [[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]] || { echo '실험 이름을 확인하세요.' >&2; exit 1; }
  src="/workspace/jsj-camera/runs/$RUN_ID"
  dst="/workspace/jsj-footstep-workbench/runs/$RUN_ID"
  docker exec g1-jsj-realsense test -s "$src/depth/manifest.json"
  docker exec jsj-footstep-workbench mkdir -p "$dst"
  if ! docker exec jsj-footstep-workbench test -e "$dst/depth"; then
    tmp=$(docker exec jsj-footstep-workbench mktemp -d "$dst/.incoming-XXXXXX")
    docker exec g1-jsj-realsense tar -C "$src" -cf - depth \
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
docker stop jsj-monitor
docker stop g1-jsj-realsense
docker stop jsj-footstep-workbench
```

PC2에서의 실제 빌드, DDS·D435i 수신, 계단 실측 비교는 현장 확인 항목입니다.
