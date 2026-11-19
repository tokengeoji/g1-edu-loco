# G1 EDU 전신 상태 대시보드

PC2의 `jsj-g1-tools` 컨테이너에서 Unitree Python SDK2로 `rt/lowstate`를 읽는다. 대시보드는 모터 29개 슬롯과 IMU 상태를 표시하며, 동일한 컨테이너에서 원본 C++ 배터리·모터 온도 모니터도 실행할 수 있다. [컨테이너 설치와 기능 목록](../../../README.md)

## 원본 C++ 온도·배터리 모니터

PC2의 SSH 터미널에서 아래 명령으로 네트워크 인터페이스를 확인한다.

```bash
docker exec jsj-g1-tools g1 interfaces
```

이 문서의 `eth0`는 예시다. 아래 명령에서 `eth0`를 기존 온도 모니터로 로봇 데이터를 수신한 유선 인터페이스 이름으로 바꾼다.

```bash
docker exec -it jsj-g1-tools g1 health eth0
```

C++ 프로그램은 도메인 0에서 `ChannelSubscriber<LowState_>`와 `ChannelSubscriber<BmsState_>`를 생성해 모터 온도와 BMS 상태를 수신한다. 경보 기준과 출력 항목은 [원본 모니터 설명](../../g1_health_monitor/)에서 확인할 수 있다.

## 웹 대시보드와 관절 기록

아래 명령은 PC2의 루프백에서 웹 서버를 연다. 외부 브라우저에서 직접 열 때는 `--bind`에 관측용 PC가 접근할 수 있는 PC2의 LAN 주소를 입력한다. `--nic`은 로봇 DDS에 연결할 NIC를 지정한다.

```bash
docker exec -it jsj-g1-tools g1 monitor serve --nic eth0 --domain 0 --bind 127.0.0.1
```

PC2 브라우저에서 `http://127.0.0.1:8765/`를 연다. `waiting`은 웹 서버가 첫 DDS 샘플을 기다린다는 뜻이다. 별도 터미널에서 같은 NIC로 샘플 한 건을 확인하거나 10초 동안 기록할 수 있다. `stairs-01`을 이번 실험 이름으로 바꾼다. 카메라 기록에도 같은 이름을 쓰면 컨테이너의 `/workspace/runs/<실험 이름>/` 아래에 상태는 `state/`, 깊이 영상은 `depth/`에 저장된다.

```bash
docker exec jsj-g1-tools g1 monitor probe --nic eth0 --domain 0
docker exec jsj-g1-tools g1 monitor record --nic eth0 --domain 0 --run stairs-01 --seconds 10
docker exec jsj-g1-tools g1 monitor inspect --run stairs-01
```

## 공식 SDK 데이터와 표시 항목

| 항목 | 근거 |
| --- | --- |
| 발행 메시지 | 공식 Python SDK의 `ChannelFactoryInitialize`, `ChannelSubscriber`와 `unitree_hg.msg.dds_.LowState_`를 사용한다. |
| 관절·IMU | `q`, `dq`, `tau_est`, `imu_state`와 모터 온도 배열을 읽는다. SDK의 온도 배열 0은 외함, 1은 권선이다. |
| 관절 이름 | 공식 G1 예제의 인덱스 0–28과 `mode_pr`의 PR/AB 표현을 따른다. EDU 23자유도·허리 잠금 모델의 인덱스 13/14 등은 실제 관절 구성과 대조한다. |
| 수신 시간·상태 | 수신 시각, 샘플 간격, `live`·`stale`은 모니터가 PC2의 단조 시계로 계산한다. |

[공식 SDK의 채널 구현](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/unitree_sdk2py/core/channel.py) · [G1 관절 인덱스와 LowState 수신 예제](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/example/g1/low_level/g1_low_level_example.py) · [온도 배열 정의](https://github.com/unitreerobotics/unitree_sdk2/blob/aaf69cb56c9d5ed63d8b284008ec3a8ab999bec1/include/unitree/robot/g1/common/terminations.hpp)
