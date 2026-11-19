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
