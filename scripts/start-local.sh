#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

export LOCAL_UID="$(id -u)"
export LOCAL_GID="$(id -g)"
export G1_DEMO_RUN="${G1_DEMO_RUN:-demo}"
if [[ ! "$G1_DEMO_RUN" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]]; then
  printf '%s\n' 'G1_DEMO_RUN에는 영문, 숫자, 하이픈, 밑줄만 사용할 수 있습니다.' >&2
  exit 2
fi

docker info --format '{{.ServerVersion}}' >/dev/null
docker compose version >/dev/null
mkdir -p runs
docker compose build monitoring

if [[ ! -f "runs/$G1_DEMO_RUN/state/manifest.json" ]]; then
  docker compose run -T --rm --no-deps monitoring \
    python -m g1stairs.monitoring fixture --runs-dir /runs --run "$G1_DEMO_RUN"
fi
docker compose up --detach --no-build

if [[ ! -f "runs/$G1_DEMO_RUN/depth/manifest.json" ]]; then
  docker compose exec -T camera \
    python -m g1stairs.camera fixture --runs-dir /runs --run "$G1_DEMO_RUN"
fi
if [[ ! -f "runs/$G1_DEMO_RUN/geometry/manifest.json" ]]; then
  docker compose exec -T geometry \
    python -m g1stairs.geometry measure --runs-dir /runs --run "$G1_DEMO_RUN" --all-frames
fi

docker compose ps
printf '모니터링 http://127.0.0.1:%s/\n합성 실험 runs/%s/\n' "${MONITOR_PORT:-8765}" "$G1_DEMO_RUN"
