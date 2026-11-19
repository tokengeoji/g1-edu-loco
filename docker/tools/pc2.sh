#!/usr/bin/env bash
# Author: Codex (IIC)
set -euo pipefail
shopt -s nullglob

print_create_command() {
  local sysfs=$1 usb camera node parent base path bus number
  local -a devices=()

  # The unprivileged helper sees the kernel's sysfs inventory. Camera device
  # nodes themselves exist on PC2 and are passed only to the operator container.
  for usb in "$sysfs"/bus/usb/devices/*; do
    [[ -r $usb/idVendor && -r $usb/idProduct ]] || continue
    [[ $(<"$usb/idVendor") == 8086 && $(<"$usb/idProduct") == 0b3a ]] || continue
    [[ -r $usb/busnum && -r $usb/devnum ]] || continue
    bus=$(<"$usb/busnum")
    number=$(<"$usb/devnum")
    [[ $bus =~ ^[0-9]{1,3}$ && $number =~ ^[0-9]{1,3}$ ]] || continue
    camera=$(readlink -e -- "$usb") || continue
    printf -v path '/dev/bus/usb/%03d/%03d' "$((10#$bus))" "$((10#$number))"
    devices+=(--device "$path:$path:rw")

    for node in "$sysfs"/class/video4linux/video* "$sysfs"/class/media/media* "$sysfs"/class/hidraw/hidraw*; do
      base=${node##*/}
      [[ $base =~ ^(video|media|hidraw)[0-9]+$ && -r $node/dev ]] || continue
      parent=$(readlink -e -- "$node/device") || continue
      [[ $parent == "$camera" || $parent == "$camera/"* ]] || continue
      path=/dev/$base
      devices+=(--device "$path:$path:rw")
    done
  done

  if ((${#devices[@]} == 0)); then
    echo 'PC2에서 USB D435i(8086:0b3a)를 찾지 못했습니다. 네트워크 전용 명령을 출력합니다.' >&2
  fi
  # A name collision must stop the command before it can start another container.
  printf '%s\n' '아래 Docker 명령을 G1 PC2 호스트에서 실행하세요.' >&2
  printf '%q ' docker create --name jsj-g1-tools --pull never --init --runtime=runc --network host \
    --cap-drop ALL --security-opt no-new-privileges:true --log-driver none \
    "${devices[@]}" g1-jsj:base
  printf '&& docker start jsj-g1-tools\n'
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  print_create_command /sys
fi
