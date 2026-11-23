<!-- Author: Codex (IIC) -->
# G1 헤드 카메라 수신 확인

연구실 G1의 유선 `eth0`·도메인 0에서 전방 DDS 토픽 `rt/frontvideostream` 발행자를 발견했다. 설치된 SDK 메시지로는 5초간 유효 표본이 없었다. 이후 기체가 광고한 메시지의 필드 구성을 사용해 5.1초간 영상 패킷 148개를 수신했고, 별도 관측에서는 640×360 컬러 영상 23장을 디코딩했다. 이 전방 컬러의 물리 카메라는 확정되지 않았다. 같은 네트워크에서 머리 D435i의 ROS RGB·깊이 발행자는 0개였고, PC2의 USB 장치 목록에서는 D435i가 보였다. [원본 관측과 실험 수신기](teleop-802-evidence.md#같은-날의-카메라계단-상태)

**G1 호스트 · 실행 중인 통합 컨테이너 접속**

```bash
docker exec -it jsj-g1-tools bash
```

**컨테이너 내부 · 네트워크 영상과 USB 깊이 검사**

```bash
export G1_CAMERA_IFACE=eth0 G1_CAMERA_DOMAIN=0
g1 camera check --seconds 5
```

5초는 경로별 관측 시간이다. 도구는 ROS 2 표준 영상 토픽과 전방 DDS 메시지를 각각 구독한 뒤, 공식 RealSense SDK로 D435i 원시 깊이 스트림을 연다. USB 스트림은 검사가 끝나면 닫힌다. 한 경로에서 오류가 발생해도 나머지 검사 결과를 볼 수 있다.

| 출력 | 판독 |
| --- | --- |
| `ros.ros_images`에서 `samples_received > 0` | 해당 토픽에서 영상 메시지를 수신했다. 실제 광학 프레임, 인코딩과 발행자를 확인하고 [ROS 영상 보기](../README.md#camera)에서 해당 토픽을 선택한다. |
| `front_video_dds.reader_matches > 0`이면서 `samples_read = 0` | DDS 구독자가 발행자와 연결됐지만 관측 시간에 유효한 메시지가 오지 않았다. |
| `front_video_dds.status = DDS_NO_SAMPLES`, `reader_matches = 0` | 발행자는 탐색됐고 구독자 매칭은 관측되지 않았다. `incompatible_qos_events > 0`이면 Cyclone DDS가 QoS 불일치를 보고했다. |
| `front_video_dds.samples_with_video_bytes > 0` | 하나 이상의 메시지에 영상 바이트가 있다. 이 검사는 코덱·영상 내용을 디코딩하지 않는다. 설치 SDK의 형식은 해상도별 바이트 배열을, 현장 발행자의 형식은 해상도 값과 영상 바이트 배열을 담는다. |
| `usb_depth.frames_with_valid_depth > 0`, `depth_scale_m > 0` | D435i에서 Z16 깊이 프레임을 받았고 0이 아닌 픽셀과 SDK가 읽은 미터 환산값을 확인했다. |
| `usb_depth.frames > 0`, `frames_with_valid_depth = 0` | 받은 프레임에서 유효 거리 픽셀이 하나도 없었다. 계단 치수를 추정할 관측이 부족하다. |
| `usb_depth.status = DEVICE_NOT_VISIBLE` | 현재 컨테이너의 SDK에서 장치를 찾지 못했다. [USB 장치 확인 방법](../README.md#create)으로 PC2의 장치 목록과 컨테이너에 전달한 장치 경로를 비교한다. |
| `DEVICE_BUSY` 또는 `DEPTH_PROFILE_UNSUPPORTED` | 점유한 프로그램이 제공하는 깊이 토픽을 확인한다. 프로필 오류라면 `g1 camera probe-usb`에서 장치가 지원하는 조합을 보고 `--width`, `--height`, `--fps`로 선택한다. |

## 전방 DDS 영상 바이트 확인

**컨테이너 내부 · PC2의 전방 DDS 발행자 읽기**

```bash
export G1_CAMERA_IFACE=eth0 G1_CAMERA_DOMAIN=0
g1 camera tty-dds --topic rt/frontvideostream \
  --type 'unitree_go::msg::dds_::Go2FrontVideoData_' --seconds 5
```

이 명령은 발행자가 광고한 타입과 설치된 SDK의 타입을 대조한다. 출력의 `idl_source=unitree_sdk`는 SDK에 포함된 타입으로 읽었을 때, `writer_type`은 Cyclone DDS가 발행자의 타입 설명을 받아 사용했을 때 표시된다. 타입 ID가 없는 발행자에는 이 토픽의 설치 SDK 타입을 시도한다. `--idl-class`를 명시했을 때 광고된 타입 ID와 다르면 `DDS_TYPE_MISMATCH`가 표시된다. `tty-dds`는 메시지 필드와 영상 바이트 수를 출력한다.

## USB에서 실시간 컬러·깊이 영상 켜기

`check` 결과에서 이미 헤드 D435i의 ROS 2 영상을 받고 있으면 해당 토픽을 그대로 구독한다. 기본 D435i가 PC2의 USB 장치로 보이고 기존 프로그램이 점유하지 않은 경우에는 아래 명령으로 SDK 스트림과 ROS 2 발행을 함께 시작한다. 먼저 [USB 장치를 포함하는 컨테이너 생성 절차](../README.md#create)를 확인한다.

**컨테이너 내부 · G1 PC2에서 카메라 켜기**

```bash
G1_CAMERA_IFACE=eth0 G1_CAMERA_DOMAIN=0 g1 camera start
```

이 경로는 공식 `pyrealsense2.pipeline.start(config)`로 장치를 열고 SDK의 깊이 단위와 카메라 내부 파라미터를 읽는다. 프로젝트 ROS 2 발행기가 영상과 보정 정보를 아래 토픽으로 보낸다. 기본값은 컬러와 깊이 각각 640×480, 30 fps다. 첫 프레임을 실제 발행하면 스트림 이름·크기·인코딩과 토픽을 출력한다. 터미널을 열어 두고 사용한 뒤 Ctrl+C로 카메라를 해제한다. 깊이만 보려면 `g1 camera start --stream depth`, 색상만 보려면 `--stream color`를 사용한다. 장치가 지원하는 조합에 맞춰 `--width`, `--height`, `--fps`를 지정할 수 있다. 선택한 스트림에서 5초 이상 새 프레임이 없으면 종료하고 해당 스트림을 알려 준다.

| ROS 2 이미지 토픽 | 함께 발행하는 보정 정보 | 영상 의미 |
| --- | --- | --- |
| `/g1/head/color/image_raw` | `/g1/head/color/camera_info` | `bgr8`, 컬러 카메라 광학 좌표계 |
| `/g1/head/depth/image_rect_raw` | `/g1/head/depth/camera_info` | `16UC1`, 깊이 카메라 광학 좌표계. 장치의 프레임별 SDK 단위를 읽어 밀리미터로 환산하며 0은 유효 거리 없음 |

각 이미지와 해당 `CameraInfo`는 같은 촬영 시각과 광학 프레임을 사용한다. 색상과 깊이는 각각 고유한 카메라 좌표계에 있다. 센서 데이터 QoS는 Best Effort, Volatile이다. 카메라를 켜 둔 채 깊이 기록까지 하려면 별도 셸에서 ROS 토픽을 구독한다. USB 장치를 다시 열면 장치가 사용 중이라는 오류가 날 수 있다.

**컨테이너 내부 · G1 PC2에서 발행 중인 깊이를 5초간 기록**

```bash
G1_CAMERA_IFACE=eth0 G1_CAMERA_DOMAIN=0 g1 camera record-ros \
  --run "head-$(date +%Y%m%d-%H%M%S)" --seconds 5 \
  --depth-topic /g1/head/depth/image_rect_raw --info-topic /g1/head/depth/camera_info \
  --depth-scale-m 0.001
```

여기서 `0.001`은 이 발행기의 출력 1밀리미터를 미터로 바꾸는 값이다. 다른 발행기의 깊이 단위는 해당 드라이버에서 확인한다. [RealSense SDK 파이썬 예제](https://github.com/realsenseai/librealsense/tree/v2.54.1/wrappers/python/examples) · [RealSense ROS 보정 정보](https://github.com/realsenseai/realsense-ros/blob/960306819f45006ca3f903aa046bed32c509679a/realsense2_camera/src/base_realsense_node.cpp#L795) · [Windows 개발 PC에서 영상 보기](development-pc.md)

## USB 깊이 미리보기

**컨테이너 내부 · 실제 USB 깊이 화면 한 장 저장**

```bash
mkdir -p /workspace/runs/camera-preview
g1 camera check --seconds 5 --depth-preview /workspace/runs/camera-preview/head-check.png
```

`usb_depth.depth_preview`에 경로와 프레임 번호가 표시되면 실제 관측한 깊이 화면이 저장됐다. PNG는 브라우저에서 열 수 있는 그레이스케일 영상으로, 무효 픽셀은 검정, 수신 프레임에서 가장 가까운 유효 픽셀은 흰색이다. 매번 새 파일명을 사용한다. 결과의 `near_raw`·`far_raw`에 `depth_scale_m`을 곱하면 그 프레임에서 표시한 최소·최대 거리를 미터로 읽을 수 있다. 계단 계산에는 [원시 깊이 기록과 실측 보정](../README.md#geometry)을 사용한다.

**컨테이너 내부 · 미리보기 PNG를 브라우저로 확인**

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory /workspace/runs/camera-preview
```

저장소의 `--network host` 구성에서는 PC2 브라우저로 [실제 깊이 화면](http://127.0.0.1:8765/head-check.png)을 연다. 개발 PC의 브라우저로 보려면 유선 SSH 터미널을 하나 더 열고 아래 명령으로 포트를 전달한다. `192.168.123.164`는 연구실에서 확인한 PC2 주소다.

**외부 개발 PC · PC2 SSH 포트 전달**

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18765:127.0.0.1:8765 unitree@192.168.123.164
```

개발 PC의 브라우저에서 [전달된 깊이 화면](http://127.0.0.1:18765/head-check.png)을 연다. 확인 후 포트 전달과 HTTP 서버 양쪽 터미널에서 각각 Ctrl+C로 종료한다.

셸 종료 코드 0은 ROS 영상 표본, DDS 영상 바이트 또는 유효 USB 깊이 중 하나 이상을 받았을 때 반환한다. 미리보기 파일을 요청했다면 파일 저장까지 성공해야 한다. 계단에 쓸 USB 깊이 여부는 `usb_depth` 항목으로 판단한다. ROS로 기록할 때는 `16UC1` 영상과 같은 촬영 시각·광학 프레임의 `CameraInfo`, 검증한 깊이 스케일이 필요하다.

[Unitree G1 Depth Camera Routine](https://support.unitree.com/home/en/G1_developer/depth_camera_instruction) · [Unitree Python SDK 전방 영상 메시지 정의](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/unitree_sdk2py/idl/unitree_go/msg/dds_/_Go2FrontVideoData_.py)
