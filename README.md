# G1 EDU loco

허리가 잠기지 않은 29자유도 G1 EDU의 상태와 헤드 카메라를 기록하고 실제 계단 치수를 계산합니다. PC2의 기존 이미지 **`jsj-g1-base:foxy`**로 기능별 컨테이너를 만듭니다.

| 컨테이너 | Git 디렉터리 | 기능 |
| --- | --- | --- |
| `jsj-monitor` | `g1stairs/monitoring/` | Unitree SDK2 Python으로 `rt/lowstate` 구독 |
| `jsj-camera` | `g1stairs/camera/` | 기존 D435i Depth 구독 또는 librealsense로 직접 수집 |
| `jsj-footstep-workbench` | `g1stairs/geometry/` | RealSense SDK로 깊이를 3D로 복원한 뒤 계단 치수 계산 |

## 최초 실행

PC2에 SSH로 접속한 터미널에서 사용할 기능의 블록을 실행합니다. `docker run`은 **새 컨테이너를 만들 때 한 번** 사용합니다. 기존 컨테이너는 `docker inspect --format '{{.Config.Image}}' 컨테이너이름`으로 이미지를 확인하고, 정지 상태면 `docker start 컨테이너이름`으로 재개합니다. 체크아웃이 이미 있으면 아래 갱신 명령부터 사용합니다. 컨테이너의 쓰기 레이어에 코드와 실험 로그를 보관합니다.

### 전신 모니터링

```bash
docker run -d --name jsj-monitor --pull never --platform linux/arm64 \
  --network host --ipc private --cap-drop ALL --security-opt no-new-privileges:true \
  jsj-g1-base:foxy sleep infinity
docker exec jsj-monitor git clone --branch main --single-branch --sparse \
  https://github.com/tokengeoji/g1-edu-loco.git /opt/g1-edu-loco
docker exec jsj-monitor git -C /opt/g1-edu-loco sparse-checkout init --cone
docker exec jsj-monitor git -C /opt/g1-edu-loco sparse-checkout set g1stairs/monitoring
```

### 헤드 카메라

```bash
docker run -d --name jsj-camera --pull never --platform linux/arm64 --runtime nvidia \
  --network host --ipc private --cap-drop ALL --security-opt no-new-privileges:true \
  jsj-g1-base:foxy sleep infinity
docker exec jsj-camera git clone --branch main --single-branch --sparse \
  https://github.com/tokengeoji/g1-edu-loco.git /opt/g1-edu-loco
docker exec jsj-camera git -C /opt/g1-edu-loco sparse-checkout init --cone
docker exec jsj-camera git -C /opt/g1-edu-loco sparse-checkout set g1stairs/camera
```

### 계단 측정

```bash
docker run -d --name jsj-footstep-workbench --pull never --platform linux/arm64 \
  --network bridge --ipc private --cap-drop ALL --security-opt no-new-privileges:true \
  jsj-g1-base:foxy sleep infinity
docker exec jsj-footstep-workbench git clone --branch main --single-branch --sparse \
  https://github.com/tokengeoji/g1-edu-loco.git /opt/g1-edu-loco
docker exec jsj-footstep-workbench git -C /opt/g1-edu-loco sparse-checkout init --cone
docker exec jsj-footstep-workbench git -C /opt/g1-edu-loco sparse-checkout set g1stairs/geometry config
```

