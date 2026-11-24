# G1 EDU 전신 상태 대시보드

PC2의 `jsj-g1-tools` 컨테이너에서 Unitree Python SDK2로 `rt/lowstate`를 읽는다. 대시보드는 모터 29개 슬롯과 IMU 상태를 표시하며, 동일한 컨테이너에서 원본 C++ 배터리·모터 온도 모니터도 실행할 수 있다. [컨테이너 설치와 기능 목록](../../../README.md)

## 원본 C++ 온도·배터리 모니터

G1-EDU PC2에서 실행 중인 `jsj-g1-tools`에 접속한다. 아래 예시의 `eth0`는 로봇 데이터를 받는 실제 유선 인터페이스 이름으로 바꾼다.

**G1 호스트 · 터미널 1**

```bash
docker exec -it jsj-g1-tools bash
```

**컨테이너 내부 · 터미널 1**

```bash
g1 interfaces
g1 health eth0
```

C++ 프로그램은 도메인 0에서 `ChannelSubscriber<LowState_>`와 `ChannelSubscriber<BmsState_>`로 모터와 BMS 상태를 수신한다. 첫 출력 후 10초마다 최신 샘플로 온도와 경보 단계를 갱신한다. 다른 도구를 함께 쓸 때는 이 모니터를 켜 두고, 실험이 끝나면 `Ctrl+C`로 종료한다. [원본 모니터 설명](../../g1_health_monitor/)

## 웹 대시보드와 관절 기록

두 번째 SSH 터미널에서 같은 컨테이너에 접속한다. 대시보드의 `--nic`은 로봇 DDS에 연결할 NIC, `--bind`는 웹 서버가 응답할 PC2 주소다.

**G1 호스트 · 터미널 2**

```bash
docker exec -it jsj-g1-tools bash
```

**컨테이너 내부 · 터미널 2**

```bash
g1 monitor serve --nic eth0 --domain 0 --bind 127.0.0.1
```

PC2 브라우저에서 `http://127.0.0.1:8765/`를 연다. `waiting`은 웹 서버가 첫 DDS 샘플을 기다린다는 뜻이다.

세 번째 SSH 터미널에서 수신 샘플 한 건을 확인하거나 10초 동안 기록할 수 있다. `stairs-01`을 새 실험 이름으로 바꾼다. 카메라 기록에도 같은 이름을 쓰면 컨테이너의 `/workspace/runs/<실험 이름>/` 아래에 상태는 `state/`, 깊이 영상은 `depth/`에 저장된다.

**G1 호스트 · 터미널 3**

```bash
docker exec -it jsj-g1-tools bash
```

**컨테이너 내부 · 터미널 3**

```bash
g1 monitor probe --nic eth0 --domain 0
g1 monitor record --nic eth0 --domain 0 --run stairs-01 --seconds 10
g1 monitor inspect --run stairs-01
```

## 보행 요청과 첫 다리 움직임의 시간 비교

**컨테이너 내부 · 조작 터미널과 별도의 기록 터미널**

```bash
g1 monitor record --with-teleop --nic eth0 --domain 0 --run "first-step-$(date +%Y%m%d-%H%M%S)" --seconds 30
```

이 명령은 구독만 한다. 구독 시작 안내가 뜨면 정지 자세부터 기록할 수 있다. 지정한 시간이 지나면 `/workspace/runs/<실험 이름>/state/`에 두 파일을 저장한다. `samples.jsonl`의 `imu.rpy[1]`은 IMU 피치(rad), `joints[0:12]`의 `q_rad`는 양다리의 실측 관절각이다. 두 파일의 `host_rx_monotonic_ns`는 같은 PC2 단조 시계로 잰 수신 시각이다. 명령 전후를 비교할 때는 두 파일이 함께 기록된 구간을 사용한다.

