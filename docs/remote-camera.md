<!-- Author: Codex (IIC) -->
# 개발 PC에서 실제 카메라 영상과 G1 상태 보기

Windows에서 [외부 개발 컨테이너](windows-development-pc.md)를 실행하고 연구실 스위치에 유선으로 연결한다. G1 카메라가 이미 ROS 2 영상을 발행하는 경우 그 토픽을 구독한다. USB D435i만 보이는 경우 운영 컨테이너에서 `g1 camera start`로 발행을 시작한다. 영상을 발행하는 프로세스는 실험 중 계속 실행한다. [카메라 수신 검사](camera-check.md)

## 외부 PC에서 ROS 2 또는 전방 DDS 영상을 직접 보기

로봇과 같은 유선망에 연결된 **외부 PC의 그래픽 데스크톱**에서 뷰어를 실행한다. `--address`에는 그 PC의 유선 IPv4 주소를 넣고, `--domain`은 영상 발행자와 맞춘다. 예시는 외부 PC `192.168.123.99`, 도메인 `0`이다. 기존 `CYCLONEDDS_URI`가 있으면 그 설정을 사용하므로 선택한 인터페이스가 로봇망에 연결돼 있는지 확인한다. [외부 PC의 DDS 네트워크 설정](development-pc.md)

| 사용할 기능 | 외부 PC의 Python 환경에 필요한 항목 |
| --- | --- |
| 영상 창 | NumPy, GUI를 지원하는 OpenCV(`cv2`) |
| ROS 2 영상 | ROS 2 환경의 `rclpy`, `sensor_msgs`. 파라미터 조회에는 `ros2` CLI도 필요하다. |
| 네이티브 DDS 영상 | Cyclone DDS Python(`cyclonedds`), H.264 디코더를 제공하는 PyAV(`av`). 발행자가 타입 ID를 제공하지 않을 때는 일치하는 Unitree Python SDK의 IDL도 필요하다. |

**외부 PC · 로컬 터미널에서 저장소 루트로 이동한 뒤 실행**

```bash
python3 tools/g1_camera_view.py --address 192.168.123.99 --domain 0
```

ROS 2를 쓴다면 해당 배포판의 환경을 먼저 불러온다. 뷰어는 `sensor_msgs/msg/Image`와 `sensor_msgs/msg/CompressedImage`를 탐색하고, 최근 2초 안에 디코딩한 ROS 프레임을 우선 표시한다. ROS 영상이 끊겼거나 아직 도착하지 않았을 때는 Cyclone DDS의 `rt/frontvideostream`에서 받은 360p H.264 프레임을 사용한다. 터미널의 `Displaying` 뒤에 현재 표시 중인 토픽 이름이 나온다. 창에서 `q` 또는 Esc를 누르면 종료된다. [뷰어 소스](../tools/g1_camera_view.py)

**외부 PC · 특정 ROS 이미지 토픽을 알고 있을 때**

```bash
python3 tools/g1_camera_view.py --address 192.168.123.99 --topic /g1/head/color/image_raw
```

**외부 PC · ROS 노드의 문자열 파라미터가 토픽 이름을 지정할 때**

```bash
python3 tools/g1_camera_view.py --address 192.168.123.99 --ros-param /camera_node image_topic
```

`/camera_node`와 `image_topic`은 예시다. 실제 노드명과 파라미터명을 넣으면 뷰어가 시작될 때 파라미터에서 토픽 이름을 읽고 해당 토픽을 구독한다.

2026년 11월 27일 별도 ROS 도메인에서 테스트 발행기의 8×8 원본 컬러 영상과 JPEG 압축 영상을 수신했다. 문자열 파라미터로 지정한 토픽에서도 RGB 픽셀의 색상 변환을 확인했다. 루프백 DDS 도메인에서는 Unitree SDK 메시지의 `video360p`에 담은 H.264 테스트 영상을 640×360 컬러 프레임으로 디코딩하고 픽셀값을 확인했다. 같은 날 PC2의 `eth0`, 도메인 0에서는 `rt/lowstate` 발행자가 보였지만 12초간 `rt/frontvideostream` 발행자가 발견되지 않았다. 외부 PC에서 이 뷰어로 실기체 영상을 표시하는 검증은 남아 있다. [이전 전방 DDS 실기체 관측](experiments/2026-11-23-front-rgb/README.md)

## SSH를 통한 수신

PC2에서 보이는 영상과 상태 토픽을 유선 SSH 연결 하나로 전달한다. PC2 운영 컨테이너는 호스트 네트워크를 사용하며 수신 대기 소켓은 PC2의 `127.0.0.1`에 열린다. 개발 컨테이너 안에서 SSH를 실행해야 같은 컨테이너의 수신기가 포워딩 포트를 열 수 있다.

**G1 호스트 · 두 번째 터미널**

```bash
docker exec -it jsj-g1-tools bash
```

**G1 컨테이너 내부 · PC2가 관측하는 토픽 전달**

```bash
G1_CAMERA_IFACE=eth0 G1_CAMERA_DOMAIN=0 g1 camera remote serve
```

