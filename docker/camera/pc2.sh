#!/usr/bin/env bash
# PC2 dispatcher. All network and hardware inspection runs inside a container.
set -euo pipefail

base_image=g1-jsj:base
camera_image=g1-jsj:realsense
container=jsj-realsense
legacy_container=g1-jsj-realsense
repo='https://github.com/tokengeoji/g1-edu-loco.git#jsj'
command=${1:-help}
if (($#)); then shift; fi

die() { echo "$*" >&2; exit 1; }
run=(docker run --pull never --runtime=runc --cap-drop ALL --security-opt no-new-privileges:true)

build_images() {
  local parent=jsj-ubuntu:20.04
  if docker image inspect jsj-g1-base:ubuntu20.04-cpu >/dev/null 2>&1; then
    parent=jsj-g1-base:ubuntu20.04-cpu
  elif docker image inspect g1-jsj-ubuntu:20.04 >/dev/null 2>&1; then
    parent=g1-jsj-ubuntu:20.04
  elif ! docker image inspect "$parent" >/dev/null 2>&1; then
    docker import --change 'CMD ["/bin/bash"]' \
      'https://partner-images.canonical.com/oci/focal/20250530.1/ubuntu-focal-oci-arm64-root.tar.gz' "$parent"
  fi
  "${run[@]}" --rm --name "jsj-base-check-$BASHPID" --network none "$parent" sh -ec \
    '. /etc/os-release; test "$ID:$VERSION_ID:$(dpkg --print-architecture)" = ubuntu:20.04:arm64'
  docker build --pull=false --platform linux/arm64 --build-arg BASE_IMAGE="$parent" \
    -f docker/base/Dockerfile -t "$base_image" "$repo"
  if [[ $command == build-base ]]; then return; fi
  docker build --pull=false --platform linux/arm64 -f docker/camera/Dockerfile -t "$camera_image" "$repo"
}

# This internal command runs WITHIN the image. Enumerate device names from
# sysfs, which does not require exposing USB devices to this helper container.
usb_paths() {
  local sys model bus num target node
  for sys in /sys/bus/usb/devices/*; do
    [[ -r "$sys/product" && -r "$sys/idVendor" && -r "$sys/idProduct" ]] || continue
    read -r model < "$sys/product"
    [[ $(<"$sys/idVendor") == 8086 ]] || continue
    [[ $(<"$sys/idProduct") == 0b3a || ${model,,} == *435i* ]] || continue
    read -r bus < "$sys/busnum"
    read -r num < "$sys/devnum"
    printf '/dev/bus/usb/%03d/%03d\n' "$((10#$bus))" "$((10#$num))"
    target=$(readlink -f "$sys")
    for node in /sys/class/video4linux/video* /sys/class/media/media* /sys/class/hidraw/hidraw*; do
      [[ -e $node/device && -e $node/dev ]] || continue
      if [[ $(readlink -f "$node/device") == "$target/"* ]]; then printf '/dev/%s\n' "${node##*/}"; fi
    done
  done
}

if [[ $command == _usb-paths ]]; then usb_paths; exit; fi
if [[ $command == build || $command == build-base ]]; then build_images; exit; fi

domain=${G1_CAMERA_DOMAIN:-${ROS_DOMAIN_ID:-0}}
[[ $domain =~ ^[0-9]+$ ]] || die "ROS_DOMAIN_ID must be a number: $domain"
env_args=(-e "ROS_DOMAIN_ID=$domain")
if [[ -n ${G1_CAMERA_IFACE:-} ]]; then
  [[ $G1_CAMERA_IFACE =~ ^[[:alnum:]_.:-]+$ ]] || die "Invalid NIC: $G1_CAMERA_IFACE"
  env_args+=(-e "CYCLONEDDS_URI=<CycloneDDS><Domain><General><Interfaces><NetworkInterface name=\"$G1_CAMERA_IFACE\"/></Interfaces></General></Domain></CycloneDDS>")
elif [[ -n ${CYCLONEDDS_URI:-} ]]; then
  env_args+=(-e "CYCLONEDDS_URI=$CYCLONEDDS_URI")
fi

select_container() {
  if ! docker container inspect "$container" >/dev/null 2>&1 &&
      [[ $(docker inspect --type container --format '{{.Config.Image}} {{len .Mounts}} {{.HostConfig.Privileged}} {{.HostConfig.NetworkMode}}' "$legacy_container" 2>/dev/null || :) == "$camera_image 0 false host" ]]; then
    container=$legacy_container
  fi
}

device_args=()
usb_devices() {
  local paths path
  paths=$("${run[@]}" --rm --name "jsj-camera-usb-list-$BASHPID" --network none "$camera_image" bash /opt/g1/pc2.sh _usb-paths)
  [[ -n $paths ]] || die "컨테이너의 sysfs에서 D435i를 찾지 못했습니다. PC2의 USB 연결을 확인하세요."
  while IFS= read -r path; do
    [[ $path =~ ^/dev/(bus/usb/[0-9]{3}/[0-9]{3}|(video|media|hidraw)[0-9]+)$ ]] || die "Unexpected USB device: $path"
    device_args+=(--device "$path")
  done <<< "$paths"
}

start_camera() {
  local requested actual settings
  select_container
  requested=$(docker image inspect --format '{{.Id}}' "$camera_image")
  if docker container inspect "$container" >/dev/null 2>&1; then
    actual=$(docker inspect --format '{{.Image}}' "$container")
    [[ $actual == "$requested" ]] || die "$container uses another image revision. Preserve existing recordings and rename your old container before starting the new one."
    settings=$(docker inspect --format '{{len .Mounts}} {{.HostConfig.Privileged}} {{.HostConfig.NetworkMode}} {{.Config.Image}}' "$container")
    [[ $settings == "0 false host $camera_image" ]] || die "$container has incompatible settings. Check its owner and use a separate name for existing data."
    if [[ ${1:-} == --usb && $(docker inspect --format '{{len .HostConfig.Devices}}' "$container") == 0 ]]; then
      die "USB was not mapped at creation. Use tty-usb/probe-usb, or preserve your existing container by renaming it before start --usb."
    fi
    if [[ $(docker inspect --format '{{.State.Running}}' "$container") != true ]]; then docker start "$container" >/dev/null; fi
  else
    if [[ ${1:-} == --usb ]]; then usb_devices; fi
    "${run[@]}" -d --name "$container" --network host "${device_args[@]}" "$camera_image" sleep infinity >/dev/null
  fi
}

tty_args=()
if [[ -t 0 && -t 1 ]]; then tty_args=(-it); fi

case "$command" in
  name) select_container; printf '%s\n' "$container" ;;
  interfaces) "${run[@]}" --rm --name "jsj-camera-nic-$BASHPID" --network host "$camera_image" ip -br -4 addr ;;
  start) start_camera "$@"; echo "$container" ;;
  discover|tty-dds|compressed-view|rviz)
    if [[ -n ${G1_CAMERA_IFACE:-} ]]; then
      "${run[@]}" --rm --name "jsj-camera-nic-$BASHPID" --network host "$camera_image" \
        test -d "/sys/class/net/$G1_CAMERA_IFACE" || die "Unknown NIC: $G1_CAMERA_IFACE"
    fi
    if [[ $command == compressed-view ]]; then
      program=(python3 -m g1stairs.camera.compressed_view)
    elif [[ $command == rviz ]]; then
      run+=(--init --log-driver none)
      env_args+=(-e "G1_RVIZ_PORT=${G1_RVIZ_PORT:-6080}")
      program=(xvfb-run -a -s "-screen 0 1280x800x24 -nolisten tcp +extension GLX" bash /opt/g1/rviz-web.sh)
    else
      program=(python3 -m g1stairs.camera "$command")
    fi
    exec "${run[@]}" --rm --name "jsj-camera-$command-$BASHPID" --network host \
      "${tty_args[@]}" "${env_args[@]}" "$camera_image" "${program[@]}" "$@" ;;
  record-ros)
    start_camera
    if [[ -n ${G1_CAMERA_IFACE:-} ]]; then
      docker exec "$container" test -d "/sys/class/net/$G1_CAMERA_IFACE" || die "Unknown NIC: $G1_CAMERA_IFACE"
    fi
    exec docker exec "${tty_args[@]}" "${env_args[@]}" "$container" python3 -m g1stairs.camera "$command" "$@" ;;
  tty-usb|probe-usb)
    usb_devices
    usb_command=tty-usb
    if [[ $command == probe-usb ]]; then usb_command=probe; fi
    exec "${run[@]}" --rm --name "jsj-camera-$command-$BASHPID" --network none "${device_args[@]}" "$camera_image" python3 -m g1stairs.camera "$usb_command" "$@" ;;
  *) echo "Usage: g1cam {interfaces|start [--usb]|name|discover|rviz|compressed-view|tty-dds|probe-usb|tty-usb|record-ros} [arguments]"
     [[ $command == help ]] ;;
esac
