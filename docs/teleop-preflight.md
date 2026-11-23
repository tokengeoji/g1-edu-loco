<!-- Author: Codex (IIC) -->
# G1-EDU 보행 전 점검 가이드

**기체 상태를 읽고 키보드 입력이 어떤 보행 명령으로 변환되는지 확인한다.** 이 가이드에서 사용하는 `--preview`는 실제 FSM과 관절 피드백을 읽은 뒤, 키 입력을 컨테이너 메모리에서 처리한다. 마지막 `Ctrl+C`까지 기체에 이동·모드 변경·정지 명령을 보내지 않는다.

## 1. PC2에서 사용할 이미지와 컨테이너 준비

이미지 이름은 **`g1-jsj:base`**, 그 이미지로 만든 운영 컨테이너 이름은 **`jsj-g1-tools`**다. Ubuntu 20.04 ARM64, ROS 2 Foxy, Cyclone DDS, Unitree SDK와 온도·텔레옵·카메라·계단 계산 도구가 이 이미지에 함께 들어 있다.

| PC2의 현재 상태 | 먼저 할 일 |
| --- | --- |
| 처음 설치하거나 코드를 업데이트하는 경우 | 바로 아래 명령으로 `jsj` 브랜치에서 이미지를 한 번 빌드한다. |
| 컨테이너를 처음 만드는 경우 | 빌드 후 [컨테이너 생성과 시작](../README.md#create)에서 네트워크용 또는 USB D435i 직접 연결용을 선택한다. |
| 이전 버전의 컨테이너가 있는 경우 | 새 이미지를 빌드한 뒤 [실험 기록을 보존하며 컨테이너 교체](previous-runs.md)를 따른다. 기존 컨테이너를 재시작하면 이전 코드가 실행된다. |
| 최신 컨테이너가 이미 실행 중인 경우 | 2단계로 이동한다. |

**G1 호스트 · 최초 설치 또는 업데이트**

```bash
docker build --pull=false --platform linux/arm64 -f docker/base/Dockerfile -t g1-jsj:base 'https://github.com/tokengeoji/g1-edu-loco.git#jsj'
```

### 실행 중인 컨테이너에서 텔레옵만 업데이트할 때

현재 `jsj-g1-tools`에 설치한 Node.js·Codex와 실험 기록을 유지한 채 텔레옵만 시험할 수 있다. 기존 텔레옵 세션을 종료하고 컨테이너 안에서 아래 명령을 한 번 실행한다. 새 소스를 검사한 뒤 `/workspace/g1_teleop` 링크를 만들면, `/workspace`에서 Python을 실행하는 기존 `g1 teleop` 명령이 이 패키지를 사용한다.

**컨테이너 내부 · 기존 이미지에서 처음 적용**

```bash
git clone --depth 1 --branch jsj https://github.com/tokengeoji/g1-edu-loco.git /workspace/jsj-teleop-src &&
(cd /workspace/jsj-teleop-src/src && python3 -m unittest discover -s g1_teleop -t . -q) &&
ln -sT /workspace/jsj-teleop-src/src/g1_teleop /workspace/g1_teleop
```

`ln`은 기존 경로를 덮어쓰지 않는다. 이미 이 절차로 설치했다면 텔레옵을 종료하고 `git -C /workspace/jsj-teleop-src pull --ff-only`로 갱신한 뒤 같은 검사를 실행한다. 다음 명령에서 출력된 경로가 체크아웃의 패키지를 가리키면 설치한 버전이다.

**컨테이너 내부 · 적용 확인**

```bash
(cd /workspace && python3 -c 'from pathlib import Path; import g1_teleop; print(Path(g1_teleop.__file__).resolve())')
```

### 기존 체크아웃에서 텔레옵과 카메라 검사 함께 사용하기

컨테이너에 있는 `/workspace/jsj-teleop-src`가 이미 `jsj` 브랜치이면 아래 명령을 사용한다. 새 셸을 열 때마다 `export` 줄을 적용하면 카메라 검사와 텔레옵이 같은 체크아웃의 코드를 읽는다. 기본 이미지 설치는 [PC2 빌드 절차](../README.md#pc2)를 따른다.

**컨테이너 내부 · 기존 소스 갱신 후 읽기 전용 상태 확인**

```bash
git -C /workspace/jsj-teleop-src pull --ff-only &&
export PYTHONPATH="/workspace/jsj-teleop-src/src${PYTHONPATH:+:$PYTHONPATH}"
g1 teleop --status --interface eth0 --domain 0
```

`robot_state`에서 주 제어 서비스 `ai_sport`의 상태 원값과 기체 소프트웨어 패키지 버전을 별도로 조회한다. 펌웨어가 버전 조회를 지원하지 않으면 Unitree 앱에 표시된 기체 소프트웨어 버전을 사용한다. 보행 서비스 API 버전은 통신 인터페이스의 버전을 뜻한다. [G1 상태 서비스 문서](https://support.unitree.com/home/en/G1_developer/robot_state_client_interface) · [SDK의 조회 함수](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/unitree_sdk2py/b2/robot_state/robot_state_client.py)

**컨테이너 내부 · 두 번째 셸에서 보행기 추정값 구독**

```bash
export PYTHONPATH="/workspace/jsj-teleop-src/src${PYTHONPATH:+:$PYTHONPATH}"
g1 teleop --feedback --interface eth0 --domain 0
```

`--feedback`은 오도메트리의 수평 속력과 시작점으로부터 수평거리를 표시한다. 제자리에서의 흔들림과 추정 오차가 있으므로 현장 발걸음과 함께 본다. 이 기체에서 순정 조종기의 전진·후진은 FSM 802에서 정상이다. 텔레옵으로 직진·후진을 시험할 때는 정지한 시작 자세 기준의 부호 있는 전후 변위와 기체가 실제로 내디딘 발걸음을 함께 기록한다. [키 입력 및 정지 절차](../src/g1_teleop/README.md) · [카메라 검사](camera-check.md)

## 2. 터미널 1에서 온도·배터리 확인

**G1 호스트 · 터미널 1**

```bash
docker exec -it jsj-g1-tools bash
```

**컨테이너 내부 · 터미널 1**

```bash
g1 interfaces
g1 health eth0
```

`eth0`는 연구실 기체에서 수신을 확인한 유선 NIC다. 이름이 다르면 두 터미널에서 모두 실제 NIC 이름을 쓴다. 배터리와 모터 값이 계속 갱신되는지 확인하고 이 터미널을 열어 둔다.

## 3. 터미널 2에서 기체 상태를 읽고 키 입력 시험

**G1 호스트 · 새 터미널 2**

```bash
docker exec -it jsj-g1-tools bash
```

**컨테이너 내부 · 터미널 2**

```bash
g1 teleop --preview --interface eth0 --domain 0
```

시작 화면의 **`[시작 시점 실측]`** 두 줄에서 실제 FSM과 응답 서비스(`sport` 또는 `loco`), `q/dq 수신 29/29 슬롯`, 왼쪽 무릎의 위치(rad)와 속도(rad/s)를 확인한다. `29/29`는 수신한 한 샘플에서 전체 29개 슬롯의 위치·속도가 유한한 값이라는 뜻이다. 이후의 **`[모의]`** 출력은 키보드 입력으로 바뀌는 모의 상태와 명령값이다.

시작 화면에 각 숫자 키의 자세·보행 모드와 4/5번의 제자리걸음 설정이 표시된다. 영문 입력 상태에서 아래 키를 한 번씩 누른다. 모드 선택만 `Enter`로 확인한다.

| 키 입력 | 확인할 결과 |
| --- | --- |
| 시작값이 0 또는 4이면 `2` → 4초 안에 `Enter` | 연구실 기본값으로 모의 `SetFsmId(802)`. 시작값이 이미 Run(801/802)이면 건너뛴다. |
| `f` | 모의 현재 FSM과 메뉴에 표시된 Run ID 일치 |
| `i` | 기본 경로에서 `Move(0.3, 0, 0)` 한 번. 모의 전진 요청 `vx=0.300` m/s, `vy=0`, `yaw=0` |
| 소문자 `j` / `l` 또는 `←` / `→` | 모의 제자리 좌회전 / 우회전 요청. `vx=vy=0`, `yaw=+0.300 / −0.300` rad/s |
| `Shift+j` / `Shift+l` (대문자 `J` / `L`) | 모의 왼쪽 / 오른쪽 옆걸음 요청. `vx=yaw=0`, `vy=+0.100 / −0.100` m/s |
| 초기 배율에서 `x` 한 번 → `i` | 선속도 배율 0.9배, 전진 요청 `vx=0.270` m/s. 배율을 올려도 순수 전후진 크기는 0.30 m/s까지다. |
| `k` 또는 스페이스 | 기본 경로에서 모의 `StopMove()`로 속도 0 요청 |
| `i`를 누른 직후 `Ctrl+C` | 모의 속도 0과 종료 메시지가 표시된 뒤 셸로 복귀 |

컨테이너에서 `g1 teleop --dry-run`을 열고 `v` → `Enter` → `f` 순서로 입력하면 모의 FSM 500이 표시된다. 이어서 `i`를 한 번 누르면 1초짜리 `Move`가 한 번 표시되고 마지막 입력에서 1초가 지나면 정지를 요청한다. `g1 teleop --dry-run --timed-velocity`에서는 동일한 단발 입력으로 기한이 줄어드는 `SetVelocity` 재전송을 확인할 수 있다.

**점검 완료 기준**은 실제 상태 두 줄을 확인하고, `[모의]`에서 예상한 FSM·속도·정지가 순서대로 표시되는 것이다. 이 결과는 상태 수신과 명령 변환을 검증한다. 실제 균형, 팔 움직임, 보행 성능은 기체에서 별도로 확인해야 한다. [실제 운용 조건과 전체 키 배치](../src/g1_teleop/README.md)

## 출력이 예상과 다를 때

| 보이는 현상 | 확인할 항목 |
| --- | --- |
| `--preview`를 알 수 없는 옵션이라고 표시 | 컨테이너 내부에서 `g1 teleop --help`를 본다. 옵션이 없으면 1단계에서 새 이미지로 컨테이너를 교체한다. |
| 온도는 들어오지만 `GetFsmId` 오류 | 온도는 DDS 구독, FSM은 보행 서비스의 왕복 조회다. 같은 컨테이너에서 `g1 teleop --status --interface eth0 --domain 0`로 서비스와 반환 코드를 확인한다. |
| `rt/lowstate` 수신 시간 초과 또는 관절값 오류 | 터미널 1의 최신 모터 샘플, 두 터미널의 NIC와 도메인을 대조한다. 미리보기는 상태 확인이 실패하면 키 입력 전에 종료된다. |
| 현재 FSM이 1000 | 사용자 제어 모드에서는 내장 보행기 전환이 차단된다. `Ctrl+C`로 나간 뒤 키 처리만 시험하려면 컨테이너 안에서 `g1 teleop --dry-run`을 실행한다. |
| 모드만 바뀌고 이동 키를 눌러도 반응이 없음 | 먼저 `[모의]` 여부와 전진 키 `i`를 확인한다. 실기체 시험에서는 `f`의 현재 FSM, 기본 `Move(7105)`의 서비스 응답, 오도메트리 변위를 함께 기록한다. |
| 802에서 전진·후진 수락 후 기체가 서 있음 | 11월 23일의 ±0.15 m/s 시험에서 이 증상이 기록됐다. `k`로 정지하고 현재 속도와 시작 전방 변위를 확인한다. `--dry-run` 기본 배율에서 전후진 부호와 정지를 확인할 수 있다. [속도별 관찰과 오도메트리 판독](../src/g1_teleop/README.md#no-motion) |
| 대화형 TTY가 필요하다고 표시 | G1 호스트에서 `docker exec -it jsj-g1-tools bash`로 다시 접속한다. |

**컨테이너 내부 · 로봇 연결 없이 자동 검사**

```bash
python3 -m unittest g1_teleop.test_control g1_teleop.test_terminal g1_teleop.test_preview g1_teleop.test_status g1_teleop.test_feedback g1_teleop.test_services
```

마지막에 `OK`가 출력되면 키 입력 처리와 미리보기 회귀 검사를 통과한 것이다. 직접 키만 연습할 때는 컨테이너 내부에서 `g1 teleop --dry-run`을 실행한다.

[전체 운영 안내](../README.md) · [카메라 탐색과 영상 확인](../README.md#camera) · [계단 치수 계산](../README.md#geometry)
