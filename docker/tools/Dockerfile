# Author: Codex (IIC)
FROM g1-jsj:base

LABEL org.iic.g1.role="operator-tools"
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-foxy-rviz2 ros-foxy-rviz-default-plugins ros-foxy-sensor-msgs \
      ros-foxy-image-transport ros-foxy-compressed-image-transport \
      ros-foxy-compressed-depth-image-transport \
      libgl1-mesa-dri libglx-mesa0 libusb-1.0-0 libudev1 iproute2 \
      xvfb xauth x11-utils x11vnc novnc websockify curl \
    && rm -rf /var/lib/apt/lists/*

# Official librealsense wheel for CPython 3.8 on aarch64.
RUN printf '%s\n' 'pyrealsense2==2.54.1.5217 --hash=sha256:933b6948bb995d8b98b063bd7d555b3b9c043d8f041352c035b0fdb0902e13e7' \
      | python3 -m pip install --no-cache-dir --no-deps --only-binary=:all: --require-hashes -r /dev/stdin

WORKDIR /opt/g1-tools
COPY src/g1_health_monitor/ ./g1_health_monitor/
# Build the unchanged monitor against the same Unitree C++ SDK it uses at run time.
RUN cmake -S g1_health_monitor -B /tmp/g1-health-build \
        -Dunitree_sdk2_DIR=/opt/unitree_robotics/lib/cmake/unitree_sdk2 && \
    cmake --build /tmp/g1-health-build --parallel 2 && \
    install -D -m 0755 /tmp/g1-health-build/g1_health_monitor /opt/g1-tools/bin/g1_health_monitor && \
    rm -rf /tmp/g1-health-build
COPY docker/tools/health-monitor.sh /usr/local/bin/g1_health_monitor
RUN chmod 0755 /usr/local/bin/g1_health_monitor && \
    LD_LIBRARY_PATH=/opt/unitree_robotics/lib ldd /opt/g1-tools/bin/g1_health_monitor > /tmp/health-libs && \
    ! grep -q 'not found' /tmp/health-libs

COPY src/g1_teleop/ ./g1_teleop/
COPY src/g1stairs/ ./g1stairs/
COPY config/ ./config/
COPY docker/tools/g1 /usr/local/bin/g1
COPY docker/tools/pc2.sh /usr/local/bin/g1-pc2-create-command

ENV BASH_ENV=/opt/g1/ros_env.sh \
    LIBGL_ALWAYS_SOFTWARE=1 QT_X11_NO_MITSHM=1 \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/g1-tools:${PYTHONPATH}
RUN set -e; chmod 0755 /usr/local/bin/g1 /usr/local/bin/g1-pc2-create-command; mkdir -p /run/g1-tools /workspace/runs; \
    bash -n /usr/local/bin/g1; bash -n /usr/local/bin/g1-pc2-create-command; bash -n g1stairs/camera/resources/rviz-web.sh; \
    test -s g1stairs/camera/resources/image.rviz; test -s /usr/share/novnc/vnc.html; \
    for tool in rviz2 Xvfb xvfb-run xauth xwininfo x11vnc websockify; do command -v "$tool" >/dev/null; done; \
    python3 -c 'from importlib.metadata import version; from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient; assert version("pyrealsense2") == "2.54.1.5217"'; \
    g1 monitor --help >/dev/null; g1 teleop --help >/dev/null; \
    g1 camera --help >/dev/null; g1 stairs --help >/dev/null

# Mark G1 operator shells so interactive commands are entered in the right place.
RUN printf '%s\n' 'PS1="[jsj-g1-tools] \w\\$ "' >> /root/.bashrc

WORKDIR /workspace
CMD ["sleep", "infinity"]
