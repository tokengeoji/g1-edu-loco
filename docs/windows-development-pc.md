<!-- Author: Codex (IIC) -->
# Windows에서 G1 헤드 카메라와 로봇 상태 보기

연구실 유선 스위치에 연결한 Windows x64 PC에서 Docker Desktop을 **Linux containers** 모드로 사용한다. PC2 운영 도구는 기존 ARM64 이미지 `g1-jsj:base`, 외부 PC의 개발 도구는 전용 amd64 이미지 `g1-jsj:windows-foxy`다. Windows 호스트에는 ROS 2, X 서버, RealSense 드라이버를 설치할 필요가 없다.

| 기기 | 데이터 경로 |
| --- | --- |
| G1 PC2 | 유선 도메인 0에서 G1 `/lowstate`를 구독한다. 내장 D435i가 PC2 컨테이너에 전달된 경우 librealsense로 열고, ROS 2 이미지·보정 정보를 발행한다. 이미 표준 영상을 발행 중이면 그 발행자를 사용한다. |
| Windows 개발 컨테이너 | SSH로 받은 원본 ROS 2 직렬화 메시지를 자기 컨테이너의 Cyclone DDS에 다시 발행한다. `/g1_remote` 아래에서 카메라 영상·보정과 `unitree_hg/msg/LowState`를 구독할 수 있다. |
| Windows 화면 | PowerShell에서 실제 영상의 밝기를 문자로 그려 보거나, 브라우저에서 개발 컨테이너의 RViz2 창을 연다. |

