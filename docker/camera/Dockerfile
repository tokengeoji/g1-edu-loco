FROM g1-jsj:base

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-foxy-rviz2 ros-foxy-rviz-default-plugins ros-foxy-sensor-msgs \
      ros-foxy-image-transport ros-foxy-compressed-image-transport \
      ros-foxy-compressed-depth-image-transport \
      libgl1-mesa-dri libglx-mesa0 libusb-1.0-0 libudev1 iproute2 \
      xvfb xauth x11-utils x11vnc novnc websockify curl \
    && rm -rf /var/lib/apt/lists/*

# CPython 3.8 / aarch64 wheel published for librealsense 2.54.1.
RUN printf '%s\n' 'pyrealsense2==2.54.1.5217 --hash=sha256:933b6948bb995d8b98b063bd7d555b3b9c043d8f041352c035b0fdb0902e13e7' \
      | python3 -m pip install --no-cache-dir --no-deps --only-binary=:all: --require-hashes -r /dev/stdin \
    && python3 -c 'from pyrealsense2 import context, pipeline, stream'

WORKDIR /opt/g1-edu-loco
COPY g1stairs/ ./g1stairs/
COPY config/ ./config/
COPY docker/camera/image.rviz /opt/g1/camera.rviz
COPY docker/camera/pc2.sh /opt/g1/pc2.sh
COPY docker/camera/rviz-web.sh /opt/g1/rviz-web.sh

# A non-interactive Bash sources BASH_ENV before executing the supplied command.
ENV BASH_ENV=/opt/g1/ros_env.sh \
    LIBGL_ALWAYS_SOFTWARE=1 \
    QT_X11_NO_MITSHM=1 \
    PYTHONUNBUFFERED=1
RUN set -e; python3 -m g1stairs.camera --help >/dev/null; \
    for tool in rviz2 Xvfb xvfb-run xauth xwininfo x11vnc websockify; do command -v "$tool" >/dev/null; done; \
    test -s /usr/share/novnc/vnc.html; bash -n /opt/g1/rviz-web.sh; bash -n /opt/g1/pc2.sh
ENTRYPOINT ["/bin/bash", "-c", "exec \"$@\"", "g1-camera"]
CMD ["python3", "-m", "g1stairs.camera", "discover"]
