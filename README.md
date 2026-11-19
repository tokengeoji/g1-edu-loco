# G1 EDU loco

Unitree G1 EDU의 전신 상태와 온도를 기록하고, 전방 Depth 카메라 데이터를 이용해 계단 치수를 측정한다. 세 모듈을 합성 데이터로 한 번에 시험할 수 있다.

| 디렉터리 | 기능 | 결과 |
| --- | --- | --- |
| [`g1stairs/monitoring/`](g1stairs/monitoring/) | Unitree SDK2 `rt/lowstate` 구독, 관절·IMU·모터 외함/권선 온도 기록과 웹 대시보드 | `runs/<run_id>/state/` |
| [`g1stairs/camera/`](g1stairs/camera/) | G1 헤드 RealSense D435i의 Depth 원본·깊이 스케일·카메라 보정·시각 기록과 재생 | `runs/<run_id>/depth/` |
| [`g1stairs/geometry/`](g1stairs/geometry/) | 보정된 깊이의 3D 역투영과 단 윗면 측정. 관측된 단 높이·디딤면 깊이·폭과 미관측 범위 기록 | `runs/<run_id>/geometry/` |
| [`g1stairs/session.py`](g1stairs/session.py) | 공통 세션 경로, JSON/JSONL, 기록 완료 manifest | 동일 ID의 `state`, `depth`, `geometry`를 독립 저장 |

## G1-EDU PC2에서 Docker로 실행

PC2에 SSH로 접속한 뒤 PC2 터미널에서 Docker CLI만 사용한다. 기존 `jsj-g1-base:foxy`는 Ubuntu 20.04·ROS 2 Foxy·Python 3.8 기반이다. 이미지 빌드의 `RUN`에서 Git 저장소를 내려받고, 프로그램과 실험 기록은 컨테이너 내부에 둔다. 호스트의 소프트웨어와 파일을 보존하고, 사용자 지정 마운트 없이 실행한다.

```bash
docker image inspect jsj-g1-base:foxy --format '{{.Os}}/{{.Architecture}} volumes={{json .Config.Volumes}}'

docker build --pull=false --no-cache -t jsj-g1-loco-tools:foxy - <<'DOCKERFILE'
FROM jsj-g1-base:foxy
ARG G1_LOCO_BRANCH=main
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /opt/g1-edu-loco
RUN . /etc/os-release \
    && test "$ID" = ubuntu && test "$VERSION_ID" = 20.04 \
    && test -f /opt/ros/foxy/setup.bash \
    && python3 -c 'import sys, numpy; assert sys.version_info[:2] == (3, 8)' \
    && git clone --depth 1 --branch "$G1_LOCO_BRANCH" https://github.com/tokengeoji/g1-edu-loco.git . \
    && git rev-parse HEAD
CMD ["sleep", "infinity"]
DOCKERFILE
```

기반 이미지가 확인된 경우, 사용하려는 기능의 컨테이너만 생성한다. 기존 이름이 있으면 `docker inspect`로 이미지를 포함한 설정을 확인하고 해당 컨테이너를 재사용한다. 실험 기록은 컨테이너의 쓰기 레이어에 저장되므로 컨테이너 삭제 시 해당 기록도 사라진다.

```bash
create_g1_loco_container() (
  set -eu
  name="$1"
  case "$name" in
    jsj-monitor|jsj-camera) network=host ;;
    jsj-footstep-workbench) network=bridge ;;
    *) printf '%s\n' '기능별 이름을 사용하세요.' >&2; exit 2 ;;
  esac
  test "$(docker image inspect jsj-g1-loco-tools:foxy --format '{{len .Config.Volumes}}')" = 0
  if docker container inspect "$name" >/dev/null 2>&1; then
    printf '기존 %s를 확인한 뒤 재사용하세요.\n' "$name" >&2
    exit 1
  fi
  docker run -d --name "$name" --pull never --network "$network" \
    --ipc private --cap-drop ALL --security-opt no-new-privileges:true \
    jsj-g1-loco-tools:foxy
)

# 사용할 기능만 선택해 실행한다.
create_g1_loco_container jsj-footstep-workbench
```

### 컨테이너 안에서 합성 데이터 검증

아래 명령은 PC2의 Docker CLI에서 컨테이너 내부 프로그램을 호출한다. `start-demo.sh`는 합성 데이터로 세 모듈을 검증하고 결과를 `/workspace/jsj-footstep-workbench/runs/demo`에 저장한다.

```bash
docker exec -w /opt/g1-edu-loco jsj-footstep-workbench python3 -m unittest discover -v
docker exec -w /opt/g1-edu-loco jsj-footstep-workbench bash scripts/start-demo.sh
```

웹 대시보드를 확인할 때는 PC2의 `jsj-monitor`에서 합성 상태 기록을 만든 뒤 서버를 실행한다.

