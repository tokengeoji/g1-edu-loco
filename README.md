# G1 EDU loco

Unitree G1 EDU의 전신 상태와 온도를 기록하고, 전방 Depth 카메라 데이터를 이용해 계단 치수를 측정한다. 세 모듈을 합성 데이터로 한 번에 시험할 수 있다.

| 디렉터리 | 기능 | 결과 |
| --- | --- | --- |
| [`g1stairs/monitoring/`](g1stairs/monitoring/) | Unitree SDK2 `rt/lowstate` 구독, 관절·IMU·모터 외함/권선 온도 기록과 웹 대시보드 | `runs/<run_id>/state/` |
| [`g1stairs/camera/`](g1stairs/camera/) | RealSense Z16 원본·깊이 스케일·카메라 보정·시각 기록, 저장된 깊이 재생과 점검 | `runs/<run_id>/depth/` |
| [`g1stairs/geometry/`](g1stairs/geometry/) | 보정된 깊이의 3D 역투영과 단 윗면 측정. 관측된 단 높이·디딤면 깊이·폭과 미관측 범위 기록 | `runs/<run_id>/geometry/` |
| [`g1stairs/session.py`](g1stairs/session.py) | 공통 세션 경로, JSON/JSONL, 기록 완료 manifest | 동일 ID의 `state`, `depth`, `geometry`를 독립 저장 |

## 내 PC에서 Docker로 실행

Docker Engine과 Compose v2가 동작하는 Linux PC에서 실행한다. 이 구성은 개인 PC용이며, 로봇 PC2에서 기존 `jsj-g1-base:foxy` 가이드를 사용하는 경우에는 그 환경의 파일·장치 전달 조건을 따른다.

```bash
git clone https://github.com/tokengeoji/g1-edu-loco.git
cd g1-edu-loco
bash scripts/start-local.sh
```

`jsj-loco-monitoring`, `jsj-loco-camera`, `jsj-loco-geometry`가 생성된다. 모니터링 화면은 [127.0.0.1:8765](http://127.0.0.1:8765/)에서 볼 수 있다. 카메라와 계단 컨테이너는 명령 실행용으로 유지된다. 시작 스크립트는 합성 상태와 깊이 기록을 만들어 `runs/demo/`에 저장하고 계단 계산을 실행한다. 이미 완료된 같은 이름의 기록은 보존한다. 다른 데모 세션과 포트는 `G1_DEMO_RUN=demo2 MONITOR_PORT=8766 bash scripts/start-local.sh`처럼 지정한다.

```bash
docker compose ps
docker compose exec camera python -m g1stairs.camera replay --runs-dir /runs --run demo
docker compose logs monitoring
```

## Docker 없이 합성 데이터로 검증

Python 3.8~3.11 및 `requirements.txt`의 NumPy 설치 환경에서, 저장소 루트에서 실행한다. Docker 예제는 Python 3.10을 사용한다. 다음 명령은 `sample`이라는 새 실험 ID를 만든다.

```bash
python3 -m pip install -r requirements.txt
python3 -m g1stairs.monitoring fixture --run sample
python3 -m g1stairs.camera fixture --run sample
python3 -m g1stairs.camera replay --run sample
python3 -m g1stairs.geometry measure --run sample --all-frames
python3 -m unittest discover -v
python3 -m g1stairs.monitoring serve --run sample
```

카메라의 합성 계단은 단 높이 `0.15 m`, 디딤면 깊이 `0.35 m`, 폭 `1.00 m`를 사용한다. 측정 결과는 `geometry/stairs.jsonl`, 합성 정답은 `depth/truth.json`에 저장된다. 카메라가 경계를 확인할 수 없는 단에서는 길이·폭을 `null`로 기록하고 관측 범위를 별도 필드로 남긴다.

## 실기 수신

### 로봇 상태와 온도

Unitree SDK2 Python과 호환 CycloneDDS가 준비된 환경에서 실제 로봇 NIC·DDS 도메인·기체 프로필을 넣는다. 프로필과 명령은 [모니터링 가이드](g1stairs/monitoring/README.md)에 정리했다. 기본 Docker 데모는 장치나 실기 DDS에 접속하지 않는다. 실기에서는 먼저 `probe`로 수신을 확인하고 `record` 또는 `serve`를 실행한다.

### 원본 Depth

카메라가 연결된 Linux 환경에서 호환 RealSense SDK를 준비한다. 먼저 `probe`로 장치와 Z16 지원 해상도·FPS를 확인한다. 기존 스트림이 사용 중이면 현재 제공되는 데이터를 재사용할 수 있는지 확인한다. 직접 기록은 장치를 볼 수 있고 스트림을 열 수 있는 환경에서 실행한다. `depth_scale_m`은 각 장치가 보고한 값이다.

```bash
python3 -m g1stairs.camera probe --source realsense
python3 -m g1stairs.camera record --source realsense --run stairs-01 \
  --seconds 10 --calibration config/measured-camera.json
python3 -m g1stairs.geometry measure --run stairs-01 --all-frames
```

`config/measured-camera.json`은 해당 촬영 자세에서 측정한 보정 파일이다. [예시 형식](config/calibration.example.json)의 행렬과 높이는 형식 설명용이다. 보정 파일이 아직 준비되지 않았다면 Depth 기록을 먼저 마치고 나중에 `geometry measure --calibration <경로>`로 전달할 수 있다. `ground_z_m`을 확인한 경우 첫 단 높이의 기준면으로 지정한다. 1차 기하 분석은 카메라가 정지한 기록과 고정 보정을 입력으로 사용한다.

### 데이터 연결

같은 실험의 로봇 상태와 카메라 기록에는 동일한 `--run` 값을 지정한다. 각 센서의 장치 시각·도메인과 호스트 도착 시각은 기록에 남긴다. 서로 다른 컴퓨터의 단조 시각은 별도 동기화 정보가 필요하다. `geometry/`의 결과는 관측한 표면의 치수를 나타내며, 발 디딤 후보 검사는 후속 모듈에서 수행한다.

## 공식 참고 자료

- [Unitree SDK2 Python](https://github.com/unitreerobotics/unitree_sdk2_python)
- [RealSense SDK 3D 측정 예제](https://github.com/realsenseai/librealsense/blob/master/examples/measure/readme.md)
- [Docker Compose 명령](https://docs.docker.com/reference/cli/docker/compose/up/)
