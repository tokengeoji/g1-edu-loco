# G1 EDU loco 실행 가이드

PC2에 있는 **`jsj-g1-base:foxy`**로 모니터링·카메라·계단 분석 컨테이너를 실행합니다. 대상 기체는 허리가 잠기지 않은 **29자유도 G1 EDU**입니다. **온도와 관절 상태만 보려면 1단계와 2단계만** 진행하세요.

| 하고 싶은 작업 | 컨테이너 | 실행 순서 |
| --- | --- | --- |
| 29개 관절·모터 온도·IMU 보기 | `jsj-monitor` | [PC2 접속](#pc2) → [모니터링](#monitoring) |
| 실제 헤드 D435i 깊이 영상 기록 | `jsj-camera` | [PC2 접속](#pc2) → [Depth 기록](#camera) |
| 기록한 계단 높이·디딤면 깊이·폭 계산 | `jsj-footstep-workbench` | [Depth 기록](#camera) → [계단 측정](#geometry) |
| 이전에 만든 컨테이너로 다시 작업 | 해당 기능 컨테이너 | [재시작 및 코드 갱신](#resume) |

<a id="pc2"></a>

## 1. PC2 접속과 베이스 이미지 확인

**개발 PC 터미널**에서 평소 사용하는 PC2 SSH 별칭 또는 `계정@주소`를 입력합니다.

```bash
read -rp 'PC2 SSH 접속 대상: ' PC2_SSH
ssh "$PC2_SSH"
```

**SSH로 접속한 PC2 터미널**에서 공통 이미지와 기존 컨테이너를 확인합니다.

```bash
docker image inspect jsj-g1-base:foxy --format 'image={{index .RepoTags 0}} platform={{.Os}}/{{.Architecture}}'
docker ps -a --filter name=jsj- --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

첫 명령에서 공통 이미지와 `linux/arm64`를 확인합니다. 이미지가 없으면 프로젝트의 [공통 베이스 이미지 준비 문서](https://app.notion.com/p/41a3c6661b7d8117a89cf15e9824c6fa)를 먼저 확인하세요. 같은 이름의 컨테이너가 이미 있으면 [재시작 절차](#resume)로 이동합니다.

**베이스 이미지를 실행하는 명령이 각 기능의 `docker run … jsj-g1-base:foxy sleep infinity`입니다.** 이 한 줄이 새 컨테이너를 만들고 시작합니다. `sleep infinity`로 컨테이너를 켜 둔 뒤 `docker exec -it … bash`로 들어가 Git과 Python을 실행합니다. `--pull never`는 PC2에 있는 이미지를 사용합니다. [Docker run](https://docs.docker.com/reference/cli/docker/container/run/) · [Docker exec](https://docs.docker.com/reference/cli/docker/container/exec/)

<a id="monitoring"></a>

## 2. 전신 모니터링 GUI 실행

**① PC2 터미널**에서 모니터링 컨테이너를 만들고 들어갑니다.

```bash
docker run -d --name jsj-monitor --pull never --platform linux/arm64 \
  --network host --ipc private --cap-drop ALL --security-opt no-new-privileges:true \
  jsj-g1-base:foxy sleep infinity
docker exec -it jsj-monitor bash
```

**② `jsj-monitor` 안**에서 처음 한 번 코드를 받고 바로 GUI를 실행합니다.

```bash
git clone --branch main --single-branch --sparse https://github.com/tokengeoji/g1-edu-loco.git /opt/g1-edu-loco
cd /opt/g1-edu-loco
git sparse-checkout init --cone
git sparse-checkout set g1stairs/monitoring
python3 -m g1stairs.monitoring serve
```

**③ 개발 PC의 새 터미널**에서 SSH 포트 포워딩을 엽니다. 이 터미널을 열어 둔 채 개발 PC 브라우저에서 [모니터링 화면](http://127.0.0.1:8765)을 엽니다.

```bash
read -rp 'PC2 SSH 접속 대상: ' PC2_SSH
ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 "$PC2_SSH"
```

실제 `rt/lowstate`가 들어오면 다리 12축·허리 3축·팔 14축의 값이 갱신됩니다. 페이지가 열리는 것과 로봇 상태가 수신되는 것은 화면에서 각각 확인합니다. 기록도 필요하면 별도의 **PC2 터미널**에서 아래 명령으로 실제 상태를 기본 10초간 저장합니다. [기록 필드와 SDK 설정](g1stairs/monitoring/README.md)

```bash
docker exec -w /opt/g1-edu-loco jsj-monitor bash -c \
  'python3 -m g1stairs.monitoring record --run stairs-01 --runs-dir /workspace/jsj-monitor/runs'
```

<a id="camera"></a>

## 3. 헤드 D435i의 실제 Depth 기록

**① PC2 터미널**에서 카메라 컨테이너를 만들고 들어갑니다.

```bash
docker run -d --name jsj-camera --pull never --platform linux/arm64 --runtime nvidia \
  --network host --ipc private --cap-drop ALL --security-opt no-new-privileges:true \
  jsj-g1-base:foxy sleep infinity
docker exec -it jsj-camera bash
```

**② `jsj-camera` 안**에서 카메라 코드를 받고 기존 ROS 2 발행자를 조회합니다. 이후 실제 연결 상태에 맞는 수집 경로 한 가지를 사용합니다.

```bash
git clone --branch main --single-branch --sparse https://github.com/tokengeoji/g1-edu-loco.git /opt/g1-edu-loco
cd /opt/g1-edu-loco
git sparse-checkout init --cone
git sparse-checkout set g1stairs/camera
ros2 topic list -t
```

**기존 D435i 발행자가 있을 때**는 같은 광학 좌표계·촬영 시각의 보정된 원본 깊이 영상(`16UC1`)과 `CameraInfo`를 구독합니다. 카메라 발행자와 같은 DDS 도메인에서 조회한 토픽명과 발행자가 사용하는 픽셀 한 단위당 미터 값을 입력하세요. [ROS 2 Foxy CameraInfo](https://github.com/ros2/common_interfaces/blob/foxy/sensor_msgs/msg/CameraInfo.msg)

```bash
read -rp '실제 D435i 깊이 영상 토픽: ' DEPTH_TOPIC
read -rp '짝이 되는 CameraInfo 토픽: ' INFO_TOPIC
read -rp '발행자의 깊이 한 단위당 미터 값: ' DEPTH_UNIT_M
python3 -m g1stairs.camera record-ros \
  --depth-topic "$DEPTH_TOPIC" --info-topic "$INFO_TOPIC" --depth-scale-m "$DEPTH_UNIT_M" \
  --runs-dir /workspace/jsj-camera/runs --run stairs-01
```

**컨테이너에서 D435i에 직접 접근할 수 있을 때**는 기존 프로그램이 장치를 사용 중인지 확인하고, 아래 [SDK 확인](#sdk)을 같은 셸에서 마친 뒤 실행합니다. `probe`에서 실제 D435i와 지원 프로필이 확인되면 `record`를 실행하세요. Unitree 예제의 기본 요청은 640×480, 60 FPS, Z16입니다. [Unitree Depth Camera Routine](https://support.unitree.com/home/en/G1_developer/depth_camera_instruction)

```bash
python3 -m g1stairs.camera probe
python3 -m g1stairs.camera record --runs-dir /workspace/jsj-camera/runs --run stairs-01
```

녹화가 끝나면 출력의 `source`, `frame_count`, `depth_scale_m`, `invalid_depth_fraction`을 확인하세요. 완료된 기록은 `/workspace/jsj-camera/runs/stairs-01/depth/`에 있습니다. 같은 계단을 다시 촬영할 때는 새 실험 이름을 쓰고 아래 분석 단계에도 그 이름을 적용합니다. `exit`로 PC2 터미널에 돌아갑니다.

<a id="geometry"></a>

## 4. 촬영한 계단 치수 계산

**① PC2 터미널**에서 분석 컨테이너를 만들고 들어갑니다.

```bash
docker run -d --name jsj-footstep-workbench --pull never --platform linux/arm64 \
  --network bridge --ipc private --cap-drop ALL --security-opt no-new-privileges:true \
  jsj-g1-base:foxy sleep infinity
docker exec -it jsj-footstep-workbench bash
```

**② `jsj-footstep-workbench` 안**에서 계단 분석 코드를 받습니다. 이어서 [RealSense SDK 확인](#sdk)을 진행합니다.

```bash
git clone --branch main --single-branch --sparse https://github.com/tokengeoji/g1-edu-loco.git /opt/g1-edu-loco
cd /opt/g1-edu-loco
git sparse-checkout init --cone
git sparse-checkout set g1stairs/geometry config
```

**③ 같은 컨테이너 안**에서 촬영 당시의 실측 보정 파일을 준비합니다. 이미 `depth/calibration.json`을 포함해 녹화한 경우에는 ④로 이동하세요. 아래는 실측한 JSON 내용을 컨테이너에 직접 입력하는 방법입니다. `cat` 실행 후 JSON을 붙여 넣고 새 줄에서 **Ctrl+D**를 누릅니다. `rotation`(3×3)과 `translation_m`(3개 값)은 카메라 광학 좌표에서 중력에 정렬된 좌표로의 변환입니다. 첫 단의 기준 바닥을 측정했다면 `ground_z_m`도 지정합니다. [보정 JSON 필드 예시](config/calibration.example.json)의 수치는 형식 설명용입니다.

```bash
mkdir -p /workspace/jsj-footstep-workbench/calibration
( set -C; cat > /workspace/jsj-footstep-workbench/calibration/stairs-01.json )
```

**④ PC2 터미널**에서 아래 블록을 실행해 방금 촬영한 `depth/`를 카메라 컨테이너에서 분석 컨테이너로 복사합니다. 컨테이너 셸에 있다면 먼저 `exit`를 입력하세요. 전송은 Docker 표준입출력을 사용하고, 완료된 데이터만 분석 경로로 이동합니다. 같은 이름의 기록이 이미 있으면 기존 데이터를 보존하고 종료합니다.

```bash
(
  set -euo pipefail
  run=stairs-01
  src="/workspace/jsj-camera/runs/$run"
  dst="/workspace/jsj-footstep-workbench/runs/$run"
  docker exec jsj-camera test -s "$src/depth/manifest.json"
  docker exec jsj-footstep-workbench mkdir -p "$dst"
  docker exec jsj-footstep-workbench test ! -e "$dst/depth"
  tmp=$(docker exec jsj-footstep-workbench mktemp -d "$dst/.incoming-XXXXXX")
  docker exec jsj-camera tar -C "$src" -cf - depth \
    | docker exec -i jsj-footstep-workbench tar --no-same-owner -C "$tmp" -xf -
  docker exec jsj-footstep-workbench test -s "$tmp/depth/manifest.json"
  docker exec jsj-footstep-workbench mv -Tn "$tmp/depth" "$dst/depth"
  docker exec jsj-footstep-workbench rmdir "$tmp"
)
```

**⑤ PC2 터미널**에서 분석 컨테이너에 다시 들어갑니다.

```bash
docker exec -it -w /opt/g1-edu-loco jsj-footstep-workbench bash
```

**분석 컨테이너 안**에서 다음 명령을 실행합니다. ③에서 보정 파일을 준비한 경우의 명령입니다.

```bash
python3 -m g1stairs.geometry measure --run stairs-01 \
  --runs-dir /workspace/jsj-footstep-workbench/runs \
  --calibration /workspace/jsj-footstep-workbench/calibration/stairs-01.json
head -n 1 /workspace/jsj-footstep-workbench/runs/stairs-01/geometry/stairs.jsonl
```

보정이 이미 `depth/calibration.json`에 포함된 경우에는 위 명령에서 `--calibration` 인자를 생략합니다. 기본값은 첫 프레임 측정입니다. 출력의 `riser_height_m`, `tread_depth_m`, `width_m`을 실제 계단 실측값과 비교하세요. 관측되지 않은 경계는 `null`로 표시됩니다. [RealSense SDK 역투영](https://dev.realsenseai.com/docs/projection-in-realsense-sdk-2-0/)

<a id="sdk"></a>

### RealSense Python SDK 확인

**D435i 직접 수집 또는 계단 분석을 실행할 컨테이너 안**에서 확인합니다. 기존 ROS 2 Depth만 구독할 때는 베이스의 Foxy 패키지를 사용합니다.

```bash
python3 -c 'import pyrealsense2 as rs; print(rs.__file__)'
```

바인딩이 없을 때만 같은 컨테이너 안에서 공식 Python 3.8 호환 패키지를 설치하고 다시 확인합니다. [RealSense ARM64 배포 파일](https://pypi.org/project/pyrealsense2/2.54.1.5217/#files)

```bash
python3 -m pip install --user --no-cache-dir --only-binary=:all: --no-deps pyrealsense2==2.54.1.5217
python3 -c 'import pyrealsense2 as rs; print(rs.__file__)'
```

<a id="resume"></a>

## 5. 다음 실험에서 재시작하고 갱신하기

**PC2 터미널**에서 사용할 컨테이너 상태를 확인합니다. 예를 들어 모니터를 다시 쓸 때는 아래 순서입니다. 기존 이름이 다른 이미지에 연결되어 있다면 아래 갱신 절차를 적용하기 전에 해당 컨테이너의 용도를 확인하세요.

```bash
docker inspect --format 'image={{.Config.Image}} status={{.State.Status}}' jsj-monitor
# 정지 상태일 때
docker start jsj-monitor
# 기록 또는 GUI를 종료한 뒤 코드 갱신
docker exec jsj-monitor git -C /opt/g1-edu-loco pull --ff-only
docker exec -it -w /opt/g1-edu-loco jsj-monitor bash -c 'python3 -m g1stairs.monitoring serve'
```

컨테이너만 생성해 둬서 `git pull` 시 `/opt/g1-edu-loco`가 없다고 나오면, PC2에서 `docker exec -it jsj-monitor bash`처럼 해당 셸로 들어가 그 기능의 **② 최초 Git 다운로드** 블록부터 실행합니다.

카메라·분석 컨테이너도 생성되어 있다면 아래에서 필요한 기능의 줄만 실행하고 3·4단계의 수집 또는 측정 명령을 사용하세요.

```bash
docker start jsj-camera
docker exec jsj-camera git -C /opt/g1-edu-loco pull --ff-only
docker start jsj-footstep-workbench
docker exec jsj-footstep-workbench git -C /opt/g1-edu-loco pull --ff-only
```

`Ctrl+C`는 현재 프로그램을 종료합니다. 컨테이너 셸에서 `exit`를 입력하면 PC2 터미널로 돌아갑니다. 컨테이너 자체를 정지할 때는 PC2에서 `docker stop jsj-monitor`처럼 기능 이름을 지정합니다. 다음에 같은 컨테이너를 시작하면 코드와 기록이 남아 있습니다.

**검증 범위** · 이 가이드는 저장소 CLI와 공식 SDK 문서를 기준으로 작성했습니다. PC2의 실제 DDS 수신, D435i 프레임 수신, 계단 실측 비교는 현장 확인 항목입니다.
