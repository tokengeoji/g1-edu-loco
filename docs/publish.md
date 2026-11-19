# Docker 이미지 빌드와 게시

배포용 PC의 작업은 `docker pull`과 컨테이너 실행입니다. 게시용 이미지는 프로젝트 규칙에 따라 `jsj-g1-base:foxy`가 준비된 G1 EDU PC2에서 Docker CLI로 빌드합니다. 기반 이미지는 Ubuntu 20.04, ROS 2 Foxy, Python 3.8, Unitree SDK2가 준비된 실제 PC2 구성을 사용합니다.

## 1. PC2 이미지 확인 및 빌드

기반 이미지의 OS·아키텍처와 선언된 볼륨 수를 확인합니다. 대상 PC와 같은 아키텍처를 사용하고, 볼륨 수는 0이어야 합니다. `G1_LOCO_REVISION`에는 이 Dockerfile과 함께 검토한 GitHub 커밋의 전체 SHA를 지정합니다. 클론에 해당하는 Git 초기화·가져오기는 빌드 레이어 안에서만 실행됩니다.

```bash
docker image inspect jsj-g1-base:foxy \
  --format '{{.Os}}/{{.Architecture}} volumes={{len .Config.Volumes}}'

(
  set -eu
  : "${G1_LOCO_REVISION:?Set the full GitHub commit SHA}"
  test "$(docker image inspect jsj-g1-base:foxy --format '{{len .Config.Volumes}}')" = 0
  for target in monitoring geometry realsense; do
    docker build --pull=false --target "$target" \
      --build-arg G1_LOCO_REVISION="$G1_LOCO_REVISION" \
      -t "jsj-g1-$target:foxy" - <<'DOCKERFILE'
FROM jsj-g1-base:foxy AS source

ARG G1_LOCO_REVISION
WORKDIR /opt/g1-edu-loco
RUN test -n "$G1_LOCO_REVISION" \
    && git init -q \
    && git fetch --quiet --depth 1 https://github.com/tokengeoji/g1-edu-loco.git "$G1_LOCO_REVISION" \
    && git checkout --quiet --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "$G1_LOCO_REVISION" \
    && rm -rf .git

FROM jsj-g1-base:foxy AS common

ARG G1_LOCO_REVISION
LABEL org.opencontainers.image.source="https://github.com/tokengeoji/g1-edu-loco" \
      org.opencontainers.image.revision="$G1_LOCO_REVISION"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /opt/g1-edu-loco
COPY --from=source /opt/g1-edu-loco/ .
RUN . /etc/os-release \
    && test "$ID" = ubuntu && test "$VERSION_ID" = 20.04 \
    && test -f /opt/ros/foxy/setup.bash \
    && python3 -c 'import sys, numpy; assert sys.version_info[:2] == (3, 8)'
CMD ["sleep", "infinity"]

FROM common AS monitoring
RUN python3 -c 'import cyclonedds; from unitree_sdk2py.core.channel import ChannelSubscriber; from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_'

FROM common AS geometry

FROM common AS realsense
RUN python3 -m pip install --no-cache-dir --only-binary=:all: 'pyrealsense2==2.54.1.5217' \
    && python3 -c 'import pyrealsense2; assert hasattr(pyrealsense2, "context")'
DOCKERFILE
  done
)
```

RealSense 타깃에는 Unitree 개발 예제와 같은 SDK 계열의 `pyrealsense2==2.54.1.5217`을 설치합니다. 공식 배포에는 Python 3.8 Linux ARM64 휠이 있습니다. [Unitree Depth Camera Routine](https://support.unitree.com/home/en/G1_developer/depth_camera_instruction) · [RealSense Python 배포 파일](https://pypi.org/project/pyrealsense2/2.54.1.5217/#files)

## 2. 실제 장치 연결과 게시

[실기 연결 절차](../README.md#실기-연결-확인)에서 `jsj/iiclab:<기능>` 대신 동일한 로컬 검증용 이미지 `jsj-g1-<기능>:foxy`를 사용합니다. 검증 입력은 D435i 원본 프레임 또는 G1의 `rt/lowstate`입니다. 계단 형상은 해당 D435i가 기록한 실측 계단으로 확인합니다. 기존 컨테이너의 이름과 기록을 확인한 후 작업합니다.

유효한 실기 기록이 확인된 태그만 게시합니다. 게시 전에 해당 네임스페이스의 쓰기 권한과 이미 구성된 배포 인증을 확인합니다. 이미지를 푸시하면 기반 이미지 레이어도 포함되므로, 게시 권한과 기반 레이어의 공개 범위를 확인합니다. 아래 명령은 프로젝트 기록이 없는 빌드 산출물에 태그를 붙입니다. 예시에서 `FEATURE`는 `realsense`, `monitoring`, `geometry` 중 검증된 기능입니다.

```bash
(
  set -eu
  case "${FEATURE:-}" in
    realsense|monitoring|geometry) ;;
    *) printf '%s\n' 'Set FEATURE to a verified feature.' >&2; exit 2 ;;
  esac
  docker tag "jsj-g1-$FEATURE:foxy" "jsj/iiclab:$FEATURE"
  docker push "jsj/iiclab:$FEATURE"
  docker manifest inspect "jsj/iiclab:$FEATURE"
)
```

[Docker 이미지 게시](https://docs.docker.com/docker-hub/repos/manage/hub-images/push/) · [Docker 이미지 가져오기](https://docs.docker.com/reference/cli/docker/image/pull/)
