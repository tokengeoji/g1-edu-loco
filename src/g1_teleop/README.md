<!-- Author: Codex (IIC) -->
# 키보드 텔레옵

PC2의 상시 컨테이너 `jsj-g1-tools`에서 실행한다. 키보드는 G1의 내장 고수준 보행기에 모드와 속도를 요청한다. 사용자 보행 정책, 관절 PD 제어 또는 학습 코드는 별도 보행 프로젝트에서 다룬다. [컨테이너 빌드와 시작](../../README.md) · [실기체 운영 규칙](../../AGENTS.md)

## 키 입력 연습

```bash
docker exec -it jsj-g1-tools g1 teleop --dry-run
```

연습 중에는 Unitree 통신을 초기화하지 않는다. 모의 초기 상태는 잠금 기립(FSM 4)이다. `r` → `2` → 확인 문구가 뜨면 `Enter` → `f` 순서로 `FSM=500`을 확인한다. `w`를 짧게 눌러 전진 속도와 이어지는 0 명령을 확인하고 `x`로 종료한다. 한 키씩 직접 입력한다.

## 상태 모니터와 실기체 텔레옵

PC2의 각 SSH 터미널에서 이 기체의 로봇 네트워크 인터페이스를 입력한다. 정상 동작한 모니터의 NIC와 일치하는지 확인할 수 있다.

```bash
docker exec jsj-g1-tools ip -br -4 addr
read -rp '로봇 네트워크 NIC: ' G1_IFACE
```

첫 번째 터미널에서 원본 C++ 모니터를 켜 둔다.

```bash
docker exec -it jsj-g1-tools g1 health "$G1_IFACE"
```

모니터는 도메인 **0**의 `rt/lowstate`와 `rt/lf/bmsstate`를 구독한다. 최신 모터·배터리 샘플, 온도와 통신 상태를 확인한다. `no BMS message`는 배터리 값 미수신을 뜻한다. 경보가 울리면 운영자가 현장 정지 절차를 수행한다. [원본 모니터](../g1_health_monitor/)

두 번째 터미널에도 NIC를 입력한 뒤 보행 서비스에 상태를 조회한다. 정상 응답에는 현재 `FSM`, NIC, 도메인, 응답한 `sport` 또는 `loco`가 표시된다. 기체의 보행 서비스가 다른 도메인을 사용한다고 확인했으면 `--domain` 값을 변경한다.

```bash
read -rp '모니터에서 확인한 로봇 NIC: ' G1_IFACE
docker exec jsj-g1-tools g1 teleop --status --interface "$G1_IFACE" --domain 0
```

첫 실기체 동작은 숙련자 입회하에 진행한다. 모니터의 온도·배터리 상태, 기체 지지, 주변 공간을 확인하고 물리 조종기를 손에 둔다. 앱에서 고수준 `ai_sport`가 활성화되어 있어야 한다. 실기체 키보드 제어는 같은 컨테이너에서 한 세션만 열리며, 상태 조회·온도 측정·카메라는 동시에 사용할 수 있다.

```bash
docker exec -it jsj-g1-tools g1 teleop --live --interface "$G1_IFACE" --domain 0
```

`f`로 현재 FSM을 조회하고 `r`로 키보드를 활성화한다. 이미 `500`이면 모드를 다시 요청할 필요가 없다. 다른 상태에서는 기체 자세와 공식 전환 절차를 먼저 확인한다. `2`와 `Enter`로 기본 보행을 요청한 다음 `f`로 실제 FSM 500 진입을 확인한다. 허리 3자유도 모델임을 확인했으면 실행 명령에 `--waist-3dof`를 추가해 보행 FSM 501을 사용할 수 있다.

## 키 배치

| 키 | 로봇에 요청하는 동작 |
| --- | --- |
| `r` / `g` / `f` | 키보드 활성화 / 제어 해제 / 현재 FSM 조회 |
| `w`·`s` 또는 `↑`·`↓` | 전진·후진, 기본 0.15 m/s |
| `a`·`d` | 좌·우 옆걸음, 기본 0.10 m/s |
| `q`·`e` 또는 `←`·`→` | 좌·우 회전, 기본 0.30 rad/s |
| `+` / `-` | 다음 이동의 속도 배율 조절, 기본 1배, 범위 0.5~2배 |
| `Space` / `x` | 보행 속도 0 요청 / 프로그램 종료 |
| `2` / `8` + 각각 `Enter` | 기본 보행(FSM 500) / 허리 3자유도 보행(501, 옵션 필요) |
| `4` / `5` + 각각 `Enter` | 보행 중 안정되면 제자리걸음 해제 / 속도 0에서도 계속 제자리걸음 |
| `6` + `Enter` | 균형 쪼그림↔기립 전환(706). 현재 자세를 눈으로 확인한 후 재활성화 |
| `1` / `3` / `9` + 각각 `Enter` | 잠금 기립(4) / 위치 제어 쪼그림(2) / 의자 앉기(3). 기체 지지와 의자 위치 등 자세별 조건 확인 |
| `0` + `Enter` | 감쇠(1). 균형을 잃을 수 있으므로 기체 지지 확인 |
| `Esc` / `?` | 선택 취소 / 키 도움말 |

숫자 명령에는 4초 이내의 별도 `Enter`가 필요하다. 이동 키를 반복 수신하는 동안에만 최대 0.25초의 속도 명령을 갱신한다. 터미널은 키를 뗀 시각을 보내지 않으므로 자동 반복이 늦으면 처음 눌렀을 때 잠깐 멈출 수 있다. 통신 오류가 발생하면 키보드 제어를 해제하고 응답 코드를 표시한다. **Space는 이동 속도를 0으로 요청한다.** 자세 복원이나 물리적 비상 정지를 보장하지 않는다. 비상 상황에서는 현장 조종기와 해당 기체의 공식 절차를 따른다.

