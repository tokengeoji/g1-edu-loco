FROM jsj-g1-base:foxy

ARG G1_LOCO_BRANCH=main
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /opt/g1-edu-loco

RUN . /etc/os-release \
    && test "$ID" = ubuntu && test "$VERSION_ID" = 20.04 \
    && test -f /opt/ros/foxy/setup.bash \
    && python3 -c 'import sys, numpy; assert sys.version_info[:2] == (3, 8)' \
    && git clone --depth 1 --branch "$G1_LOCO_BRANCH" https://github.com/tokengeoji/g1-edu-loco.git . \
    && git rev-parse HEAD

CMD ["sleep", "infinity"]
