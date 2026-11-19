<!-- Author: Codex (IIC) -->
# 이전 컨테이너의 기록 가져오기

새 실험은 `jsj-g1-tools`의 `/workspace/runs`에 기록한다. 아래는 **이전 카메라 컨테이너에서 완료한 실험 하나**를 가져와 다시 계산할 때만 사용한다. Docker는 정지한 원본 컨테이너에서도 파일을 읽을 수 있다. PC2 호스트에 파일을 쓰지 않는다.

1. PC2에서 `docker ps -a`로 자신의 이전 컨테이너 이름을 확인한다. 이전 카메라의 기본 경로는 `/workspace/jsj-camera/runs`, 이전 분석 컨테이너는 `/workspace/jsj-footstep-workbench/runs`였다. 통합 컨테이너를 교체하면서 이름만 바꾼 경우 원본 경로는 `/workspace/runs`다.
2. 원본 녹화가 완료되었는지 확인한다. 아래 명령은 통합 컨테이너에 **새 임시 디렉터리**를 만들고 실험 폴더 하나를 통째로 복사한다. 이미 있는 실험과 이름이 같아도 덮어쓰지 않는다.
3. `camera replay` 성공 후 같은 경로로 계단 계산을 실행한다. 보정 파일이 촬영 당시 저장되지 않았다면 실측 보정 파일 경로를 `--calibration`으로 지정해야 한다.

```bash
read -rp '내 이전 카메라 컨테이너 이름: ' OLD_CAMERA
read -rp '이전 실험 이름: ' RUN_ID
OLD_ROOT=/workspace/jsj-camera/runs
(
  set -euo pipefail
  [[ $RUN_ID =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]]
  docker container inspect "$OLD_CAMERA" >/dev/null
  dest=$(docker exec jsj-g1-tools mktemp -d /workspace/imported-runs-XXXXXXXX)
  echo "복사 대상 $dest/$RUN_ID"
  docker cp "$OLD_CAMERA:$OLD_ROOT/$RUN_ID" - | docker cp - "jsj-g1-tools:$dest/"
  docker exec jsj-g1-tools g1 camera replay --runs-dir "$dest" --run "$RUN_ID"
  echo "계단 측정 시 --runs-dir $dest --run $RUN_ID 사용"
)
```

이미지를 다시 빌드했거나 USB 연결로 장치 경로가 바뀌면 시작 스크립트는 기존 컨테이너의 교체 여부를 알려준다. 교체가 필요한 경우 기록과 텔레옵을 먼저 종료하고, **자신의** 컨테이너를 `docker stop` 후 `docker rename`으로 보관한다. 시작 명령으로 새 컨테이너를 만든 다음, 보관본의 `/workspace/runs`에서 필요한 실험을 위와 같이 읽는다. 기존 계단 결과가 이미 들어 있는 실험은 `geometry/stairs.jsonl`에서 확인할 수 있다.
