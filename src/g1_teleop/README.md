<!-- Author: Codex (IIC) -->
# G1-EDU 키보드 텔레옵

PC2의 통합 컨테이너 `jsj-g1-tools`에서 Unitree 고수준 보행기를 조작한다. 이 기체에서 관측한 **FSM 802를 기본 이동 모드**로 쓴다. Unitree 문서의 명칭은 Run Mode다. [컨테이너 생성·시작](../../README.md#pc2) · [IIC 실기체 운영 규칙](../../AGENTS.md)

## 실행

`jsj-g1-tools`가 실행 중인 G1-EDU PC2에서 SSH 터미널 두 개를 사용한다. 첫 번째 터미널은 온도·배터리 모니터용, 두 번째 터미널은 키보드 조작용이다. 두 터미널 모두 같은 컨테이너에 접속한다.

**G1 호스트 · 터미널 1**

```bash
docker exec -it jsj-g1-tools bash
```

**컨테이너 내부 · 터미널 1**

```bash
g1 interfaces
g1 health eth0
```

`eth0`는 예시다. 실제 G1 연결용 유선 NIC 이름으로 바꾸고, 모터 온도와 배터리 데이터가 새로 들어오는지 확인한다. 조작하는 동안 모니터를 켜 둔다.

**G1 호스트 · 터미널 2**

```bash
docker exec -it jsj-g1-tools bash
```

**컨테이너 내부 · 터미널 2**

```bash
g1 teleop --dry-run
```

오프라인 연습은 FSM 802에서 시작한다. `w`로 전진 요청값, `Space`로 속도 0을 확인하고 `x`로 연습을 끝낸다. 같은 셸에서 모니터가 정상 수신한 NIC와 도메인 0으로 기체의 실제 FSM과 응답한 서비스(`sport` 또는 `loco`)를 조회한다.

**컨테이너 내부 · 터미널 2**

```bash
g1 teleop --status --interface eth0 --domain 0
```

첫 실기체 동작은 숙련자 입회하에 기체 지지, 물리 조종기, 모터·배터리 상태를 확인하고 진행한다. FSM 802에서는 내장 보행기가 팔을 흔들 수 있다. 팔 고정이 필요한 실험은 아래 실기체 조작을 시작하기 전에 이 제약을 확인한다. 같은 컨테이너에서 실기체 텔레옵은 한 세션만 실행한다.

**컨테이너 내부 · 터미널 2**

```bash
g1 teleop --live --interface eth0 --domain 0
```

텔레옵에서 `f`로 현재 FSM을 읽는다. **이미 802면 첫 `w`가 전진 명령**이다. 다른 모드에서는 `2`를 누른 뒤 4초 이내에 `Enter`를 눌러 802를 요청한다. 실제 FSM이 802로 조회되어야 해당 모드에서 이동한다. 모드와 속도 상한은 조작자가 해당 키를 눌렀을 때만 변경한다.

## 이동과 속도

| 키 | 동작 |
| --- | --- |
| `w` / `s` 또는 `↑` / `↓` | 전진 / 후진, 기본 0.15 m/s |
| `a` / `d` | 좌 / 우 옆걸음, 기본 0.10 m/s |
| `q` / `e` 또는 `←` / `→` | 좌회전 / 우회전, 기본 0.30 rad/s |
| `+` / `-` | 다음 이동 속도의 배율을 0.25씩 조절. 기본 1배, 범위 0.5~2배 |
| `!` / `@` / `#` / `$` | 802에서 공식 `SetSpeedMode(0…3)` 호출. Run Mode의 전진 속도 상한은 각각 1.0, 2.0, 2.7, 3.0 m/s |
| `Space` / `x` | 이동 속도 0 요청 / 텔레옵 종료 |
| `f` / `?` | 실제 FSM 조회 / 키 목록 |

각 방향 입력은 최대 0.25초간 유효하다. 계속 이동하려면 키를 반복 입력한다. 속도 상한을 바꿔도 현재 속도 배율은 유지된다. 기본 상태에서 `+` 한 번 후 `w`는 0.1875 m/s를 요청한다.

## 텔레옵에서 모드 변경

원하는 키를 한 번 누른 뒤 선택 내용이 표시되면 4초 안에 `Enter`를 누른다. `Esc`로 취소할 수 있다. 요청 뒤 화면에 표시되는 실제 FSM과 기체 자세를 확인한다.

| 키 → Enter | SDK에 요청하는 모드 |
| --- | --- |
| **`2`** | **이 기체의 우선 이동 모드. `SetFsmId(802)`** |
| `m` | 일반 보행 Walk Motion(500)을 명시적으로 선택. `2`로 802 복귀 |
| `8` | 허리 3자유도 보행(501). 해당 모델을 확인하고 실행 옵션 `--waist-3dof`를 지정한 경우 |
| `1` / `3` | 잠금 기립(4) / 위치 제어 쪼그림(2). 균형 제어가 없어 기체 지지 필요 |
| `6` | 균형 쪼그림과 기립 간 전환(706). 전환 후 현재 자세를 직접 확인 |
| `7` 또는 `9` | 의자에 앉기(3). 의자 위치와 기체 지지 확인 |
| `0` | 댐핑(1). 기체가 자세를 유지하지 못하므로 지지 확인 |
| `4` / `5` | 500/501에서 `SetBalanceMode(0/1)`. 안정 시 제자리걸음 해제 / 속도 0에서도 계속 제자리걸음 |

**802에서의 팔 동작.** 텔레옵은 팔 관절, 제스처, 저수준 명령을 보내지 않는다. 내장 보행기가 팔을 흔들 수 있으며 802에서 양팔을 고정하는 공식 기능은 확인되지 않았다. Unitree의 XR 상체 제어 예제는 보행과 병행할 수 있는 모드를 Regular로 명시한다. [Unitree XR 지원 모드](https://github.com/unitreerobotics/xr_teleoperate#32-parameter-description)

## 온도는 수신되는데 보행이 되지 않았던 이유

`kmj` 현장 기록에는 당시 PC2 프로그램의 활성화 조건이 500이었고 실제 FSM은 802였다고 적혀 있다. 당시 참고 C++ 소스는 기본 보행에 `Start()`를 호출한다. 공식 SDK의 `Start()`는 500을 요청한다. 현재 구현은 `2`에서 802를 직접 요청하고 기체의 응답을 다시 읽는다. [현장 진단 기록](https://github.com/tokengeoji/g1-edu-loco/blob/2f8770ef004f9eca70c6ed1e72860514ed124bf8/docs/TROUBLESHOOTING.md#L18) · [kmj C++ 코드](https://github.com/tokengeoji/g1-edu-loco/blob/2f8770ef004f9eca70c6ed1e72860514ed124bf8/g1_teleop/g1_teleop.cpp) · [공식 G1 LocoClient](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/unitree_sdk2py/g1/loco/g1_loco_client.py)

온도 모니터는 `rt/lowstate`와 `rt/lf/bmsstate`를 구독한다. 보행에는 고수준 서비스의 왕복 RPC 응답이 필요하다. `--status`가 실패하면 표시된 NIC, 도메인, 각 서비스의 반환 코드를 확인한다. `--service sport` 또는 `--service loco`로 개별 조회할 수 있다. 실제 전환 가능 여부는 기체 상태와 펌웨어에 따라 달라진다. [Unitree 보행 서비스](https://support.unitree.com/home/en/G1_developer/sport_services_interface)

공식 Unitree Python SDK와 Cyclone DDS의 모의 서버에서 `sport/802`의 첫 `w`로 0.15 m/s가 수신됐고, `loco/4`에서는 `2`와 `Enter`로 802에 진입한 뒤 전진 명령이 수신됐다. 두 경로에서 속도 배율 변경, 정지, 속도 상한을 확인했다. 실제 PC2에서의 보행과 팔 동작은 현장 확인 항목이다.
