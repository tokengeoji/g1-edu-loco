<!-- Author: Codex (IIC) -->
# G1-EDU 현장 시작 가이드

이미 PC2에서 `g1 health eth0`가 동작한다면 **1번에서 기존 컨테이너로 접속**한다. PC2에는 ARM64 운영 이미지 `g1-jsj:base` 한 개면 된다. Windows의 별도 amd64 이미지는 외부 화면에서 영상과 상태를 볼 때 쓴다. 두 환경 모두 Ubuntu 20.04, ROS 2 Foxy와 Cyclone DDS를 사용한다. 이 가이드의 `eth0`, 도메인 `0`, PC2 주소 `192.168.123.164`는 이 기체에서 관측된 값이다.

## 1. PC2 컨테이너 열기

**G1 호스트 · PC2 SSH 터미널 1**

```bash
docker ps -a --filter 'name=^/jsj-g1-tools$'
```

목록에 컨테이너가 있으면 다음 두 줄로 실제 이미지 ID와 역할을 확인한다. 본인의 `operator-tools` 컨테이너이고 현재 이미지와 ID가 같으면 사용한다. `Exited`이면 G1 호스트에서 `docker start jsj-g1-tools`를 실행한다. 태그의 ID가 달라졌거나 USB 구성을 교체해야 하면 기존 기록부터 보관한다. [기존 컨테이너 확인·기록 이관](previous-runs.md)

**G1 호스트 · 기존 컨테이너와 이미지 확인**

```bash
docker container inspect jsj-g1-tools --format '{{.Config.Image}} {{.Image}} {{with .Config.Labels}}{{index . "org.iic.g1.role"}}{{end}} {{.State.Status}}'
docker image inspect g1-jsj:base --format '{{.Id}} {{with .Config.Labels}}{{index . "org.iic.g1.role"}}{{end}}'
```

