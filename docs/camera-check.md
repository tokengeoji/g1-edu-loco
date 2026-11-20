<!-- Author: Codex (IIC) -->
# G1 헤드 카메라 수신 확인

연구실 G1의 유선 `eth0`, 도메인 0에서 8초간 탐색했을 때 표준 ROS 2 영상은 발견되지 않았다. Unitree 전방 영상 토픽 `rt/frontvideostream`의 발행자는 발견됐다. 공식 타입으로 5초간 구독한 결과는 `DDS_NO_SAMPLES`였다. 이 두 기록은 헤드 카메라가 꺼졌는지, PC2에 연결됐는지, 원시 깊이를 받을 수 있는지까지 설명하지 않는다.

**G1 호스트 · 실행 중인 통합 컨테이너 접속**

```bash
docker exec -it jsj-g1-tools bash
```

**컨테이너 내부 · 네트워크 영상과 USB 깊이 검사**

```bash
export G1_CAMERA_IFACE=eth0 G1_CAMERA_DOMAIN=0
g1 camera check --seconds 5
```

5초는 경로별 관측 시간이다. 도구는 ROS 2 표준 영상 토픽을 구독하고, Unitree SDK의 공식 메시지 정의로 전방 DDS를 구독한 뒤, RealSense SDK로 D435i 원시 깊이 스트림을 연다. USB 스트림은 검사가 끝나면 닫힌다. 한 경로에서 오류가 발생해도 나머지 검사 결과를 볼 수 있다.

| 출력 | 판독 |
| --- | --- |
| `ros.ros_images`에서 `samples_received > 0` | 해당 토픽에서 영상 메시지를 수신했다. 실제 광학 프레임, 인코딩과 발행자를 확인하고 [ROS 영상 보기](../README.md#camera)에서 해당 토픽을 선택한다. |
| `front_video_dds.reader_matches > 0`이면서 `samples_read = 0` | DDS 구독자가 발행자와 연결됐지만 관측 시간에 유효한 메시지가 오지 않았다. |
| `front_video_dds.status = DDS_NO_SAMPLES`, `reader_matches = 0` | 발행자는 탐색됐고 구독자 매칭은 관측되지 않았다. `incompatible_qos_events > 0`이면 Cyclone DDS가 QoS 불일치를 보고했다. |
| `front_video_dds.samples_with_video_bytes > 0` | 하나 이상의 메시지에 영상 바이트가 있다. 이 검사는 코덱·영상 내용을 디코딩하지 않는다. 공식 타입에는 세 해상도의 바이트 배열과 시간 필드가 있다. |
| `usb_depth.frames_with_valid_depth > 0`, `depth_scale_m > 0` | D435i에서 Z16 깊이 프레임을 받았고 0이 아닌 픽셀과 SDK가 읽은 미터 환산값을 확인했다. |
| `usb_depth.frames > 0`, `frames_with_valid_depth = 0` | 받은 프레임에서 유효 거리 픽셀이 하나도 없었다. 계단 치수를 추정할 관측이 부족하다. |
| `usb_depth.status = DEVICE_NOT_VISIBLE` | 현재 컨테이너의 SDK에서 장치를 찾지 못했다. [USB 장치 확인 방법](../README.md#create)으로 PC2의 장치 목록과 컨테이너에 전달한 장치 경로를 비교한다. |
| `DEVICE_BUSY` 또는 `DEPTH_PROFILE_UNSUPPORTED` | 점유한 프로그램이 제공하는 깊이 토픽을 확인한다. 프로필 오류라면 `g1 camera probe-usb`에서 장치가 지원하는 조합을 보고 `--width`, `--height`, `--fps`로 선택한다. |

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
