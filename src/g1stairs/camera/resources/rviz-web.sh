#!/usr/bin/env bash
# Author: Codex (IIC project)
# Runs inside xvfb-run. Xauthority, browser assets and VNC state are all local
# to this container. Only the RViz window is exposed on the loopback interface.
set -euo pipefail
umask 077

port=${G1_RVIZ_PORT:-6080}
[[ $port =~ ^[0-9]{1,5}$ ]] && ((10#$port >= 1024 && 10#$port <= 65535)) || {
  echo 'G1_RVIZ_PORT must be an integer between 1024 and 65535.' >&2
  exit 2
}
port=$((10#$port))
self_test=false
if [[ ${1:-} == --self-test ]]; then self_test=true; shift; fi
if [[ $self_test == false && ! -t 1 ]]; then
  echo '실행 중인 컨테이너의 대화형 셸에서 g1 camera rviz를 실행하세요. PC2 호스트에서는 docker exec -it jsj-g1-tools g1 camera rviz를 사용하세요.' >&2
  exit 2
fi
state=$(mktemp -d)
children=()
cleanup() {
  if ((${#children[@]})); then
    kill "${children[@]}" 2>/dev/null || :
    wait "${children[@]}" 2>/dev/null || :
  fi
  rm -rf -- "$state"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export XDG_RUNTIME_DIR="$state"

# A VNC password has eight significant characters. Pass it through a
# container-private file so it never appears in a process command line.
python3 -c 'import secrets, string; print("".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8)))' > "$state/password"
: > "$state/rfb-port"
x11vnc -norc -display "$DISPLAY" -auth "$XAUTHORITY" \
  -listen 127.0.0.1 -allow 127.0.0.1 -no6 -autoport 15900 \
  -passwdfile "$state/password" -forever -noxdamage -noxrecord \
  > "$state/rfb-port" &
vnc_pid=$!
children+=("$vnc_pid")

rfb_port=''
for ((attempt=0; attempt<200; attempt++)); do
  if ! kill -0 "$vnc_pid" 2>/dev/null; then echo 'x11vnc exited before opening its loopback port.' >&2; exit 1; fi
  if IFS= read -r line < "$state/rfb-port" && [[ $line =~ ^PORT=([0-9]+)$ ]]; then
    rfb_port=${BASH_REMATCH[1]}
    break
  fi
  sleep 0.1
done
[[ -n $rfb_port ]] || { echo 'Timed out waiting for the VNC listener.' >&2; exit 1; }

websockify --web /usr/share/novnc "127.0.0.1:$port" "127.0.0.1:$rfb_port" &
children+=("$!")
rviz2 -d /opt/g1-tools/g1stairs/camera/resources/image.rviz "$@" &
children+=("$!")

# Wait for a mapped RViz window and the noVNC page before announcing the viewer.
ready=false
for ((attempt=0; attempt<180; attempt++)); do
  for pid in "${children[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then echo 'The RViz viewer failed to start; see the process output above.' >&2; exit 1; fi
  done
  if xwininfo -root -tree | grep -Ei 'rviz.*[1-9][0-9]{2,}x[1-9][0-9]{2,}' >/dev/null &&
      curl --noproxy '*' -fsS --max-time 1 "http://127.0.0.1:$port/vnc.html" -o /dev/null 2>/dev/null; then
    ready=true
    break
  fi
  sleep 0.5
done
[[ $ready == true ]] || { echo 'Timed out waiting for the RViz window and noVNC page.' >&2; exit 1; }
if [[ $self_test == true ]]; then
  python3 - "$rfb_port" <<'PY'
import socket
import sys
with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=3) as connection:
    with connection.makefile("rb") as stream:
        assert stream.readline(13).startswith(b"RFB ")
PY
  echo 'RViz window, noVNC page and VNC handshake verified.'
  exit 0
fi

printf '\nPC2 브라우저에서 열 RViz2 주소: http://127.0.0.1:%s/vnc.html?autoconnect=true&resize=scale\n' "$port"
printf '이번 세션의 VNC 암호: %s\n종료: Ctrl+C\n' "$(<"$state/password")"
wait -n