Git은 각 컨테이너 안에서 실행합니다. sparse checkout은 선택한 모듈과 상위 공통 파일을 작업 디렉터리에 둡니다. 카메라 옵션은 PC2 카메라 운영 가이드의 NVIDIA 런타임 설정을 따릅니다. USB와 ROS 토픽의 실제 접근 여부는 컨테이너 안에서 확인합니다. [Git sparse checkout](https://git-scm.com/docs/git-sparse-checkout/2.25.0)

## 이후 코드 갱신

기록을 마친 뒤 변경된 기능의 명령만 실행합니다. 갱신 후 해당 프로그램을 다시 실행하면 새 코드가 적용됩니다.

```bash
docker exec jsj-monitor git -C /opt/g1-edu-loco pull --ff-only
docker exec jsj-camera git -C /opt/g1-edu-loco pull --ff-only
docker exec jsj-footstep-workbench git -C /opt/g1-edu-loco pull --ff-only
```

## 전신 모니터링

PC2 터미널에서 컨테이너에 들어갑니다.

```bash
docker exec -it -w /opt/g1-edu-loco jsj-monitor bash
```

컨테이너 안에서 GUI를 띄웁니다. 프로그램은 허리 세 축을 포함한 몸체 모터 29개와 IMU를 읽습니다. [기록 명령·GUI 접속·필드](g1stairs/monitoring/README.md)

```bash
python3 -m g1stairs.monitoring serve
```

## D435i 수집

```bash
docker exec -it -w /opt/g1-edu-loco jsj-camera bash
```

먼저 컨테이너에서 `ros2 topic list -t`로 기존 발행자를 확인합니다. 발행자가 사용하는 DDS 도메인에서 확인해야 합니다. 실제 D435i의 보정된 원본 깊이 영상(`16UC1`)과 짝이 맞는 `CameraInfo`가 이미 있으면 해당 토픽을 구독합니다. `DEPTH_TOPIC`과 `INFO_TOPIC`은 확인한 토픽명, `DEPTH_UNIT_M`은 **그 발행자가 내보내는 픽셀 한 단위당 미터 값**입니다. 두 메시지의 촬영 시각과 광학 좌표계가 일치해야 합니다. [ROS 2 Foxy CameraInfo](https://github.com/ros2/common_interfaces/blob/foxy/sensor_msgs/msg/CameraInfo.msg)

```bash
python3 -m g1stairs.camera record-ros --depth-topic "$DEPTH_TOPIC" --info-topic "$INFO_TOPIC" \
  --depth-scale-m "$DEPTH_UNIT_M" --runs-dir /workspace/jsj-camera/runs --run stairs-01
```

기존 발행자가 카메라를 쓰지 않고 컨테이너에서 D435i에 직접 접근할 수 있으면 아래 SDK 경로를 사용합니다. 첫 명령에서 모델과 지원 프로필을 확인한 후 두 번째 명령을 실행합니다. Unitree 예제의 기본 요청은 640×480, 60 FPS, Z16입니다. 카메라를 확인할 수 없으면 미수신으로 기록합니다. [Unitree Depth Camera Routine](https://support.unitree.com/home/en/G1_developer/depth_camera_instruction)

```bash
python3 -m g1stairs.camera probe
python3 -m g1stairs.camera record --runs-dir /workspace/jsj-camera/runs --run stairs-01
```

## 계단 치수 계산

```bash
docker exec -it -w /opt/g1-edu-loco jsj-footstep-workbench bash
```

카메라에서 완료한 실험의 `depth/`를 동일 실험 이름으로 분석 컨테이너에 전달합니다. [Notion의 ‘컨테이너 사이에 완료된 세션 옮기기’](https://app.notion.com/p/41d3c6661b7d81c7a880f1b5dc0e664c)를 사용합니다. `CALIBRATION`은 현재 촬영 자세에서 측정한 광학 좌표계→중력 정렬 좌표계 보정 파일의 **분석 컨테이너 내부 경로**입니다.

```bash
python3 -m g1stairs.geometry measure --run stairs-01 \
  --runs-dir /workspace/jsj-footstep-workbench/runs --calibration "$CALIBRATION"
```

실제 프레임에는 RealSense SDK의 `rs2_deproject_pixel_to_point`를 적용합니다. 단 높이·디딤면 깊이·관측 폭을 추정하는 부분은 프로젝트 코드입니다. 가려진 경계의 치수는 `null`로 남깁니다. [RealSense 공식 역투영](https://dev.realsenseai.com/docs/projection-in-realsense-sdk-2-0/)

### RealSense Python SDK 확인

D435i 직접 수집과 계단 계산에 사용하는 각 컨테이너 안에서 아래 명령으로 기존 바인딩을 확인합니다. 기존 ROS 2 토픽만 구독하는 경우에는 Foxy의 `rclpy`와 `sensor_msgs`를 사용합니다.

```bash
python3 -c 'import pyrealsense2 as rs; print(rs.__file__)'
```

바인딩이 없을 때만 **해당 컨테이너의 셸에서** Python 3.8 호환 공식 패키지를 설치합니다. [공식 ARM64 휠](https://pypi.org/project/pyrealsense2/2.54.1.5217/#files)

```bash
python3 -m pip install --user --no-cache-dir --only-binary=:all: --no-deps pyrealsense2==2.54.1.5217
```