프로젝트 발행기의 기본 토픽은 표에 있는 이름을 사용한다. 기존 ROS 2 카메라 드라이버를 쓰는 경우 `ros2 topic list -t`로 이름을 확인하고 `serve --color-topic ... --depth-topic ... --color-info-topic ... --depth-info-topic ...`로 해당 이름을 지정한다. 이미지 채널은 `sensor_msgs/msg/Image`를 받는다. 압축 토픽만 있으면 PC2의 기존 `g1 camera compressed-view TOPIC`을 먼저 실행한 뒤 출력인 `/g1_jsj/view_image`를 해당 이미지 채널에 지정한다. 상태 채널은 PC2 ROS 도메인의 `/lowstate`를 읽는다. 카메라와 상태 토픽이 다른 도메인이라면 현재 `serve`가 구독한 도메인의 토픽만 전달된다.

**Windows 개발 컨테이너 내부 · 첫 번째 셸에서 유선 SSH 포워딩 유지**

```bash
ssh -NT -o ExitOnForwardFailure=yes -L 127.0.0.1:8766:127.0.0.1:8766 unitree@192.168.123.164
```

**Windows 개발 컨테이너 내부 · 두 번째 셸에서 로컬 ROS 2 토픽 발행 유지**

```bash
g1 camera remote receive
```

| 원본 PC2 토픽 | 개발 컨테이너에서 읽을 토픽 | 전달되는 데이터 |
| --- | --- | --- |
| `/g1/head/color/image_raw` | `/g1_remote/color/image_raw` | 원래 색상 인코딩과 촬영 시각의 Image |
| `/g1/head/depth/image_rect_raw` | `/g1_remote/depth/image_rect_raw` | 원래 픽셀과 단위를 보존한 깊이 Image |
| `/g1/head/color/camera_info` | `/g1_remote/color/camera_info` | 색상 CameraInfo |
| `/g1/head/depth/camera_info` | `/g1_remote/depth/camera_info` | 깊이 CameraInfo |
| `/lowstate` | `/g1_remote/lowstate` | Unitree HG LowState 원본 필드 |

수신기는 채널에서 첫 메시지가 도착했을 때 해당 토픽 이름을 출력한다. 기본값은 영상과 기체 상태를 각각 최대 5 Hz로 전달한다. `serve --hz N`으로 상한을 바꿀 수 있다. 원래 메시지의 시각과 픽셀을 그대로 전달하며, 이 주기는 원래 카메라 FPS나 기체 제어 주기와 다를 수 있다.

**Windows 개발 컨테이너 내부 · 세 번째 셸에서 표시 방법 선택**

```bash
g1 camera remote tty --topic /g1_remote/color/image_raw
```

`tty`는 수신한 영상의 실제 픽셀을 명암 문자로 그린다. 깊이는 `--topic /g1_remote/depth/image_rect_raw`로 선택한다. 유효 거리 중 가까운 쪽은 밝게, 먼 쪽은 어둡게 보이며 무효 거리 픽셀은 공백이다. 영상 하나만 남기려면 `--once`를 추가한다. 셸의 글꼴·창 크기에 맞춰 `--columns 100 --rows 30`처럼 지정할 수 있다.

**Windows 개발 컨테이너 내부 · RViz2 또는 상태 구독**

```bash
g1 camera rviz
```

RViz2 창은 [Windows Docker 가이드](windows-development-pc.md)의 로컬 noVNC 주소에서 연다. 별도 셸에서 `ros2 topic hz /g1_remote/lowstate`를 실행하면 로컬 상태 구독이 실제로 업데이트되는지 확인할 수 있다.

## 유선 DDS 직접 연결

개발 컨테이너가 이미 유선 DDS 통신이 가능한 환경이면 동일 도메인·유선 인터페이스에서 [직접 DDS 수신 설정](development-pc.md)을 적용한다. `ros2 topic hz /lowstate`와 실제 카메라 토픽의 수신율을 확인한 뒤, `g1 camera remote tty --topic /g1/head/color/image_raw`로 보거나 RViz2의 Image 표시에서 PC2 원본 영상 토픽을 선택한다. 수신이 확인되면 SSH 릴레이 없이 사용할 수 있다.

## 출력 해석

- `Connection refused`는 개발 컨테이너의 SSH 포워딩이 열렸는지 먼저 확인한다. SSH 셸에 `connect failed`가 보이면 PC2의 `remote serve`와 포트 번호를 확인한다.
- `Relay connected` 뒤 `/g1_remote/lowstate`만 보이면 SSH와 상태 구독은 동작한다. PC2의 `g1 camera check`와 `ros2 topic list -t`로 원본 영상 토픽과 실제 프레임 수신 여부를 확인한다.
- `/g1_remote/color/image_raw`가 보이는데 깊이가 없으면 PC2에서 깊이 프로필·깊이 토픽을 따로 확인한다. 네이티브 전방 DDS에 영상 바이트가 들어왔다는 사실만으로 USB 깊이 프레임을 판정할 수 없다.
- 포트 8766을 변경하면 PC2 서버, SSH 포워딩 양쪽 포트, 개발 컨테이너 수신기의 `--port`를 일치시킨다. 실험을 마치면 각 셸에서 Ctrl+C로 종료한다.

소켓은 ROS 2 Foxy의 직렬화된 이미지·보정·상태 메시지만 전달한다. 개발 컨테이너는 같은 ROS 타입으로 역직렬화해 이름이 구분된 토픽에 발행한다. [ROS 2 Foxy 센서 메시지](https://github.com/ros2/common_interfaces/tree/foxy/sensor_msgs) · [Foxy rclpy 직렬화 API](https://github.com/ros2/rclpy/blob/foxy/rclpy/rclpy/serialization.py)
