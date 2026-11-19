# G1 PC2 공통 CPU 이미지

PC2에서 `bash docker/camera/pc2.sh build`를 실행하면 공통 이미지 `g1-jsj:base`와 카메라 이미지 `g1-jsj:realsense`가 차례로 생성됩니다. PC2에 다운로드한 Ubuntu ARM64 이미지 `jsj-g1-base:ubuntu20.04-cpu`가 있으면 재사용합니다. 처음 설치할 때는 Canonical의 날짜가 고정된 컨테이너용 Focal ARM64 루트 파일시스템을 `docker import`로 로컬 Docker에 등록합니다. 두 이미지 모두 PC2의 Docker Engine을 사용하는 기본 빌더에서 빌드합니다. [Ubuntu rootfs](https://partner-images.canonical.com/oci/focal/20250530.1/) · [프로젝트 실행 명령](../../README.md#pc2)

| 구성 | `g1-jsj:base`에 들어가는 내용 |
|---|---|
| 운영체제·언어 | Ubuntu 20.04 ARM64, Python 3.8 |
| ROS 2 | Foxy ros-base, sensor_msgs, ros2 CLI |
| 통신 | Cyclone DDS C 및 Python 0.10.2, Foxy rmw_cyclonedds_cpp |
| Unitree | Unitree SDK2 C++ 및 Python, unitree_hg·unitree_go·unitree_api 메시지 |

카메라 전용 RViz2, CPU 렌더링용 Mesa, D435i Python SDK는 `g1-jsj:realsense`에 설치됩니다. Unitree의 G1 개발 가이드는 Ubuntu 20.04에서 Foxy를 사용한 예제와 로봇 측 Cyclone DDS 0.10.2를 설명합니다. [Unitree ROS 2](https://github.com/unitreerobotics/unitree_ros2) · [Depth Camera Routine](https://support.unitree.com/home/en/G1_developer/depth_camera_instruction)

## PC2에서 버전 확인

```bash
docker run --rm --runtime=runc --network none g1-jsj:base bash -ec '
  . /etc/os-release
  echo "$PRETTY_NAME / $(dpkg --print-architecture) / ROS $ROS_DISTRO"
  python3 -c "from importlib.metadata import version; import rclpy; print(version(\"cyclonedds\"), rclpy.get_rmw_implementation_identifier())"
  ros2 pkg prefix unitree_hg
'
```

정상 출력에는 Ubuntu 20.04, arm64, foxy, 0.10.2, rmw_cyclonedds_cpp와 Unitree 메시지가 설치된 경로가 포함됩니다. DDS 도메인과 네트워크 인터페이스는 발행자 환경에 맞춰 [카메라 실행 단계](../../README.md#camera)에서 지정합니다.
