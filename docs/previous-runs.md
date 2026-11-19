<!-- Author: Codex (IIC) -->
# PC2에서 기존 컨테이너와 실험 기록 보관하기

운영 컨테이너를 단순히 다시 켜려면 `docker start jsj-g1-tools`를 쓴다. 같은 컨테이너의 `/workspace/runs`가 그대로 열린다. 이미지나 USB 장치 구성을 바꿔 새 컨테이너가 필요한 경우에만 아래 교체 절차를 따른다.

## 기존 이미지와 컨테이너를 보관하고 교체

```bash
docker ps -a --format '{{.Names}}  {{.Image}}  {{.Status}}'
docker image ls --no-trunc
docker container inspect jsj-g1-tools --format '{{.Config.Image}}  {{.Image}}  {{index .Config.Labels "org.iic.g1.role"}}'
```

대상이 본인의 `jsj-g1-tools`이고 역할이 `operator-tools`인지 확인한다. 아래 보관 이름 `jsj-g1-tools:saved-01`과 `jsj-g1-tools-saved-01` 중 이미 쓰는 이름이 있으면 새 번호를 정한다. `IMAGE_ID`를 방금 컨테이너 검사에서 출력한 두 번째 값(`sha256:…`)으로 바꾸면 현재 컨테이너가 실제로 사용하는 이미지에 보관 태그가 생긴다.

```bash
docker image tag IMAGE_ID jsj-g1-tools:saved-01
```

먼저 새 이미지를 빌드한다. 빌드에 성공하면 이전 컨테이너에서 텔레옵을 종료하고 녹화·분석 결과가 모두 기록된 것을 확인한 후 기존 컨테이너 이름을 옮긴다. 쓰기 레이어에 있던 데이터도 이 보관본에 남는다.

```bash
docker stop jsj-g1-tools
docker rename jsj-g1-tools jsj-g1-tools-saved-01
```

운영 절차에 따라 새 `jsj-g1-tools`를 생성한다. 보관본은 정지 상태로 두어도 기록을 복사할 수 있다. [통합 이미지 빌드 및 시작](../README.md#pc2)

## 완료된 실험 한 건 가져오기

아래 예시는 보관한 통합 컨테이너의 `/workspace/runs/stairs-01`을 사용한다. 이전 카메라 컨테이너라면 원본의 컨테이너 이름과 경로를 `/workspace/jsj-camera/runs/실험이름`으로, 이전 분석 컨테이너라면 `/workspace/jsj-footstep-workbench/runs/실험이름`으로 바꾼다.

```bash
docker exec jsj-g1-tools mktemp -d /workspace/imported-runs-XXXXXXXX
```

아래의 `/workspace/imported-runs-AbCd1234`는 예시다. 방금 출력된 새 디렉터리로 바꾸고 `stairs-01`을 실제 실험 이름으로 바꾼다. 두 Docker 명령 사이의 파이프는 보관본의 실험 디렉터리를 새 컨테이너로 스트리밍한다. 대상 안에 같은 파일이 있으면 tar가 오류를 내고 기존 파일을 보존한다. PC2 호스트에 중간 파일이나 마운트를 만들지 않는다. 복사 오류가 나오면 새 임시 디렉터리를 만들어 다시 시도한다. [Docker 파일 복사](https://docs.docker.com/reference/cli/docker/container/cp/)

```bash
docker cp jsj-g1-tools-saved-01:/workspace/runs/stairs-01 - | docker exec -i jsj-g1-tools tar --extract --file=- --keep-old-files --no-same-owner --directory=/workspace/imported-runs-AbCd1234
docker exec jsj-g1-tools g1 camera replay --runs-dir /workspace/imported-runs-AbCd1234 --run stairs-01
```

이미 계산한 실험이면 다음 명령으로 복사본의 기존 결과를 읽는다.

```bash
docker exec jsj-g1-tools head -n 1 /workspace/imported-runs-AbCd1234/stairs-01/geometry/stairs.jsonl
```

계산 전인 실험은 재생 검사에 성공하고 촬영 당시 실측한 보정 파일이 준비됐을 때만 복사본에서 분석한다. 다음 명령은 실험의 `depth/calibration.json`을 사용한다. 보정 파일이 컨테이너 안의 다른 경로에 있으면 `--calibration 실제경로`를 추가한다.

```bash
docker exec jsj-g1-tools g1 stairs measure --runs-dir /workspace/imported-runs-AbCd1234 --run stairs-01
```
