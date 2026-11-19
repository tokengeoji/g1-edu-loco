# G1 EDU 전신 상태와 온도

Unitree Python SDK2에서 `unitree_hg/msg/dds_/LowState_` 타입의 `rt/lowstate`를 읽는다. 브라우저로 실시간 확인하거나 JSONL 기록을 열어 샘플을 탐색할 수 있다. 아래 Python 명령은 PC2의 `jsj-monitor` Docker 컨테이너 내부 `/opt/g1-edu-loco`에서 실행한다. [공식 Basic Motion Routine](https://support.unitree.com/home/en/G1_developer/basic_motion_routine)

## 합성 데이터로 확인

```bash
python3 -m g1stairs.monitoring fixture --run monitor-demo
python3 -m g1stairs.monitoring inspect --run monitor-demo
python3 -m g1stairs.monitoring serve --run monitor-demo
```

브라우저에서 [http://127.0.0.1:8765](http://127.0.0.1:8765)에 접속한다. `--runs-dir`의 기본값은 현재 작업 디렉터리의 `runs`다.

## G1 EDU 연결

실제 기체와 같은 네트워크의 NIC 이름과 DDS 도메인, 기체 설정에 맞는 프로필을 사용한다. 선택 가능한 프로필은 `g1-29`, `g1-29-waist-locked`, `g1-23`이다. 장비 구성을 실측하거나 기존 설정에서 확인한다. 실행 환경에 공식 Unitree SDK2 Python과 해당 SDK가 요구하는 CycloneDDS를 설치한다. [SDK 설치 안내](https://github.com/unitreerobotics/unitree_sdk2_python#installation)

```bash
python3 -m g1stairs.monitoring probe --nic "$G1_NIC" --domain "$G1_DDS_DOMAIN" --profile "$G1_PROFILE"
python3 -m g1stairs.monitoring record --nic "$G1_NIC" --domain "$G1_DDS_DOMAIN" --profile "$G1_PROFILE" --run "$RUN_ID" --seconds 10
python3 -m g1stairs.monitoring serve --nic "$G1_NIC" --domain "$G1_DDS_DOMAIN" --profile "$G1_PROFILE"
```

브라우저 서버의 기본 바인드는 `127.0.0.1`이다. Linux 브리지 컨테이너에서 포트를 전달할 경우 컨테이너의 앱에는 `--bind 0.0.0.0`을, Docker 호스트에는 `127.0.0.1:8765:8765` 포트 매핑을 사용한다. Linux 호스트 네트워크로 DDS를 사용할 경우 실제 NIC와 기존 도메인을 확인한다.

## 기록 필드

- `runs/<run_id>/state/samples.jsonl`과 함께 같은 디렉터리에 `manifest.json`을 저장한다. SDK 콜백 도착 시점의 `host_rx_monotonic_ns`, DDS 원본 `tick`, PR/AB 모드와 모터 상태, 전신 관절·IMU를 기록한다. 콜백 도착 시각과 센서의 측정 시각에는 차이가 있을 수 있다.
- 관절 ID는 Unitree 예제의 숫자 매핑을 사용한다. PR은 발목 Pitch/Roll, AB는 A/B 구동기 값을 나타낸다. 확인되지 않은 모드에 해당하는 슬롯은 숫자 이름으로 남긴다. [공식 관절 매핑 예제](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/example/g1/low_level/g1_low_level_example.py)
- 모터 온도 배열의 0번은 케이싱, 1번은 권선이다. 토크는 SDK 추정값이다. IMU의 쿼터니언은 SDK 순서인 WXYZ로 보존하며 RPY·가속도·자이로는 SDK 숫자를 그대로 기록한다. [온도 필드](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/g1/common/terminations.hpp) · [IMU 표시 예제](https://github.com/unitreerobotics/unitree_ros2/blob/master/example/src/src/g1/lowlevel/g1_low_level_example.cpp)
- 기록 종료 직전의 무수신 구간과 앱의 큐 오버플로를 manifest에 남긴다. 실시간 대시보드의 지연 표시는 SDK 마지막 콜백 이후의 경과 시간이다.
