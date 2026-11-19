<!-- Author: Codex (IIC) -->
# PC2에서 기존 컨테이너와 실험 기록 보관하기

운영 컨테이너를 다시 켜려면 G1 PC2 호스트에서 `docker start jsj-g1-tools`를 쓴다. 같은 컨테이너의 `/workspace/runs`가 그대로 열린다. 이미지나 USB 장치 구성을 바꿔 새 컨테이너가 필요한 경우에만 아래 교체 절차를 따른다.

## G1 호스트에서 기존 이미지와 컨테이너 보관

PC2의 SSH 터미널에서 본인의 컨테이너와 사용 중인 이미지 ID를 조회한다.

**G1 호스트**

```bash
docker ps -a --format '{{.Names}}  {{.Image}}  {{.Status}}'
docker image ls --no-trunc
docker container inspect jsj-g1-tools --format '{{.Config.Image}}  {{.Image}}  {{index .Config.Labels "org.iic.g1.role"}}'
```

대상이 본인의 `jsj-g1-tools`이고 역할이 `operator-tools`인지 확인한다. 아래 보관 이름 `jsj-g1-tools:saved-01`과 `jsj-g1-tools-saved-01` 중 이미 쓰는 이름이 있으면 새 번호를 정한다. `IMAGE_ID`를 방금 컨테이너 검사에서 출력한 두 번째 값(`sha256:…`)으로 바꾸면 현재 컨테이너가 실제로 사용하는 이미지에 보관 태그가 생긴다.

**G1 호스트**

```bash
docker image tag IMAGE_ID jsj-g1-tools:saved-01
```

먼저 새 이미지를 빌드한다. 빌드에 성공하면 이전 컨테이너에서 텔레옵을 종료하고 녹화·분석 결과가 모두 기록된 것을 확인한 후 기존 컨테이너 이름을 옮긴다. 쓰기 레이어에 있던 데이터도 이 보관본에 남는다.

**G1 호스트**

```bash
docker stop jsj-g1-tools
docker rename jsj-g1-tools jsj-g1-tools-saved-01
```

운영 절차에 따라 새 `jsj-g1-tools`를 생성한다. 보관본은 정지 상태로 두어도 기록을 복사할 수 있다. [통합 이미지 빌드 및 시작](../README.md#pc2)

## 완료된 실험 한 건 가져오기

아래 예시는 보관한 통합 컨테이너의 `/workspace/runs/stairs-01`을 사용한다. 이전 카메라 컨테이너라면 원본 컨테이너 이름과 경로를 `/workspace/jsj-camera/runs/실험이름`으로, 이전 분석 컨테이너라면 `/workspace/jsj-footstep-workbench/runs/실험이름`으로 바꾼다.

### 터미널 1 · G1 호스트에서 컨테이너 접속

```bash
docker exec -it jsj-g1-tools bash
```

### 터미널 1 · 컨테이너 내부에서 복사 대상 만들기

`RUN_ID`에는 보관할 실험의 디렉터리 이름을 넣는다. `mktemp`가 새 디렉터리를 만들면 출력된 전체 경로를 다음 단계에 사용한다. 마지막 검증에서도 같은 셸의 변수를 사용하므로 터미널을 열어 둔다.

**컨테이너 내부**

```bash
RUN_ID=stairs-01
IMPORT_ROOT=$(mktemp -d /workspace/imported-runs-XXXXXXXX) && printf '%s\n' "$IMPORT_ROOT"
```

### 터미널 2 · G1 호스트에서 컨테이너 사이로 복사

PC2에 새 SSH 터미널을 연다. 아래 명령의 `jsj-g1-tools-saved-01`, `stairs-01`, `/workspace/imported-runs-AbCd1234`를 각각 원본 컨테이너 이름, 실험 디렉터리 이름, 터미널 1이 출력한 경로로 바꾼다. 호스트에서 두 Docker 명령을 파이프로 연결하면 `docker cp`가 보관본에서 읽고 `docker exec`가 새 컨테이너 내부에서 `tar`를 실행한다. 대상에 같은 파일이 있으면 `tar`는 기존 파일을 보존하고 오류를 낸다. 복사 중 오류가 발생하면 터미널 1에서 새 대상 디렉터리를 만들어 다시 시도한다. [Docker 파일 복사](https://docs.docker.com/reference/cli/docker/container/cp/)

**G1 호스트**

```bash
docker cp jsj-g1-tools-saved-01:/workspace/runs/stairs-01 - | docker exec -i jsj-g1-tools tar --extract --file=- --keep-old-files --no-same-owner --directory=/workspace/imported-runs-AbCd1234
```

### 터미널 1 · 컨테이너 내부에서 복사본 확인

복사가 끝나면 열어 둔 컨테이너 셸에서 깊이 기록을 재생해 확인한다.

**컨테이너 내부**

```bash
g1 camera replay --runs-dir "$IMPORT_ROOT" --run "$RUN_ID"
```

이미 계산한 실험이면 복사본의 기존 결과를 읽는다.

**컨테이너 내부**

```bash
head -n 1 "$IMPORT_ROOT/$RUN_ID/geometry/stairs.jsonl"
```

계산 전인 실험은 재생 검사에 성공하고 촬영 당시 실측한 보정 파일이 준비됐을 때만 복사본에서 분석한다. 다음 명령은 실험의 `depth/calibration.json`을 사용한다. 보정 파일이 컨테이너 안의 다른 경로에 있으면 `--calibration 실제경로`를 추가한다.

**컨테이너 내부**

```bash
g1 stairs measure --runs-dir "$IMPORT_ROOT" --run "$RUN_ID"
```
