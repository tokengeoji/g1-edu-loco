#!/usr/bin/env bash
# Author: Codex (IIC)
# Paste this block into a Bash session on PC2. It writes no host files.
g1start() (
  set -euo pipefail
  shopt -s nullglob
  local name=jsj-g1-tools image=jsj-g1-tools:foxy
  local sys bus num path target node spec security option nnp=false actual_devices wanted_devices image_id
  local -a devices=() flags=()
  image_id=$(docker image inspect --format '{{.Id}}' "$image")

  # Only add actual device nodes belonging to an Intel D435i. A network-only
  # setup remains usable when PC2 has no matching local USB device.
  for sys in /sys/bus/usb/devices/*; do
    [[ -r $sys/idVendor && -r $sys/idProduct && -r $sys/product ]] || continue
    [[ $(<"$sys/idVendor") == 8086 ]] || continue
    [[ $(<"$sys/idProduct") == 0b3a || $(<"$sys/product") == *D435I* || $(<"$sys/product") == *D435i* ]] || continue
    read -r bus < "$sys/busnum"
    read -r num < "$sys/devnum"
    printf -v path '/dev/bus/usb/%03d/%03d' "$((10#$bus))" "$((10#$num))"
    [[ -c $path ]] || continue
    devices+=("$path")
    target=$(readlink -f "$sys")
    for node in /sys/class/video4linux/video* /sys/class/media/media* /sys/class/hidraw/hidraw*; do
      path=/dev/${node##*/}
      if [[ -c $path && $(readlink -f "$node/device") == "$target/"* ]]; then devices+=("$path"); fi
    done
  done
  for path in "${devices[@]}"; do flags+=(--device "$path:$path:rw"); done

  if ! docker container inspect "$name" >/dev/null 2>&1; then
    docker create --name "$name" --pull never --init --runtime=runc --network host \
      --cap-drop ALL --security-opt no-new-privileges:true --log-driver none \
      "${flags[@]}" "$image" >/dev/null || docker container inspect "$name" >/dev/null
  fi

  spec=$(docker container inspect -f '{{.Image}} {{.Config.Image}} {{index .Config.Labels "org.iic.g1.role"}} {{.HostConfig.Runtime}} {{.HostConfig.NetworkMode}} {{.HostConfig.Privileged}} {{.HostConfig.Init}} {{if or .Mounts (index .HostConfig "Tmpfs") (index .HostConfig "CapAdd") (index .HostConfig "DeviceRequests")}}extra{{else}}none{{end}} {{json .HostConfig.CapDrop}} {{json .Config.Cmd}}' "$name")
  security=$(docker container inspect -f '{{range .HostConfig.SecurityOpt}}{{println .}}{{end}}' "$name")
  while IFS= read -r option; do
    case "$option" in
      no-new-privileges|no-new-privileges:true|no-new-privileges=true) nnp=true ;;
      label=disable|label:disable|apparmor=docker-default|apparmor:docker-default) ;;
      *) echo "예상하지 않은 기존 컨테이너 보안 옵션: $option" >&2; return 1 ;;
    esac
  done <<< "$security"
  if [[ $nnp != true || $spec != "$image_id $image operator-tools runc host false true none [\"ALL\"] [\"sleep\",\"infinity\"]" ]]; then
    echo '기존 jsj-g1-tools의 이미지 또는 실행 설정이 다릅니다. 기존 데이터와 컨테이너를 보존했습니다.' >&2
    return 1
  fi
  actual_devices=$(docker container inspect -f '{{range .HostConfig.Devices}}{{println (printf "%s:%s:%s" .PathOnHost .PathInContainer .CgroupPermissions)}}{{end}}' "$name" | sed '/^$/d' | LC_ALL=C sort)
  wanted_devices=$(for path in "${devices[@]}"; do printf '%s:%s:rw\n' "$path" "$path"; done | LC_ALL=C sort)
  if [[ $actual_devices != "$wanted_devices" ]]; then
    echo 'D435i 장치 경로가 생성 시점과 다릅니다. 기존 기록을 보존한 뒤 안내에 따라 컨테이너를 교체하세요.' >&2
    return 1
  fi
  if [[ $(docker container inspect -f '{{.State.Running}}' "$name") != true ]]; then docker start "$name" >/dev/null; fi
  printf '%s 실행 중 (D435i 장치 노드 %s개). docker exec -it %s g1 --help\n' "$name" "${#devices[@]}" "$name"
)
g1start