**최초 설치만** 아래 블록을 사용한다. 이미 운영 이미지가 있으면 빌드를 건너뛴다. 두 번째 명령은 머리 D435i의 USB 장치를 조사해 호스트에서 실행할 `docker create ... && docker start jsj-g1-tools` 한 줄을 출력한다. 직접 USB로 촬영하려면 해당 줄에 `--device`가 있는지 확인하고 **출력된 한 줄을 G1 호스트에서 실행**한다. 장치를 찾지 못하면 네트워크 전용 구성이 출력된다. [장치 연결과 생성 절차](../README.md#create)

**G1 호스트 · 최초 설치**

```bash
docker build --pull=false --platform linux/arm64 -f docker/base/Dockerfile -t g1-jsj:base 'https://github.com/tokengeoji/g1-edu-loco.git#jsj'
docker run --pull never --rm --runtime=runc --network none --cap-drop ALL --security-opt no-new-privileges:true --entrypoint /usr/local/bin/g1-pc2-create-command g1-jsj:base
```

**G1 호스트 · PC2 SSH 터미널을 열 때마다**

```bash
docker exec -it jsj-g1-tools bash
```

<a id="update-tools"></a>

## 2. 기존 컨테이너에서 최신 jsj 소스 사용

기존 텔레옵과 카메라 세션을 끝낸 뒤 한 셸에서 갱신한다. 체크아웃과 빌드 결과는 컨테이너 안에 저장된다. 기존 통합 이미지에 설치된 공식 C++ SDK(`/opt/unitree_robotics`)로 텔레옵 호출부를 빌드한다. 새 이미지에 포함된 버전을 그대로 쓸 때는 이 절을 건너뛴다.

**G1 컨테이너 내부 · 터미널 1 · 최초 체크아웃 또는 업데이트**

```bash
(
  set -e
  src=/workspace/jsj-teleop-src
  if [ -d "$src/.git" ]; then
    git -C "$src" status --short --branch
    test "$(git -C "$src" rev-parse --abbrev-ref HEAD)" = jsj
    git -C "$src" pull --ff-only origin jsj
  else
    git clone --depth 1 --branch jsj https://github.com/tokengeoji/g1-edu-loco.git "$src"
  fi
  cmake -S "$src/src/g1_teleop/native" -B /tmp/g1-loco-build \
    -Dunitree_sdk2_DIR=/opt/unitree_robotics/lib/cmake/unitree_sdk2 -DCMAKE_BUILD_TYPE=Release
  cmake --build /tmp/g1-loco-build --parallel 2
  cmake --install /tmp/g1-loco-build --prefix /workspace/jsj-teleop-native
  git -C "$src" log -1 --oneline
)
```

마지막 줄에 적용할 커밋이 출력됐는지 확인한다. **기존 이미지에서 갱신한 경우 새 PC2 셸을 열 때마다** 다음 블록을 먼저 실행한다. C++ 모듈은 `/workspace/jsj-teleop-native/`, 두 Python 패키지는 `/workspace/jsj-teleop-src/src/` 아래를 가리켜야 한다.

**G1 컨테이너 내부 · 터미널마다**

```bash
export PYTHONPATH="/workspace/jsj-teleop-src/src:/workspace/jsj-teleop-native${PYTHONPATH:+:$PYTHONPATH}"
cd /workspace
python3 -c 'from pathlib import Path; import _g1_loco, g1_teleop, g1stairs; print(*(Path(m.__file__).resolve() for m in (_g1_loco, g1_teleop, g1stairs)), sep="\n")'
```

## 3. 온도와 텔레옵

**G1 컨테이너 내부 · 터미널 1 · 첫 출력 후 10초마다 온도와 배터리 표시**

```bash
g1 interfaces
g1 health eth0
```

**G1 컨테이너 내부 · 터미널 2 · 실제 상태 조회 후 모의 조작**

```bash
g1 teleop --status --interface eth0 --domain 0
g1 teleop --dry-run
```

`i`와 `,`는 초기 배율에서 각각 `Move(0.3, 0, 0)`과 `Move(-0.3, 0, 0)`을 요청한다. `x` 한 번으로 순수 전후진 속도를 0.27 m/s로 낮출 수 있다. 상한은 0.30 m/s이며 `--straight-speed`를 명시하면 지정한 값으로 고정된다. `k` 또는 스페이스는 `StopMove()`, `Ctrl+C`는 최종 정지 후 종료다. 실제 상태를 읽고 같은 키를 모의 입력할 때는 `g1 teleop --preview --interface eth0 --domain 0`을 쓴다. [보행 전 점검](teleop-preflight.md)

**G1 컨테이너 내부 · 터미널 3 · 실제 변위를 읽기 전용으로 표시**

```bash
g1 teleop --feedback --interface eth0 --domain 0
```

실기체 비교는 숙련자가 물리 조종기를 들고 입회한 상태에서 온도·배터리, 기체 지지, 이동 공간을 확인한 뒤 진행한다. 802에서는 내장 보행기가 팔을 흔들 수 있다.

**G1 컨테이너 내부 · 터미널 2 · 조작자가 승인한 실기체 시험**

```bash
g1 teleop --live --interface eth0 --domain 0
```

1. `f`로 실제 FSM을 확인한다. 허리 3축 모델에서 고정구가 제거되고 Explore 앱의 허리 잠금이 해제됐으면 `8` → 4초 안에 `Enter`로 501을 요청할 수 있다. `f`에서 501이 표시되고 기체가 안정적으로 서 있는지 확인한다. 802 전환이 필요하면 `2`의 요청 대상이 802인지 확인한다. 대상이 801이면 `--run-fsm 802`를 명시해 다시 시작한다. 자세와 지지를 확인한 뒤 `2` → 4초 안에 `Enter`로 요청하고 `f`에서 **802**가 표시되는지 확인한다. `?`는 전체 키와 모드를 표시한다.
2. 정지 상태에서 `i`를 한 번 누르고 `k`로 정지한다. 터미널 3의 **시작 전방 Δ**와 실제 발걸음을 확인한다. 후진을 따로 비교할 때는 기체를 정지시키고 피드백을 다시 시작한 뒤 `,`를 누른다. 전진이면 양수, 후진이면 음수 방향의 변화를 본다.
3. 키 한 번은 1초짜리 `Move` 한 번을 요청한다. 같은 키를 길게 누르면 새 터미널 입력을 최대 10 Hz로 전송한다. 마지막 입력에서 1초가 지나면 `StopMove()`를 요청한다. `Ctrl+C`는 속도 0 응답을 출력하고 종료한다. 현장에서 기체 정지를 확인한다. 종료 정지 미확인이 표시되면 물리 조종기로 상태를 확인한다.

`Move(7105) 수락`은 보행 서비스가 반환한 코드 0이다. 11월 23일의 두 시험에서는 FSM 802에서 ±0.15 m/s를 요청하고도 기체가 제자리에 머물렀다. 이후 운영자는 +0.30 m/s 전진을 관찰했다. 순수 후진 −0.30 m/s에서의 결과는 별도 확인이 필요하다. 2차 시험의 타이머 반복 방식은 `--timed-velocity`로 선택한다. [실험 기록과 이후 전진 관찰](../src/g1_teleop/README.md#no-motion)

## 4. PC2에서 머리 카메라 켜기

**G1 컨테이너 내부 · 터미널 4 · ROS·DDS·USB 샘플 검사**

```bash
export G1_CAMERA_IFACE=eth0 G1_CAMERA_DOMAIN=0
g1 camera check --seconds 5
```

`DDS_NO_SAMPLES`는 관측 시간 동안 유효 샘플이 0개였다는 뜻이다. **이미 머리 카메라의 ROS 영상이 수신되면** 그 발행자를 계속 사용한다. **USB D435i가 컨테이너에 보이고 장치가 비어 있으면** 다음 명령을 실행해 컬러와 깊이 첫 발행 메시지를 확인하고 터미널을 열어 둔다. [출력별 진단](camera-check.md)

**G1 컨테이너 내부 · 터미널 4 · USB 직접 촬영 시**

```bash
g1 camera start
```

**G1 컨테이너 내부 · 터미널 5 · 외부 PC로 영상·로봇 상태 전달**

```bash
G1_CAMERA_IFACE=eth0 G1_CAMERA_DOMAIN=0 g1 camera remote serve
```

기본 송신원은 방금 켠 발행기의 `/g1/head/` 영상과 보정 정보, 로봇의 `/lowstate`다. 기존 ROS 발행자의 토픽 이름이 다르면 송신기에 실제 토픽 이름을 지정한다. 송신 터미널은 외부 시청 중 열어 둔다. [송신 토픽 지정](remote-camera.md)

## 5. Windows x64에서 TTY 또는 RViz2로 확인

Docker Desktop을 Linux 컨테이너 모드로 실행한다. 유선 어댑터를 PC2와 같은 서브넷의 미사용 주소로 설정한다. 아래 예시는 PC2가 `192.168.123.164`인 경우다. `TcpTestSucceeded`가 `True`인지 확인한다. 인터넷을 사용해 최신 개발 이미지를 빌드하고 최초 한 번만 `docker run`을 실행한다. 같은 버전의 개발 컨테이너를 재시작할 때는 `docker start jsj-g1-dev`를 쓴다. [Windows 설정·기존 이미지 교체](windows-development-pc.md)

`dockerDesktopLinuxEngine` 파이프 오류가 나오면 [Windows Linux 엔진 시작·확인](windows-development-pc.md#linux-engine)을 먼저 따른다. Windows에서 빌드할 이미지는 `g1-jsj:windows-foxy`다.

**Windows PowerShell · 최초 설치**

```powershell
Test-NetConnection 192.168.123.164 -Port 22 -InformationLevel Detailed
docker build --pull=false --platform linux/amd64 -f docker/windows/Dockerfile -t g1-jsj:windows-foxy 'https://github.com/tokengeoji/g1-edu-loco.git#jsj'
docker run -d --pull never --name jsj-g1-dev -e G1_RVIZ_BIND=0.0.0.0 -p 127.0.0.1:6080:6080 g1-jsj:windows-foxy
```

**Windows PowerShell · 터미널 1 · PC2에 SSH 인증 후 계속 실행**

```powershell
docker exec -it jsj-g1-dev g1 camera connect unitree@192.168.123.164
```

**Windows PowerShell · 터미널 2 · 컬러와 깊이 한 장씩 확인한 뒤 RViz2 열기**

```powershell
docker exec -it jsj-g1-dev g1 camera remote tty --topic /g1_remote/color/image_raw --once
docker exec -it jsj-g1-dev g1 camera remote tty --topic /g1_remote/depth/image_rect_raw --once
docker exec -it jsj-g1-dev g1 camera rviz
```

TTY에 촬영 시각·해상도·그림이 나오면 해당 영상이 Windows까지 도착한 것이다. 연속해서 보려면 `--once`를 뺀다. RViz2를 띄운 후 터미널의 일회성 VNC 암호로 Windows 브라우저에서 접속한다. [로컬 RViz2 열기](http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale)

**Windows PowerShell · 터미널 3 · 로봇 상태 도착 주기 확인**

```powershell
docker exec -it jsj-g1-dev ros2 topic hz /g1_remote/lowstate
```

## 6. 계단 치수 분석

기체를 실측 보정 때와 같은 자세로 세우고 머리 카메라가 인접한 디딤면을 볼 수 있는지 확인한다. 4번 발행기를 계속 켜 둔 상태에서 ROS 깊이와 같은 영상의 보정 정보를 기록한다. `0.001`은 이 프로젝트 발행기의 밀리미터 영상에 해당한다.

**G1 컨테이너 내부 · 터미널 6 · 깊이 5초 기록**

```bash
RUN_ID="stairs-$(date +%Y%m%d-%H%M%S)"
G1_CAMERA_IFACE=eth0 G1_CAMERA_DOMAIN=0 g1 camera record-ros --run "$RUN_ID" --seconds 5 \
  --depth-topic /g1/head/depth/image_rect_raw --info-topic /g1/head/depth/camera_info --depth-scale-m 0.001
```

이후 같은 셸에서 `g1 stairs measure`로 인접 면 사이의 단차, 디딤면 깊이와 폭을 미터 단위로 계산한다. 양쪽 경계가 보이지 않으면 폭은 `null`이다. `g1 stairs assess`에 실측한 발 크기와 여유를 넣어 발을 놓을 후보를 찾는다. 지지발 자세와 검증된 도달 한계가 있으면 그 범위까지 함께 검사한다. [측정 명령·결과 판독·발 디딤 후보 검사](stair-analysis.md)
