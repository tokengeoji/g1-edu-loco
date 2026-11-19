# G1 EDU loco

Unitree G1 EDU의 전신 상태를 기록하고, 헤드 RealSense D435i의 Depth로 계단의 관측된 치수를 계산합니다.

| Docker Hub 태그 | PC2 컨테이너 | 기능 |
| --- | --- | --- |
| `jsj/iiclab:realsense` | `jsj-camera` | D435i Depth 원본 수집·재생 |
| `jsj/iiclab:monitoring` | `jsj-monitor` | G1 `rt/lowstate` 구독, 전신 관절·IMU·모터 온도 기록 및 GUI |
| `jsj/iiclab:geometry` | `jsj-footstep-workbench` | 실기 Depth에서 높이·디딤면 깊이·관측 폭 계산 |

## PC2에서 이미지 받기

표는 게시 대상입니다. 관리자가 해당 태그가 Docker Hub에 게시됐음을 확인한 뒤 PC2의 SSH 터미널에서 사용할 이미지를 받습니다. [이미지 빌드·게시 절차](docs/publish.md)

```bash
docker pull jsj/iiclab:realsense
docker pull jsj/iiclab:monitoring
docker pull jsj/iiclab:geometry
```

실행할 기능만 선택합니다. 기존에 같은 이름의 컨테이너가 있다면 `docker container inspect`로 이미지와 장치 접근 설정을 확인합니다. 기존 컨테이너에는 실험 기록이 남을 수 있습니다. 코드는 `/opt/g1-edu-loco`, 실험 기록은 컨테이너 쓰기 레이어에 둡니다. PC2 호스트에 저장소 복제, 패키지 설치 또는 사용자 지정 마운트를 추가할 필요가 없습니다.

## 실기 연결 확인

### RealSense D435i

[Unitree Depth Camera Routine](https://support.unitree.com/home/en/G1_developer/depth_camera_instruction)은 헤드 카메라를 RealSense D435i로 명시하고, librealsense 2.54.1 예제에서 Depth를 640×480, 60 FPS, `RS2_FORMAT_Z16`으로 요청합니다. `Z16` 픽셀 값에 SDK에서 읽은 깊이 스케일을 곱하면 미터 값이 됩니다. [RealSense SDK 2.0의 Depth 인코딩·좌표계](https://dev.realsenseai.com/docs/projection-in-realsense-sdk-2-0/)

PC2에서 D435i와 연결할 때는 기존에 승인된 카메라 접근 구성으로 `jsj-camera`를 실행합니다. `probe` 출력에서 D435i와 실제 지원 프로필을 확인합니다. 목록이 비어 있거나 녹화가 실패하면 실기 수신 미확인으로 남깁니다. 카메라가 이미 다른 프로그램에서 열려 있으면 기존 프로그램을 건드리지 않고 운영자에게 확인합니다.

```bash
docker exec jsj-camera python3 -m g1stairs.camera probe
docker exec jsj-camera python3 -m g1stairs.camera record \
  --runs-dir /workspace/jsj-camera/runs --run "$RUN_ID" --seconds 10
docker exec jsj-camera python3 -m g1stairs.camera replay \
  --runs-dir /workspace/jsj-camera/runs --run "$RUN_ID"
```

기본값은 공식 예제 프로필입니다. 실제 장치가 지원하는 다른 규격을 쓸 때는 `record --width … --height … --fps …`로 지정합니다. `replay`에서 `source=realsense`, 실제 프레임 수, 깊이 스케일과 유효 픽셀 비율을 확인합니다.

### 전신 상태와 모터 온도

새 모니터링 컨테이너가 필요할 때 Linux 호스트 네트워크로 실행합니다. 실제 NIC·DDS 도메인·기체 관절 프로필을 지정하고 `rt/lowstate` 첫 패킷과 수신률을 확인합니다. [Unitree G1 Basic Motion Routine](https://support.unitree.com/home/en/G1_developer/basic_motion_routine) · [모니터링 가이드](g1stairs/monitoring/README.md)

```bash
docker run -d --name jsj-monitor --pull never --network host \
  --ipc private --cap-drop ALL --security-opt no-new-privileges:true \
  jsj/iiclab:monitoring
docker exec jsj-monitor python3 -m g1stairs.monitoring probe \
  --nic "$G1_NIC" --domain "$G1_DDS_DOMAIN" --profile "$G1_PROFILE"
docker exec jsj-monitor python3 -m g1stairs.monitoring record \
  --nic "$G1_NIC" --domain "$G1_DDS_DOMAIN" --profile "$G1_PROFILE" \
  --runs-dir /workspace/jsj-monitor/runs --run "$RUN_ID" --seconds 10
docker exec jsj-monitor python3 -m g1stairs.monitoring inspect \
  --runs-dir /workspace/jsj-monitor/runs --run "$RUN_ID"
```

같은 실험에는 같은 `RUN_ID`를 지정합니다. `inspect`에서 `source=unitree`, 기록 개수, 관절·IMU·두 온도 값, 수신 공백과 누락을 확인합니다. 웹 GUI는 모니터링 가이드의 `serve`로 띄웁니다.

### 계단 형상

계단을 바라보며 실제 D435i로 수집한 Depth 기록을 `jsj-footstep-workbench`의 `/workspace/jsj-footstep-workbench/runs/$RUN_ID/depth`로 옮깁니다. [Notion의 컨테이너 간 전달 안내](https://app.notion.com/p/41d3c6661b7d81c7a880f1b5dc0e664c)에 있는 Docker 표준입출력 절차를 사용합니다. 현장에서 측정한 광학 좌표계→중력 정렬 좌표계 보정 파일을 분석 컨테이너 안에 둡니다.

```bash
docker run -d --name jsj-footstep-workbench --pull never --network none \
  --ipc private --cap-drop ALL --security-opt no-new-privileges:true \
  jsj/iiclab:geometry
docker exec jsj-footstep-workbench python3 -m g1stairs.geometry measure \
  --runs-dir /workspace/jsj-footstep-workbench/runs --run "$RUN_ID" \
  --calibration "$G1_CALIBRATION_IN_CONTAINER"
```

실측 계단 치수와 결과를 비교합니다. 카메라가 확인하지 못한 경계의 길이·폭은 `null`로 기록합니다. 현재 보정은 고정된 촬영 자세를 기준으로 합니다. [RealSense SDK 3D 측정 예제](https://github.com/realsenseai/librealsense/blob/master/examples/measure/readme.md)
