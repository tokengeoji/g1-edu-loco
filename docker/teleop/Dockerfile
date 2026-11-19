# Author: Codex (IIC)
FROM g1-jsj:base

WORKDIR /opt/g1-tools
COPY g1_health_monitor/ /opt/g1-tools/g1_health_monitor/
# Keep the donor target and its native SDK configuration intact.
RUN cmake -S g1_health_monitor -B /tmp/g1-health-build \
        -Dunitree_sdk2_DIR=/opt/unitree_robotics/lib/cmake/unitree_sdk2 && \
    cmake --build /tmp/g1-health-build --parallel 2 && \
    install -D -m 0755 /tmp/g1-health-build/g1_health_monitor /opt/g1-tools/bin/g1_health_monitor && \
    rm -rf /tmp/g1-health-build
COPY docker/teleop/health-monitor.sh /usr/local/bin/g1_health_monitor
RUN chmod 0755 /usr/local/bin/g1_health_monitor && \
    LD_LIBRARY_PATH=/opt/unitree_robotics/lib ldd /opt/g1-tools/bin/g1_health_monitor > /tmp/health-libs && \
    ! grep -q 'not found' /tmp/health-libs

COPY g1_teleop/ /opt/g1-tools/g1_teleop/
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN python3 -c 'from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient' && \
    python3 -m unittest discover -s g1_teleop -t . && python3 -m g1_teleop --help
ENTRYPOINT ["python3", "-m", "g1_teleop"]
CMD ["--dry-run"]
