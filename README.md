# G1 EDU loco 실행 가이드

처음 설정할 때는 **공통 베이스 이미지부터 빌드**합니다. 그다음 사용할 기능의 컨테이너를 만들고, 컨테이너 안에서 코드를 내려받아 실행합니다.

| 원하는 작업 | PC2에서 실행할 순서 |
| --- | --- |
| 전신 관절·모터 온도 GUI 열기 | [1. 베이스 빌드](#pc2) → [2. 모니터링](#monitoring) |
| 헤드 D435i의 실제 깊이 영상 기록 | [1. 베이스 빌드](#pc2) → [3. 카메라](#camera) |
| 촬영한 계단의 높이·디딤면 깊이·폭 측정 | [1. 베이스 빌드](#pc2) → [3. 카메라 기록](#camera) → [4. 계단 측정](#geometry) |

<a id="pc2"></a>

## 1. PC2에서 공통 베이스 이미지 만들기

PC2의 **Bash 터미널**에서 아래 블록 전체를 한 번 붙여넣으세요. Docker가 이 저장소의 Dockerfile을 읽어 `jsj-g1-base:foxy`를 빌드합니다. SDK 설치와 Git 복제는 이미지 빌드 안에서 실행됩니다. PC2의 L4T가 R35.3.1이면 부모 이미지가 자동 선택됩니다. 다른 버전이면 안내에 따라 해당 PC2와 호환되는 Ubuntu 20.04·ROS 2 Foxy ARM64 부모 이미지 태그를 입력하세요.

```bash
(
  set -euo pipefail
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
  [[ "$(docker image inspect --format '{{.Os}}/{{.Architecture}} {{if .Config.Volumes}}volumes{{else}}none{{end}}' "$parent")" == 'linux/arm64 none' ]] || {
    echo '부모 이미지의 플랫폼과 VOLUME 선언을 확인하세요.' >&2
    exit 1
  }

  docker build --platform linux/arm64 --build-arg BASE_IMAGE="$parent" \
    --tag jsj-g1-base:foxy \
    https://raw.githubusercontent.com/tokengeoji/g1-edu-loco/main/docker/base/Dockerfile
  docker image inspect --format 'jsj-g1-base:foxy  {{.Os}}/{{.Architecture}}  {{.Id}}' jsj-g1-base:foxy
)
```

마지막 줄에 `jsj-g1-base:foxy  linux/arm64  sha256:…`가 출력되면 빌드가 끝난 것입니다. 관절 상태를 보려면 [2번](#monitoring), 계단을 촬영하려면 [3번](#camera)으로 이동하세요. 이 이미지는 세 컨테이너에서 공통으로 사용하므로 최초 설정 때 한 번만 빌드하면 됩니다. [Dockerfile](docker/base/Dockerfile) · [이미지 구성과 SDK 확인 명령](docker/base/README.md#sdk) · [Docker 공식 빌드 문서](https://docs.docker.com/build/concepts/context/#how-to-build-without-a-context)

<a id="monitoring"></a>

## 2. 전신 모니터링

**① 컨테이너 생성·시작 및 코드 다운로드**. 다음 실험에서도 이 블록을 그대로 사용하면 됩니다.

```bash
(
  set -e
  if docker container inspect jsj-monitor >/dev/null 2>&1; then
    [[ "$(docker inspect -f '{{.Config.Image}}' jsj-monitor)" = jsj-g1-base:foxy ]] || {
      echo '같은 이름의 컨테이너가 다른 이미지를 사용합니다.' >&2
      exit 1
    }
    docker start jsj-monitor >/dev/null
  else
    docker run -d --name jsj-monitor --pull never --platform linux/arm64 \
      --network host --ipc private --cap-drop ALL --security-opt no-new-privileges:true \
      jsj-g1-base:foxy sleep infinity
  fi
  docker exec jsj-monitor bash -ec '
    repo=/opt/g1-edu-loco
    if [[ ! -d "$repo/.git" ]]; then
      git clone --branch main --single-branch --sparse https://github.com/tokengeoji/g1-edu-loco.git "$repo"
    fi
    cd "$repo"
    if [[ ! -f g1stairs/monitoring/__main__.py ]]; then
      git sparse-checkout init --cone
      git sparse-checkout set g1stairs/monitoring
    fi
    git pull --ff-only
    git rev-parse --short HEAD
  '
)
```

**② GUI 실행**. 이 명령이 실행되는 동안 화면이 갱신됩니다. 기본 수신 주소는 PC2의 `127.0.0.1:8765`입니다. 실제 `rt/lowstate`를 받으면 다리 12축·허리 3축·팔 14축과 IMU가 표시됩니다.

```bash
docker exec -it -w /opt/g1-edu-loco jsj-monitor bash -c 'exec python3 -m g1stairs.monitoring serve'
```

**③ 기록이 필요할 때만** 별도 PC2 터미널에서 실행합니다. 기본 10초간 기록한 후 실제 세션 이름을 출력합니다. [모니터링 필드·SDK 기본 설정](g1stairs/monitoring/README.md)

```bash
STATE_RUN_ID="state-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -w /opt/g1-edu-loco jsj-monitor bash -ec \
  'python3 -m g1stairs.monitoring record --run "$1" --runs-dir /workspace/jsj-monitor/runs' _ "$STATE_RUN_ID"
```

<a id="camera"></a>

## 3. D435i 깊이 영상 기록

**① 카메라 컨테이너 준비 및 코드 다운로드**.

```bash
(
  set -e
  if docker container inspect jsj-camera >/dev/null 2>&1; then
    [[ "$(docker inspect -f '{{.Config.Image}}' jsj-camera)" = jsj-g1-base:foxy ]] || {
      echo '같은 이름의 컨테이너가 다른 이미지를 사용합니다.' >&2
      exit 1
    }
    docker start jsj-camera >/dev/null
  else
    docker run -d --name jsj-camera --pull never --platform linux/arm64 --runtime nvidia \
      --network host --ipc private --cap-drop ALL --security-opt no-new-privileges:true \
      jsj-g1-base:foxy sleep infinity
  fi
  docker exec jsj-camera bash -ec '
    repo=/opt/g1-edu-loco
    if [[ ! -d "$repo/.git" ]]; then
      git clone --branch main --single-branch --sparse https://github.com/tokengeoji/g1-edu-loco.git "$repo"
    fi
    cd "$repo"
    if [[ ! -f g1stairs/camera/__main__.py ]]; then
      git sparse-checkout init --cone
      git sparse-checkout set g1stairs/camera
    fi
    git pull --ff-only
    git rev-parse --short HEAD
  '
)
```

**② 기존 발행자 확인**. 발행자와 같은 DDS 도메인에서 확인합니다. 기본 도메인이 다른 현장에서는 PC2 터미널에 실제 도메인을 `G1_CAMERA_DOMAIN`으로 설정하면 아래 명령이 사용합니다.

```bash
docker exec -e ROS_DOMAIN_ID="${G1_CAMERA_DOMAIN:-0}" jsj-camera bash -c 'ros2 topic list -t'
```

**③ 실제 연결 상태에 해당하는 블록 하나만 실행합니다.** 기록을 마치면 출력에서 `source`, `frame_count`, `depth_scale_m`, `invalid_depth_fraction`을 확인합니다. 실험 이름은 현재 시각으로 만들어집니다.

**기존 D435i ROS 2 발행자가 있는 경우**. 안내가 나오면 보정된 원본 깊이 영상(`16UC1`)의 실제 토픽, 짝이 되는 `CameraInfo` 토픽, 해당 발행자가 사용하는 깊이 한 단위당 미터 값을 입력합니다. [ROS 2 CameraInfo](https://github.com/ros2/common_interfaces/blob/foxy/sensor_msgs/msg/CameraInfo.msg)

```bash
RUN_ID="stairs-$(date -u +%Y%m%dT%H%M%SZ)"
(
  set -e
  read -rp '실제 D435i 깊이 영상 토픽: ' depth_topic
  read -rp '같은 촬영 시각·좌표계의 CameraInfo 토픽: ' info_topic
  read -rp '발행자의 깊이 한 단위당 미터 값: ' depth_unit
  docker exec -e ROS_DOMAIN_ID="${G1_CAMERA_DOMAIN:-0}" -w /opt/g1-edu-loco jsj-camera bash -ec \
    'python3 -m g1stairs.camera record-ros --depth-topic "$1" --info-topic "$2" --depth-scale-m "$3" --runs-dir /workspace/jsj-camera/runs --run "$4"' \
    _ "$depth_topic" "$info_topic" "$depth_unit" "$RUN_ID"
  echo "완료된 실험: $RUN_ID"
)
```

**SDK로 직접 수집하는 경우**. 기존 발행자가 장치를 쓰지 않고 D435i가 컨테이너에 보이는 상태에서 사용합니다. 블록은 바인딩을 확인하고, 없으면 해당 컨테이너에 공식 Python 3.8 호환 휠을 설치합니다. 공식 예제의 요청 규격은 640×480, 60 FPS, Z16입니다. 실제 장치가 이 규격을 지원해야 녹화가 시작됩니다. [Unitree Depth Camera Routine](https://support.unitree.com/home/en/G1_developer/depth_camera_instruction) · [RealSense 배포 파일](https://pypi.org/project/pyrealsense2/2.54.1.5217/#files)

```bash
RUN_ID="stairs-$(date -u +%Y%m%dT%H%M%SZ)"
(
  set -e
  docker exec jsj-camera bash -ec '
  if ! python3 -c "import pyrealsense2" 2>/dev/null; then
    python3 -m pip install --user --no-cache-dir --only-binary=:all: --no-deps pyrealsense2==2.54.1.5217
  fi
  python3 -c "import pyrealsense2 as rs; print(rs.__file__)"
'
  docker exec -w /opt/g1-edu-loco jsj-camera bash -ec '
    python3 -m g1stairs.camera probe
    python3 -m g1stairs.camera record --runs-dir /workspace/jsj-camera/runs --run "$1"
  ' _ "$RUN_ID"
  echo "완료된 실험: $RUN_ID"
)
```

<a id="geometry"></a>

## 4. 촬영한 계단 치수 측정

**① 분석 컨테이너 준비 및 코드 다운로드**.

```bash
(
  set -e
  if docker container inspect jsj-footstep-workbench >/dev/null 2>&1; then
    [[ "$(docker inspect -f '{{.Config.Image}}' jsj-footstep-workbench)" = jsj-g1-base:foxy ]] || {
      echo '같은 이름의 컨테이너가 다른 이미지를 사용합니다.' >&2
      exit 1
    }
    docker start jsj-footstep-workbench >/dev/null
  else
    docker run -d --name jsj-footstep-workbench --pull never --platform linux/arm64 \
      --network bridge --ipc private --cap-drop ALL --security-opt no-new-privileges:true \
      jsj-g1-base:foxy sleep infinity
  fi
  docker exec jsj-footstep-workbench bash -ec '
    repo=/opt/g1-edu-loco
    if [[ ! -d "$repo/.git" ]]; then
      git clone --branch main --single-branch --sparse https://github.com/tokengeoji/g1-edu-loco.git "$repo"
    fi
    cd "$repo"
    if [[ ! -f g1stairs/geometry/__main__.py ]]; then
      git sparse-checkout init --cone
      git sparse-checkout set g1stairs/geometry config
    fi
    git pull --ff-only
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
    docker exec jsj-camera bash -c 'cd /workspace/jsj-camera/runs && ls -d */depth/manifest.json'
    read -rp '분석할 실험 이름: ' RUN_ID
  fi
  [[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]] || { echo '실험 이름을 확인하세요.' >&2; exit 1; }
  src="/workspace/jsj-camera/runs/$RUN_ID"
  dst="/workspace/jsj-footstep-workbench/runs/$RUN_ID"
  docker exec jsj-camera test -s "$src/depth/manifest.json"
  docker exec jsj-footstep-workbench mkdir -p "$dst"
  if ! docker exec jsj-footstep-workbench test -e "$dst/depth"; then
    tmp=$(docker exec jsj-footstep-workbench mktemp -d "$dst/.incoming-XXXXXX")
    docker exec jsj-camera tar -C "$src" -cf - depth \
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
docker stop jsj-camera
docker stop jsj-footstep-workbench
```

PC2에서의 실제 빌드, DDS·D435i 수신, 계단 실측 비교는 현장 확인 항목입니다.
