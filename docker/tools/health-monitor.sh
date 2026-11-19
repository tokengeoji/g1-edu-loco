#!/bin/sh
# Author: Codex (IIC)
# Select the C++ SDK's bundled DDS libraries for this executable only.
export LD_LIBRARY_PATH="/opt/unitree_robotics/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec /opt/g1-tools/bin/g1_health_monitor "$@"
