# PC2 공통 베이스 이미지 만들기

`jsj-g1-base:foxy`는 모니터링·카메라·계단 측정 컨테이너의 공통 이미지입니다. Ubuntu 20.04 ARM64, ROS 2 Foxy, Python 3.8 환경에 Unitree SDK2(C++·Python), Unitree ROS 2 메시지, CycloneDDS 0.10.2와 Git을 설치합니다. [Dockerfile](Dockerfile)

<a id="build"></a>

## 1. 공통 베이스 이미지 빌드

PC2의 **Bash 터미널**에서 아래 블록 전체를 한 번 붙여넣으세요. Docker가 이 저장소의 Dockerfile을 읽어 `jsj-g1-base:foxy`를 빌드합니다. SDK 설치와 Git 복제는 이미지 빌드 안에서 실행됩니다. PC2의 L4T가 R35.3.1이면 부모 이미지가 자동 선택됩니다. 다른 버전이면 안내에 따라 해당 PC2와 호환되는 Ubuntu 20.04·ROS 2 Foxy ARM64 부모 이미지 태그를 입력하세요.

```bash
(
  set -euo pipefail
  if grep -Eq '^#[[:space:]]+R35[[:space:]].*REVISION:[[:space:]]*3\.1([,[:space:]]|$)' /etc/nv_tegra_release 2>/dev/null; then
    parent='dustynv/ros:foxy-ros-base-l4t-r35.3.1'
  else
    cat /etc/nv_tegra_release 2>/dev/null || true
    read -rp '이 PC2의 L4T와 호환되는 ARM64 Ubuntu 20.04/Foxy 이미지 태그(미확인 시 Enter로 종료): ' parent
    [[ -n "$parent" ]] || exit 1
  fi

  if ! docker image inspect "$parent" >/dev/null 2>&1; then
    docker pull --platform linux/arm64 "$parent"
  fi
  [[ "$(docker image inspect --format '{{.Os}}/{{.Architecture}} {{if .Config.Volumes}}volumes{{else}}none{{end}}' "$parent")" == 'linux/arm64 none' ]] || {
    echo '부모 이미지의 플랫폼과 VOLUME 선언을 확인하세요.' >&2
    exit 1
  }

  docker build --platform linux/arm64 --build-arg BASE_IMAGE="$parent" \
    --tag jsj-g1-base:foxy \
    https://raw.githubusercontent.com/tokengeoji/g1-edu-loco/main/docker/base/Dockerfile
  docker image inspect --format 'jsj-g1-base:foxy  {{.Os}}/{{.Architecture}}  {{.Id}}' jsj-g1-base:foxy
)
```

마지막 줄에 `jsj-g1-base:foxy  linux/arm64  sha256:…`가 출력되면 빌드가 끝난 것입니다. [부모 이미지 배포처](https://hub.docker.com/r/dustynv/ros/tags) · [Docker 공식 빌드 문서](https://docs.docker.com/build/concepts/context/#how-to-build-without-a-context)

<a id="sdk"></a>

## 2. 이미지 안의 SDK 확인

PC2 터미널에 아래 블록을 붙여넣으세요. 일회성 컨테이너에서 실제 SDK와 메시지 타입을 불러옵니다. 마지막에 `Unitree SDK2 및 Foxy 메시지 확인 완료`가 출력되면 [모니터링 컨테이너](../../README.md#monitoring) 또는 [카메라 컨테이너](../../README.md#camera)를 만드세요.

```bash
docker run --rm --name jsj-base-check --pull never --network none \
  --cap-drop ALL --security-opt no-new-privileges:true jsj-g1-base:foxy \
  bash -ec '
    python3 --version
    for pkg in unitree_go unitree_hg unitree_api; do ros2 pkg prefix "$pkg"; done
    python3 -c "import cyclonedds, numpy, cv2; from unitree_sdk2py.core.channel import ChannelSubscriber; from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_"
    echo "Unitree SDK2 및 Foxy 메시지 확인 완료"
  '
```

설치 순서와 구성은 프로젝트의 공통 베이스 정의를 따릅니다. Foxy를 불러오는 빌드 단계에서는 초기화 스크립트가 아직 설정되지 않은 셸 변수를 참조할 수 있어 Bash의 `nounset` 옵션을 사용하지 않습니다. 실제 PC2 빌드와 하드웨어 수신은 미확인입니다. [프로젝트 베이스 정의](https://app.notion.com/p/41a3c6661b7d8117a89cf15e9824c6fa) · [Unitree ROS 2](https://github.com/unitreerobotics/unitree_ros2) · [Unitree SDK2](https://github.com/unitreerobotics/unitree_sdk2) · [Unitree SDK2 Python](https://github.com/unitreerobotics/unitree_sdk2_python)
