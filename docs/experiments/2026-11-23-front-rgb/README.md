<!-- Author: Codex (IIC) -->
# 전방 DDS 영상 수신 실험 · 2026년 11월 23일

G1 PC2에서 `rt/frontvideostream`을 구독해 ROS 2 컬러 영상으로 변환한 실험 코드다. `eth0`, DDS 도메인 0에서 5.1초 동안 영상 바이트가 담긴 720p 패킷 72개와 360p 패킷 76개를 수신했다. 별도의 8초 관측에서 ROS 토픽의 640×360 `bgr8` 영상 23장을 확인했다. 같은 기간 머리 D435i의 ROS 컬러·깊이 토픽은 모두 발행자 0개, 수신 0장이었다. 전방 영상만으로는 촬영한 센서의 물리적 위치나 깊이값을 판정할 수 없다.

1. [receive.py](receive.py)는 Eclipse Cyclone DDS에서 발행자가 알린 타입을 조회하고 타입 식별자를 비교한다. 이 기체가 알린 필드는 `time_frame`, `resolution`, `data`였다. 설치된 Unitree Python SDK의 같은 이름의 고정 메시지 정의는 해상도별 바이트 배열을 사용한다. 이 차이 때문에 고정 정의를 쓴 구독자는 매칭이 0건이었다. 실험 수신기는 발행자의 타입으로 Unitree `ChannelSubscriber`를 생성한다. [Unitree 고정 메시지 정의](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/unitree_sdk2py/idl/unitree_go/msg/dds_/_Go2FrontVideoData_.py) · [Unitree 구독 API](https://github.com/unitreerobotics/unitree_sdk2_python/blob/814556d15970dd2ecf1c9984e845ca02ab07e206/unitree_sdk2py/core/channel.py)
2. 수신기는 360p 스트림의 H.264 SPS 시작 코드를 기다렸다가 바이트를 [bridge.cpp](bridge.cpp)의 표준 입력에 전달한다. 디코더는 OpenCV의 FFmpeg 백엔드를 사용한다. 프레임 발행 간격을 최소 180 ms로 제한하고 `/g1/unitree_front/color/image_raw`에 ROS 2 이미지를 발행한다. 헤더 시각은 PC2에서 디코딩한 후 부여하므로 센서 촬영 시각을 재현하지 않는다. [ROS 2 Foxy Image 메시지](https://github.com/ros2/common_interfaces/blob/foxy/sensor_msgs/msg/Image.msg)

### 오프라인 빌드 검증

**PC2 컨테이너 내부 · 저장소 체크아웃의 셸**

```bash
source /opt/ros/foxy/setup.bash
src="$(git rev-parse --show-toplevel)/docs/experiments/2026-11-23-front-rgb"
cmake -S "$src" -B "$src/build"
cmake --build "$src/build" --target front_color_bridge
python3 -c 'from pathlib import Path; import sys; p=Path(sys.argv[1]); compile(p.read_text(), str(p), "exec")' "$src/receive.py"
```

빌드 검사는 카메라·DDS 연결 없이 수행된다. 실험 소스가 찾는 실행 파일 경로는 `receive.py` 옆의 `build/front_color_bridge`다. 수신기의 Unitree 인터페이스는 `eth0`, 도메인은 0으로 고정되어 있으며, ROS 2 발행기는 실행 환경의 NIC와 도메인 설정을 사용한다. PC2에서 사용한 소스에 작성자 표기를 추가했고, 빌드 대상은 프로젝트 규칙에 맞춰 C++17로 지정했다. 운동 제어 API 호출은 없다.
