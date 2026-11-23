<!-- Author: Codex (IIC) -->
# FSM 802 관절 로그 재계산

2026년 11월 23일 두 실기체 시험의 속도 요청을 시간 구간으로 나누고 29개 관절의 실측값과 목표값을 CSV로 내보낸다. Python 3 표준 라이브러리와 Notion 원본 ZIP만 사용한다. 당시 순수 전후진 속도는 ±0.15 m/s였다. `key_equivalent`는 기록에 남은 속도 벡터와 당시 기본 키를 대응시킨 표기다. 실제 누른 키는 DDS 요청에서 복원할 수 없다. [시험별 결과와 구간 번호](../../teleop-802-evidence.md)

## 한 시험 재계산하기

**컨테이너 내부 · 이 문서가 있는 디렉터리에서 실행.** 첫 줄을 내려받은 원본 ZIP 경로로 바꾼다. 새 임시 폴더에 입력 파일 네 개만 꺼내면 원본 ZIP과 그 안의 기존 결과를 보존할 수 있다.

```bash
archive=/path/to/teleop-802-joint-logs.zip
trial_dir=$(mktemp -d)
unzip -q "$archive" capture.json capture-end.json motors.jsonl rpc.jsonl -d "$trial_dir"
python3 export_teleop_trial.py "$trial_dir"
```

| 생성 파일 | 분석에 쓸 값 |
| --- | --- |
| `movement-windows.json` | 구간별 7105 요청 ID, 속도 벡터와 유효시간, 대응한 응답, 표본 수 |
| `joint-feedback.csv` | 수신 시각·구간·관절별 실측 위치, 속도, 추정 토크 |
| `joint-targets.csv` | 수신 시각·구간·관절별 목표 위치, 속도, 토크, 게인 |
| `joint-window-summary.csv` | 구간별·관절별 실측 및 목표 각도의 범위, 순변화, 최대 실측 속도 |

명령 구간은 첫 요청부터 같은 벡터의 마지막 요청 유효시간까지이며, 먼저 관측된 정지나 방향 변경에서 끝난다. 대응 응답이 없는 요청, 샘플이 없는 구간, 물리적 정지 시각을 구분해서 읽는다. 오도메트리와 FSM을 합친 **2차 시험의 `motion-window-summary.csv`는 Notion 원본 ZIP에서 읽는다.** 이 내보내기의 입력에는 오도메트리·FSM 파일이 없다.

## 원본과 대조한 결과

| 실험 | 관절 실측 / 목표 표본 | 재계산 결과 |
| --- | --- | --- |
| 1차 · 01:39 UTC | 3,247 / 3,240 | 12구간. 원본 CSV의 실측 94,163행, 목표 93,960행, 관절 요약 348행에서 공통 수치 열이 일치했다(허용 절대·상대 오차 각각 10⁻⁷). 새 CSV에는 모터 제어 모드 등의 열이 추가되고 키 별칭은 `i\|I`, `,\|<`로 표시된다. 1차 ZIP의 JSON은 이전 집계 형식이다. |
| 2차 · 02:26 UTC | 3,056 / 3,053 | 11구간. 위 네 파일이 원본 ZIP에 들어 있는 결과와 바이트 단위로 일치했다. |

**컨테이너 내부 · 합성 테스트.** 중복·만료·교체·정지 요청, 결측 표본, 비어 있는 시험, 기존 파일 덮어쓰기 방지를 검사한다.

```bash
python3 test_export_teleop_trial_fixture.py
```