`teleop.jsonl`의 `topic`은 출처다. `rt/api/sport/request`와 `rt/api/loco/request`에서는 7105 요청의 `request_id`, `api_id`, `velocity`(전후 m/s, 좌우 m/s, 회전 rad/s), `duration`(초)을 입력값 그대로 기록한다. 속도 세 값이 모두 0이면 정지 요청이다. `rt/sportmodestate`에서는 처음 수신한 `fsm_id`·`fsm_mode`와 이후 값이 달라진 표본을 기록한다. 요청 시각, 정적·동적 상태 전환, IMU 기울기, 관절각 변화를 대조할 수 있다. 실제 키 누름·서비스 응답·발 접촉 시각은 이 파일에 포함되지 않는다. [공식 속도 요청](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/unitree_sdk2py/g1/loco/g1_loco_client.py#L70-L78) · [공식 HG 보행 상태 형식](https://github.com/unitreerobotics/unitree_sdk2/blob/aaf69cb56c9d5ed63d8b284008ec3a8ab999bec1/include/unitree/idl/hg/SportModeState_.hpp)

`manifest.json`의 `teleop_trace`에는 구독 준비·종료 시각, 토픽별 수신·기록·큐 누락·해석 불가 건수, 최초·마지막 수신 시각, 최대 수신 간격, 관측 건수가 0인 토픽이 들어간다. 서비스 요청의 수신 건수는 7105만 센다. 한 서비스만 사용한 시험에서는 나머지 서비스에 0건이 표시될 수 있다. DDS에서 관측되지 않은 요청 수는 알 수 없다.

### 내비게이션은 걷고 텔레옵에서는 첫발이 나오지 않을 때

같은 기체의 평지 출발을 비교하려면 위 읽기 전용 기록기를 내비게이션과 텔레옵에 각각 실행해 서로 다른 `--run` 이름으로 저장한다. 내비게이션을 기록할 때는 실기체 텔레옵을 종료해 둔다. 각 기록에 시작 자세, 사용한 조작 방식, 눈으로 확인한 첫발을 적고, 텔레옵은 실행한 커밋과 실제 키(`i` 또는 `↑`), 한 번 누름·길게 누름 여부도 적는다.

1. 두 기록에서 첫 `fsm_id`와 `fsm_mode`를 확인하고, 첫 동적 상태 전환 전후의 IMU 피치와 다리 관절각을 비교한다.
2. 속도 요청이 보이는 경로에서는 전후·좌우·회전 인자, 유효시간, 요청 간격, 처음 속도 0이 들어간 시점을 비교한다. 순수 직진과 회전을 섞은 출발은 따로 비교한다.
3. Unitree의 목표점 내비게이션은 외부에서 `slam_operate` 서비스의 1102로 목표 자세를 받는다. 위 기록기가 구독하는 속도 요청은 7105다. 내비게이션이 걸어도 7105가 관측되지 않으면 그 기록으로는 내부 속도와 명령 주기를 알 수 없다. 이 경우 보행 상태와 실측 관절각을 비교한다. [공식 내비게이션 인터페이스](https://support.unitree.com/home/en/G1_developer/slam_navigation_services_interface) · [기존 텔레옵 실측](../../../docs/teleop-802-evidence.md)

## 공식 SDK 데이터와 표시 항목

| 항목 | 근거 |
| --- | --- |
| 발행 메시지 | 공식 Python SDK의 `ChannelFactoryInitialize`, `ChannelSubscriber`와 `unitree_hg.msg.dds_.LowState_`를 사용한다. |
| 관절·IMU | 각 상태 샘플에서 `q`, `dq`, `tau_est`와 IMU 자세·각속도·가속도를 읽는다. |
| 온도 | 연속 기록과 실시간 대시보드는 첫 샘플에서 모터 외함·권선과 IMU 온도를 읽고, 이후 10초 이상 지난 첫 샘플에서 갱신한다. 그 사이 샘플은 마지막 온도와 해당 샘플의 수신 시각(`temperature_host_rx_monotonic_ns`)을 함께 표시·기록한다. |
| 관절 이름 | 공식 G1 예제의 인덱스 0–28과 `mode_pr`의 PR/AB 표현을 따른다. EDU 23자유도·허리 잠금 모델의 인덱스 13/14 등은 실제 관절 구성과 대조한다. |
| 수신 시간·상태 | 수신 시각, 샘플 간격, `live`·`stale`은 모니터가 PC2의 단조 시계로 계산한다. |

[공식 SDK의 채널 구현](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/unitree_sdk2py/core/channel.py) · [G1 관절 인덱스와 LowState 수신 예제](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/example/g1/low_level/g1_low_level_example.py) · [온도 배열 정의](https://github.com/unitreerobotics/unitree_sdk2/blob/aaf69cb56c9d5ed63d8b284008ec3a8ab999bec1/include/unitree/robot/g1/common/terminations.hpp)
