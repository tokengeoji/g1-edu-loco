#!/usr/bin/env bash
set -euo pipefail
if [[ ! -f /.dockerenv ]]; then
  printf '%s\n' '이 스크립트는 Docker 컨테이너 안에서 실행하세요.' >&2
  exit 2
fi

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
run_root="${G1_RUNS_DIR:-/workspace/jsj-footstep-workbench/runs}"
run_id="${G1_DEMO_RUN:-demo}"
if [[ ! "$run_id" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]]; then
  printf '%s\n' 'G1_DEMO_RUN에는 영문, 숫자, 하이픈, 밑줄만 사용할 수 있습니다.' >&2
  exit 2
fi

if [[ ! -f "$run_root/$run_id/state/manifest.json" ]]; then
  python3 -m g1stairs.monitoring fixture --runs-dir "$run_root" --run "$run_id"
fi
if [[ ! -f "$run_root/$run_id/depth/manifest.json" ]]; then
  python3 -m g1stairs.camera fixture --runs-dir "$run_root" --run "$run_id"
fi
if [[ ! -f "$run_root/$run_id/geometry/manifest.json" ]]; then
  python3 -m g1stairs.geometry measure --runs-dir "$run_root" --run "$run_id" --all-frames
fi

exec python3 -m g1stairs.camera replay --runs-dir "$run_root" --run "$run_id"
