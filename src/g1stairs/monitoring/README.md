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

C++ 프로그램은 도메인 0에서 `ChannelSubscriber<LowState_>`와 `ChannelSubscriber<BmsState_>`를 생성해 모터 온도와 BMS 상태를 수신한다. 다른 도구를 함께 쓸 때는 이 모니터를 켜 두고, 실험이 끝나면 `Ctrl+C`로 종료한다. [원본 모니터 설명](../../g1_health_monitor/)

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

## 공식 SDK 데이터와 표시 항목

| 항목 | 근거 |
| --- | --- |
| 발행 메시지 | 공식 Python SDK의 `ChannelFactoryInitialize`, `ChannelSubscriber`와 `unitree_hg.msg.dds_.LowState_`를 사용한다. |
| 관절·IMU | `q`, `dq`, `tau_est`, `imu_state`와 모터 온도 배열을 읽는다. SDK의 온도 배열 0은 외함, 1은 권선이다. |
| 관절 이름 | 공식 G1 예제의 인덱스 0–28과 `mode_pr`의 PR/AB 표현을 따른다. EDU 23자유도·허리 잠금 모델의 인덱스 13/14 등은 실제 관절 구성과 대조한다. |
| 수신 시간·상태 | 수신 시각, 샘플 간격, `live`·`stale`은 모니터가 PC2의 단조 시계로 계산한다. |

[공식 SDK의 채널 구현](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/unitree_sdk2py/core/channel.py) · [G1 관절 인덱스와 LowState 수신 예제](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/example/g1/low_level/g1_low_level_example.py) · [온도 배열 정의](https://github.com/unitreerobotics/unitree_sdk2/blob/aaf69cb56c9d5ed63d8b284008ec3a8ab999bec1/include/unitree/robot/g1/common/terminations.hpp)