## 공식 SDK 연결

실기체 프로그램은 Unitree의 `ChannelFactoryInitialize`와 `LocoClient`를 사용한다. 현재 서비스에는 공식 `LocoClient()`를 사용한다. 구형 서비스 이름에만 공식 RPC `Client`의 생성자에서 `loco`를 지정한다. `Init`, `GetFsmId`, `SetFsmId`, `SetVelocity`, `SetBalanceMode`와 요청 직렬화는 양쪽 모두 설치된 공식 SDK 구현을 사용한다. 키 배치, 입력 만료 시간과 실행 잠금은 이 프로젝트의 조작 기능이다. [Unitree의 서비스 이름 변경 커밋](https://github.com/unitreerobotics/unitree_sdk2_python/commit/60e8358bcf68a785c628096760fbfc941d9a44a9) · [공식 G1 LocoClient](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/unitree_sdk2py/g1/loco/g1_loco_client.py)

## 원본에서 확인한 문제와 진단 기준

| 실제 증상 또는 원본 동작 | 확인한 원인과 적용한 조치 |
| --- | --- |
| 배터리·온도는 보이는데 보행 서비스가 응답하지 않음 | 모니터는 DDS 상태를 구독하지만 보행은 왕복 RPC 응답이 필요하다. 원본에 고정된 SDK는 `sport`를 사용한다. 공식 가이드상 `ai_sport` 8.2.0.0 이상은 `sport`, 이전 버전은 `loco`다. 시작할 때 `GetFsmId`만으로 두 이름을 확인하고 응답한 하나를 해당 세션에 고정한다. `--service sport` 또는 `--service loco`로 한쪽만 진단할 수도 있다. |
| 원본이 `ARMED`라고 표시하지만 움직이지 않음 | 원본은 첫 FSM 조회가 실패해도 진행하고, 실제 보행 모드 확인 없이 키보드를 활성화한다. 새 구현은 조회 실패 시 시작을 중단하고, 방향 입력 때마다 실제 보행 FSM을 확인한다. 모드 요청이 수락돼도 기체가 전환을 보류할 수 있으므로 요청값과 재조회값을 구분한다. |
| 양쪽 서비스가 모두 실패 | 출력된 NIC·도메인·각 RPC 오류를 확인한다. 이미 모니터에서 검증한 NIC와 도메인 0부터 대조하고 앱에서 고수준 서비스 상태, 저수준 제어 점유 여부를 확인한다. 오류 코드만으로 원인을 단정하지 않는다. |
| SSH·Docker에서 타이핑해도 반응이 없음 | 키보드 세션에는 대화형 TTY(`docker exec -it`, 원격 명령식 SSH는 `ssh -t`)가 필요하다. 새 프로그램은 TTY가 없으면 시작 전에 사용법을 출력한다. |
| PC2에서 원본 Docker 베이스 생성 실패 | 참고 저장소의 `osrf/ros:foxy-desktop` 태그는 linux/amd64만 제공한다. PC2는 linux/arm64이므로 프로젝트의 Canonical ARM64 Ubuntu 기반 로컬 이미지 `g1-jsj:base`를 사용한다. 이전 실패 로그가 없어 실제로 어느 단계에서 실패했는지는 미확인이다. |

계단 모드용 키는 지정 자료에서 이 기체에 사용할 공개 RPC와 FSM 번호를 확인하면 추가할 수 있다. 기체별 통신 오류는 `--status`에 표시된 서비스와 반환 코드로 확인한다.

## 검증한 범위

- 원본 모니터의 CMake, C++ 소스, README를 참고 저장소 커밋 `0f76100`과 Git 객체 단위로 대조했다. 고정 C++ SDK `aaf69cb`와 GCC 9.3으로 Ubuntu 20.04 ARM64용 모니터와 원본 텔레옵을 빌드했다. QEMU에서 모의 모터 29축·배터리 입력과 경보 5단계를 검증했다.
- 원본 텔레옵의 모의 실행에서는 FSM이 미확인 값 `-1`이어도 키보드가 `ARMED`로 표시되는 현상을 재현했다. 새 구현은 키 입력과 터미널 복구, 상태 조회 실패, 지연 응답과 명령 만료를 회귀 테스트로 확인했다.
- 실제 Unitree Python SDK `814556d`와 Cyclone DDS 0.10.2를 사용했다. 외부 네트워크가 차단된 프로세스 내부의 모의 서버에서 `sport`와 `loco` 각각에 대해 FSM 4→500, 전진 0.15 m/s, Space로 속도 0이 도착하는 것을 확인했다. 두 서비스가 모두 없을 때 상태 조회는 코드 3102를 출력하고 종료했다.
- 실제 PC2 Docker 빌드, 기체 유선망 응답과 실보행은 현장 확인 항목이다.

[원본 텔레옵](https://github.com/duckptr/g1-edu-tools/blob/0f761000a0b78d9437f9d7166f41725a5924e441/g1_teleop/g1_teleop.cpp) · [Unitree 고수준 RPC 예제](https://support.unitree.com/home/en/G1_developer/rpc_routine) · [Unitree 고수준 보행 API](https://support.unitree.com/home/en/G1_developer/sport_services_interface) · [공식 Python LocoClient](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/unitree_sdk2py/g1/loco/g1_loco_client.py)
