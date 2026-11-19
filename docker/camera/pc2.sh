#!/usr/bin/env bash
# Run on the G1-EDU development computer (PC2).
set -euo pipefail

base_image=g1-jsj:base
camera_image=g1-jsj:realsense
container=g1-jsj-realsense
repo='https://github.com/tokengeoji/g1-edu-loco.git#jsj'
command=${1:-help}
if (($#)); then shift; fi

die() { echo "$*" >&2; exit 1; }

build_images() {
  local context="$repo" parent=g1-jsj-ubuntu:20.04 checkout
  if [[ -f "${BASH_SOURCE[0]:-}" ]]; then
    checkout=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
    if [[ -f "$checkout/docker/base/Dockerfile" ]]; then context="$checkout"; fi
  fi
  if docker image inspect jsj-g1-base:ubuntu20.04-cpu >/dev/null 2>&1; then
    parent=jsj-g1-base:ubuntu20.04-cpu
  elif ! docker image inspect "$parent" >/dev/null 2>&1; then
    docker import --change 'CMD ["/bin/bash"]' \
      'https://partner-images.canonical.com/oci/focal/20250530.1/ubuntu-focal-oci-arm64-root.tar.gz' "$parent"
  fi
  docker run --rm --runtime=runc --network none "$parent" sh -ec \
    '. /etc/os-release; test "$ID:$VERSION_ID:$(dpkg --print-architecture)" = ubuntu:20.04:arm64'
  docker build --pull=false --platform linux/arm64 --build-arg BASE_IMAGE="$parent" \
    -f docker/base/Dockerfile -t "$base_image" "$context"
  docker build --pull=false --platform linux/arm64 \
    -f docker/camera/Dockerfile -t "$camera_image" "$context"
  docker run --rm --runtime=runc --network none "$camera_image" python3 -m g1stairs.camera discover --help
}

# Re-evaluate the caller's domain and NIC on each invocation.
domain=${G1_CAMERA_DOMAIN:-${ROS_DOMAIN_ID:-0}}
[[ $domain =~ ^[0-9]+$ ]] || die "ROS_DOMAIN_ID must be a number: $domain"
env_args=(-e "ROS_DOMAIN_ID=$domain")
if [[ -n ${G1_CAMERA_IFACE:-} ]]; then
  [[ $G1_CAMERA_IFACE =~ ^[[:alnum:]_.:-]+$ && -e /sys/class/net/$G1_CAMERA_IFACE ]] || die "Unknown NIC: $G1_CAMERA_IFACE"
  env_args+=(-e "CYCLONEDDS_URI=<CycloneDDS><Domain><General><Interfaces><NetworkInterface name=\"$G1_CAMERA_IFACE\"/></Interfaces></General></Domain></CycloneDDS>")
elif [[ -n ${CYCLONEDDS_URI:-} ]]; then
  env_args+=(-e "CYCLONEDDS_URI=$CYCLONEDDS_URI")
fi

start_camera() {
  local requested actual
  local -a device_args=()
  if [[ ${1:-} == --usb ]]; then usb_devices; fi
  requested=$(docker image inspect --format '{{.Id}}' "$camera_image")
  if docker container inspect "$container" >/dev/null 2>&1; then
    actual=$(docker inspect --format '{{.Image}}' "$container")
    [[ $actual == "$requested" ]] || die "$container uses an older image. Stop and rename that container to retain its recordings before starting the new one."
    if [[ ${1:-} == --usb && $(docker inspect --format '{{len .HostConfig.Devices}}' "$container") == 0 ]]; then
      die "USB was not mapped when this container was created. tty-usb works independently; for recording, stop and rename the container, then start --usb."
    fi
    if [[ $(docker inspect --format '{{.State.Running}}' "$container") != true ]]; then docker start "$container" >/dev/null; fi
  else
    docker run -d --runtime=runc --name "$container" --network host \
      --cap-drop ALL --security-opt no-new-privileges "${device_args[@]}" "$camera_image" sleep infinity >/dev/null
  fi
}

usb_devices() {
  local sys model bus num usbnode node target
  device_args=()
  for sys in /sys/bus/usb/devices/*; do
    [[ -r "$sys/product" && -r "$sys/idVendor" ]] || continue
    read -r model < "$sys/product"
    [[ $(<"$sys/idVendor") == 8086 ]] || continue
    [[ $(<"$sys/idProduct") == 0b3a || ${model,,} == *435i* ]] || continue
    read -r bus < "$sys/busnum"
    read -r num < "$sys/devnum"
    printf -v usbnode '/dev/bus/usb/%03d/%03d' "$((10#$bus))" "$((10#$num))"
    [[ -c $usbnode ]] || continue
    device_args+=(--device "$usbnode")
    target=$(readlink -f "$sys")
    for node in /sys/class/video4linux/video* /sys/class/media/media* /sys/class/hidraw/hidraw*; do
      [[ -e $node/device && -c /dev/${node##*/} ]] || continue
      if [[ $(readlink -f "$node/device") == "$target/"* ]]; then device_args+=(--device "/dev/${node##*/}"); fi
    done
  done
  ((${#device_args[@]})) || die "PC2에서 USB D435i를 찾지 못했습니다. discover 결과와 PC2의 USB 연결을 확인하세요."
  if [[ -d /run/udev ]]; then device_args+=(-v /run/udev:/run/udev:ro); fi
}

case "$command" in
  build) build_images ;;
  start) start_camera "$@"; echo "$container" ;;
  compressed-view)
    start_camera
    docker exec "${env_args[@]}" "$container" python3 -m g1stairs.camera.compressed_view "$@" ;;
  discover|tty-dds|record-ros)
    start_camera
    docker exec "${env_args[@]}" "$container" python3 -m g1stairs.camera "$command" "$@" ;;
  rviz)
    [[ -n ${DISPLAY:-} ]] || die 'DISPLAY가 없습니다. PC2의 그래픽 터미널에서 실행하거나 같은 ROS 도메인의 Linux PC에서 RViz2를 여세요.'
    authfile=${XAUTHORITY:-$HOME/.Xauthority}
    [[ -f "$authfile" && -r "$authfile" ]] || die '현재 X11 세션의 XAUTHORITY 파일 경로를 지정하세요.'
    docker run --rm --runtime=runc --network host --hostname "$(hostname)" "${env_args[@]}" \
      --user "$(id -u):$(id -g)" --cap-drop ALL --security-opt no-new-privileges \
      -e HOME=/tmp -e DISPLAY -e XAUTHORITY=/tmp/g1.Xauthority \
      -v "$authfile:/tmp/g1.Xauthority:ro" -v /tmp/.X11-unix:/tmp/.X11-unix:ro \
      "$camera_image" rviz2 -d /opt/g1/camera.rviz "$@" ;;
  tty-usb|probe-usb)
    usb_devices
    usb_command=tty-usb
    if [[ $command == probe-usb ]]; then usb_command=probe; fi
    docker run --rm --runtime=runc --network none --cap-drop ALL --security-opt no-new-privileges \
      "${device_args[@]}" "$camera_image" python3 -m g1stairs.camera "$usb_command" "$@" ;;
  *) echo "Usage: bash pc2.sh {build|start|discover|rviz|compressed-view|tty-dds|probe-usb|tty-usb|record-ros} [arguments]"
     [[ $command == help ]] ;;
esac
