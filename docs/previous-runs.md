<!-- Author: Codex (IIC) -->
# PC2에서 기존 컨테이너와 실험 기록 보관하기

현재 운영 이미지는 `g1-jsj:base`, 컨테이너 이름은 `jsj-g1-tools`다. 이전 설치에는 같은 `g1-jsj:base` 태그의 SDK 전용 이미지와 운영 이미지 `jsj-g1-tools:foxy`가 있을 수 있다. 기체에서 기록한 `/workspace/runs`는 해당 컨테이너의 쓰기 레이어에 남는다.

## G1 호스트에서 기존 이미지와 컨테이너 보관

PC2의 SSH 터미널에서 기존 컨테이너와 이미지 태그를 확인한다.

**G1 호스트**

```bash
docker ps -a --format '{{.Names}}  {{.Image}}  {{.Status}}'
docker image ls --no-trunc
```

처음 설치하고 같은 이름의 이미지·컨테이너가 없으면 [단일 이미지 빌드와 컨테이너 생성](../README.md#pc2)으로 이동한다. 목록에 있는 이름에 대해서만 다음 명령을 실행한다. 컨테이너 검사 결과에는 생성할 때 지정한 태그, 실제로 사용 중인 이미지 ID, 역할, 실행 상태가 차례로 나온다.

**G1 호스트**

```bash
docker image inspect g1-jsj:base --format '{{.Id}}  {{with .Config.Labels}}{{index . "org.iic.g1.role"}}{{end}}'
docker container inspect jsj-g1-tools --format '{{.Config.Image}}  {{.Image}}  {{with .Config.Labels}}{{index . "org.iic.g1.role"}}{{end}}  {{.State.Status}}'
```

컨테이너가 참조하지 않는 구형 SDK 이미지를 그대로 다시 쓸 계획이라면, 빌드 전에 해당 이미지 ID의 별도 보관 여부를 결정한다. 재빌드에 성공하면 `g1-jsj:base` 태그는 새 ID를 가리킨다.

| 확인 결과 | 다음 동작 |
| --- | --- |
| 본인의 `jsj-g1-tools`가 역할 `operator-tools`이고 원하는 이미지 ID·USB 구성과 일치 | 실행 중이면 그대로 접속한다. 정지 상태라면 G1 호스트에서 `docker start jsj-g1-tools`를 실행한다. 기존 기록을 같은 경로에서 사용할 수 있다. |
| 본인의 `g1-jsj:base`를 새 버전으로 갱신 | [단일 빌드 명령](../docker/base/README.md)을 실행한다. 이전 SDK 전용 이미지는 역할이 비어 있을 수 있다. |
| 본인의 운영 컨테이너를 교체 | 생성 당시 태그는 `jsj-g1-tools:foxy` 또는 `g1-jsj:base`일 수 있다. 역할 `operator-tools`와 실제 이미지 ID를 확인하고 아래 순서로 보관한다. |
| 소유자가 불명확하거나 컨테이너 역할이 예상과 다름 | 기존 이름과 데이터를 보존하고 소유자·구성을 확인한다. |

새 `g1-jsj:base`의 이미지 ID와 `operator-tools` 역할을 확인한다. 이전 `jsj-g1-tools:foxy` 태그는 기존 이미지에 남고, 컨테이너는 정지하거나 이름을 바꿔도 생성 당시의 이미지 ID를 계속 참조한다.

기존 컨테이너에 새 이미지 또는 USB 구성을 적용할 때만 본인의 텔레옵과 녹화를 종료하고 결과가 모두 기록됐는지 확인한다. 아래 보관용 이름이 이미 사용 중이면 사용하지 않는 새 번호를 정한다. 이미 정지 상태라면 둘째 줄만 실행한다.

**G1 호스트**

```bash
docker stop jsj-g1-tools
docker rename jsj-g1-tools jsj-g1-tools-saved-01
```

새 `g1-jsj:base`에서 같은 이름의 `jsj-g1-tools`를 생성·시작한다. 위의 컨테이너 검사 명령으로 실제 이미지 ID가 새 빌드의 ID와 일치하는지 확인한다. 이미 보관한 `jsj-g1-tools-saved-01`에는 기존 쓰기 레이어와 실험 기록이 남아 있어 정지 상태에서도 복사할 수 있다. [컨테이너 생성과 시작](../README.md#pc2)

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