```bash
create_g1_loco_container jsj-monitor
docker exec -w /opt/g1-edu-loco jsj-monitor python3 -m g1stairs.monitoring fixture \
  --runs-dir /workspace/jsj-monitor/runs --run monitor-demo
docker exec -w /opt/g1-edu-loco jsj-monitor python3 -m g1stairs.monitoring serve \
  --runs-dir /workspace/jsj-monitor/runs --run monitor-demo --bind 127.0.0.1 --port 8765
```

개발 PC에서는 SSH 포트 포워딩과 브라우저로 조회한다.

```bash
ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 "$G1_PC2_SSH_TARGET"
```

브라우저는 [127.0.0.1:8765](http://127.0.0.1:8765/)에 접속한다. `G1_PC2_SSH_TARGET`에는 기존 PC2 SSH 접속 대상을 넣는다.

카메라의 합성 계단은 단 높이 `0.15 m`, 디딤면 깊이 `0.35 m`, 폭 `1.00 m`를 사용한다. 측정 결과는 `geometry/stairs.jsonl`, 합성 정답은 `depth/truth.json`에 저장된다. 카메라가 경계를 확인할 수 없는 단에서는 길이·폭을 `null`로 기록하고 관측 범위를 별도 필드로 남긴다.

## 실기 수신

### 로봇 상태와 온도

기능별 `jsj-monitor` 컨테이너에서 Unitree SDK2 Python과 호환 CycloneDDS를 사용한다. 실제 로봇 NIC·DDS 도메인·기체 프로필을 적용한다. 구독 명령은 [모니터링 가이드](g1stairs/monitoring/README.md)에 있다.

### 원본 Depth

[Unitree G1 Depth Camera Routine](https://support.unitree.com/home/en/G1_developer/depth_camera_instruction)은 헤드 카메라를 **RealSense D435i**로 명시하고, librealsense **2.54.1** 예제에서 Depth를 **640×480, 60 FPS, `RS2_FORMAT_Z16`**으로 요청한다. `Z16`은 픽셀당 부호 없는 16비트 깊이 값의 인코딩이다. 60 FPS는 예제 설정이며, 실제 장치의 지원 여부를 `probe`로 확인한다. 측정값은 SDK에서 읽은 `depth_scale_m`을 적용해 미터로 환산한다.

`jsj-camera` 컨테이너에서 SDK와 카메라가 기존 규칙에 맞게 접근 가능한 경우에만 실기 스트림을 연다. 설치된 Python 바인딩이 없거나 장치가 보이지 않으면 해당 사유를 기록하고 합성·기존 기록 검증을 사용한다. Unitree 예제에는 IR·RGB·카메라 IMU도 설정되어 있다. 이 프로젝트의 계단 계산 경로에서는 Depth를 기록한다.

```bash
docker exec -w /opt/g1-edu-loco jsj-camera python3 -m g1stairs.camera probe
docker exec -w /opt/g1-edu-loco jsj-camera python3 -m g1stairs.camera record \
  --runs-dir /workspace/jsj-camera/runs --run stairs-01 --seconds 10
```

기본 프로필이 실제 장치에 없으면 `probe`에 나온 규격을 `--width`, `--height`, `--fps`로 지정한다. 녹화를 끝낸 뒤에는 선택한 세션의 `depth/`를 Docker 표준 입출력으로 분석 컨테이너에 전달할 수 있다. G1 SDK의 광학 좌표 및 내참수를 사용하고, 로봇에 장착된 카메라에서 중력 정렬 좌표계로 변환하는 보정은 실제 촬영 자세에서 측정한다. [보정 형식 예시](config/calibration.example.json)의 수치는 형식 설명용이다. 실기 분석은 분석 컨테이너 안의 보정 파일을 `geometry measure --calibration <경로>`에 전달한다. `ground_z_m`을 확인한 경우 첫 단 높이의 기준면으로 지정한다.

### 데이터 연결

같은 실험의 로봇 상태와 카메라 기록에는 동일한 `--run` 값을 지정한다. 각 센서의 장치 시각·도메인과 호스트 도착 시각은 기록에 남긴다. 서로 다른 컴퓨터의 단조 시각은 별도 동기화 정보가 필요하다. `geometry/`의 결과는 관측한 표면의 치수를 나타내며, 발 디딤 후보 검사는 후속 모듈에서 수행한다.

## 공식 참고 자료

- [Unitree SDK2 Python](https://github.com/unitreerobotics/unitree_sdk2_python)
- [Unitree G1 SDK Development Guide](https://support.unitree.com/home/en/G1_developer/about_G1)
- [Unitree G1 Depth Camera Routine](https://support.unitree.com/home/en/G1_developer/depth_camera_instruction)
- [RealSense SDK 2.0의 Depth 인코딩·좌표계](https://dev.realsenseai.com/docs/projection-in-realsense-sdk-2-0/)
- [RealSense SDK 3D 측정 예제](https://github.com/realsenseai/librealsense/blob/master/examples/measure/readme.md)
- [Docker Build 입력](https://docs.docker.com/build/concepts/context/#empty-context)