기본 경로에는 PC2의 SSH 포트만 필요하다. Docker Desktop의 host 네트워크 기능은 TCP/UDP 계층에서 동작하며 컨테이너가 Windows의 물리 NIC에 직접 바인딩할 수 없다. WSL의 기본 NAT나 Docker Desktop의 `--network host`만으로 로봇 DDS 멀티캐스트가 도달한다고 가정하지 않는다. [Docker Desktop host 네트워크 제한](https://docs.docker.com/engine/network/drivers/host/#limitations) · [Microsoft WSL 네트워킹](https://learn.microsoft.com/en-us/windows/wsl/networking)

## 1. Windows 개발 컨테이너 준비

Windows Ethernet 포트의 주소를 연구실 스위치와 같은 `192.168.123.0/24`의 미사용 주소로 설정한다. 다음 명령에서 TCP 연결 결과가 `True`이고, 인터페이스와 출발 주소가 유선 연결인지 확인한다. PC2의 현장 주소는 `192.168.123.164`다.

<a id="linux-engine"></a>

**Windows PowerShell · 유선과 로컬 Docker 엔진 점검**

```powershell
Test-NetConnection 192.168.123.164 -Port 22 -InformationLevel Detailed
docker desktop start
docker info --format '{{.OSType}}/{{.Architecture}}'
```

`TcpTestSucceeded : True`이면 Windows에서 G1 PC2의 SSH 포트까지 연결된 상태다. `dockerDesktopLinuxEngine` 파이프를 찾을 수 없다는 오류는 Windows Docker CLI가 로컬 Linux 엔진에 연결하지 못했다는 뜻이다. 이때 빌드는 시작되지 않는다.

- `docker desktop start`를 인식하지 못하면 Windows 시작 메뉴에서 **Docker Desktop**을 실행한 뒤 엔진이 시작될 때까지 기다린다. 앱이 설치되어 있지 않다면 공식 Windows 설치 안내를 따른다.
- `docker info`가 오류 없이 **`linux/x86_64` 또는 `linux/amd64`**를 출력하면 아래 Windows용 빌드를 진행한다. `windows/...`가 나오면 작업 표시줄의 Docker 메뉴에서 **Switch to Linux containers**를 선택하고 다시 확인한다.
- 앱을 열었는데도 같은 오류라면 Docker Desktop 화면의 오류 문구와 `docker version`, `docker context ls` 출력을 확인한다. WSL 2 백엔드를 사용한다면 `wsl --status`, `wsl --version`도 확인한다.

[Docker Desktop 시작 명령](https://docs.docker.com/reference/cli/docker/desktop/start/) · [Windows 설치와 Linux 컨테이너 전환](https://docs.docker.com/desktop/setup/install/windows-install/)

**Windows PowerShell · 엔진 확인 후 x64 개발 이미지 빌드**

```powershell
docker build --pull=false --platform linux/amd64 -f docker/windows/Dockerfile -t g1-jsj:windows-foxy 'https://github.com/tokengeoji/g1-edu-loco.git#jsj'
```

인터넷이 있는 상태에서 빌드한다. Docker Desktop은 BuildKit 및 Dockerfile 1.6 이상의 `ADD --checksum`을 지원해야 한다. Ubuntu 20.04 Focal amd64 루트 파일과 압축 해제 도구는 원 배포처에서 SHA-256으로 검증한다. ROS 2 Foxy의 공식 RMW 패키지 `rmw_cyclonedds_cpp` 0.7.11과 Cyclone DDS C 라이브러리 0.10.2, `unitree_hg`·`unitree_go`·`unitree_api`, RViz2, SSH 클라이언트가 이미지에 포함된다. [Canonical 이미지 체크섬](https://partner-images.canonical.com/oci/focal/20250530.1/SHA256SUMS) · [Unitree ROS 2](https://github.com/unitreerobotics/unitree_ros2) · [Dockerfile ADD](https://docs.docker.com/reference/dockerfile/#add---checksum)

**Windows PowerShell · 최초 생성**

```powershell
docker run -d --pull never --name jsj-g1-dev -e G1_RVIZ_BIND=0.0.0.0 -p 127.0.0.1:6080:6080 g1-jsj:windows-foxy
docker exec jsj-g1-dev python3 /opt/g1/verify-foxy.py
docker exec jsj-g1-dev ros2 interface show unitree_hg/msg/LowState
```

RViz 웹 포트는 Windows의 루프백에만 공개한다. 컨테이너 안에서 DDS는 기본적으로 `127.0.0.1`, 도메인 0을 사용한다. 같은 컨테이너를 다시 사용할 때는 `docker start jsj-g1-dev`를 실행한다. 새로 빌드한 이미지로 교체할 때는 기존 컨테이너를 중지해 포트를 반환한 뒤 보관용으로 이름을 변경하고 위 명령으로 새 컨테이너를 생성한다.

## 2. G1에서 실측 데이터 송신 시작

최신 `jsj` 코드를 사용하는 PC2의 `jsj-g1-tools`에서 실행한다. 예전 이미지의 소스를 컨테이너 안에서 갱신했다면 **각 셸**에서 체크아웃의 `src`를 `PYTHONPATH` 앞에 둔다. [PC2 소스 갱신](teleop-preflight.md)

**G1 호스트 · SSH 터미널마다**

```bash
docker exec -it jsj-g1-tools bash
```

**G1 컨테이너 내부 · 터미널 1 · USB가 전달된 내장 카메라 시작**

```bash
G1_CAMERA_IFACE=eth0 G1_CAMERA_DOMAIN=0 g1 camera start
```

**G1 컨테이너 내부 · 터미널 2 · 읽기 전용 송신 시작**

```bash
G1_CAMERA_IFACE=eth0 G1_CAMERA_DOMAIN=0 g1 camera remote serve
```

기본 송신원은 `/g1/head/color/image_raw`, `/g1/head/depth/image_rect_raw`, 두 `camera_info`, `/lowstate`다. 이미 다른 운영 프로그램이 USB를 점유하며 ROS 2 영상을 내보내면 두 번째 명령의 `--color-topic`, `--depth-topic` 등으로 실제 토픽을 선택한다. 카메라 수신이 실패해도 송신기는 수신되는 로봇 상태를 전달할 수 있다. DDS 영상 발행자만 발견되고 프레임이 0개인 경우에는 USB 장치 전달이나 실제 ROS 영상 원본을 확인한다. [카메라 진단](camera-check.md) · [송신 토픽과 카메라 확인](remote-camera.md)

## 3. Windows에서 실시간으로 보기

**Windows PowerShell · 터미널 1 · SSH 연결과 ROS 2 수신**

```powershell
docker exec -it jsj-g1-dev g1 camera connect unitree@192.168.123.164
```

처음 연결하면 PC2 SSH 호스트 키 지문을 확인하고 기존 계정으로 인증한다. 이 터미널을 열어 둔다. 컨테이너 안에서 SSH 포트 전달을 열므로 Windows에 별도 터널이나 키 마운트가 필요 없다. Ctrl+C로 수신을 종료하면 터널도 닫힌다.

**Windows PowerShell · 터미널 2 · 실제 영상 한 장을 문자로 확인**

```powershell
docker exec -it jsj-g1-dev g1 camera remote tty --topic /g1_remote/color/image_raw --once
docker exec -it jsj-g1-dev g1 camera remote tty --topic /g1_remote/depth/image_rect_raw --once
```

`--once`를 빼면 계속 표시한다. 헤더의 촬영 시각과 프레임 크기를 확인한다. 깊이 영상에서는 유효 깊이의 상대적인 거리가 밝기로 표시된다.

**Windows PowerShell · 터미널 2 · RViz2 창 열기**

```powershell
docker exec -it jsj-g1-dev g1 camera rviz
```

Windows 브라우저에서 [로컬 RViz2](http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale)를 열고 방금 터미널에 표시된 일회성 VNC 암호를 입력한다. `Head color`와 `Head depth` 두 Image 디스플레이가 해당 토픽을 Best Effort QoS로 구독한다. RViz 터미널에서 Ctrl+C로 창을 종료한다.

**Windows PowerShell · 터미널 3 · 로봇 데이터 실제 도착 확인**

```powershell
docker exec jsj-g1-dev ros2 topic list --no-daemon --spin-time 3 -t
docker exec -it jsj-g1-dev ros2 topic hz /g1_remote/lowstate
```

`ros2 topic hz`를 몇 초 유지해 평균 주기가 표시되는지 본다. 기본 송신 제한은 채널당 최대 5 Hz이며 이 값은 원래 로봇 DDS의 발행률과 다를 수 있다. 카메라·상태는 읽기 전용으로 전달한다. 원본 `/lowstate` 직접 구독과 PC2에서의 원생 DDS 확인은 [개발 PC 유선 DDS 구성](development-pc.md)을 참고한다.

| 현상 | 확인할 사항 |
| --- | --- |
| SSH 연결 거절/시간 초과 | PowerShell에서 유선 출발 주소와 `Test-NetConnection … -Port 22`를 확인한다. |
| 연결 직후 수신기 종료 | PC2에서 `g1 camera remote serve`가 실행 중인지, PC2 운영 컨테이너가 `--network host`로 생성됐는지 확인한다. |
| 토픽은 보이지만 이미지가 없음 | PC2에서 실제 ROS 이미지가 오는지 확인한다. Windows에서 `tty --once`가 프레임과 시각을 출력하는지 확인한다. |
| Windows의 RViz 브라우저가 연결되지 않음 | 터미널에서 VNC 암호가 출력될 때까지 기다리고 `docker port jsj-g1-dev 6080/tcp` 결과가 `127.0.0.1:6080`인지 확인한다. |
