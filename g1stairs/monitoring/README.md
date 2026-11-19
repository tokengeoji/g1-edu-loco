# G1 EDU 전신 모니터링

허리가 잠기지 않은 **29자유도 G1 EDU**의 상태를 PC2의 `jsj-monitor` 컨테이너가 수신하고, 외부 PC의 브라우저가 화면을 표시합니다. 최초 실행 시 [컨테이너 생성 및 코드 다운로드](../../README.md#monitoring)를 먼저 완료하세요.

## 실시간 GUI

**PC2에서** 아래 블록을 실행합니다. 표시되는 주소 중 외부 PC에서 PC2에 접속할 때 쓰는 LAN 주소를 입력하세요. 이미 서버가 떠 있으면 그 터미널에서 `Ctrl+C`로 종료한 뒤 실행하세요.

```bash
(
  set -e
  ip -brief -4 address show up
  read -rp '외부 PC에서 접속할 PC2의 LAN IPv4 주소 (/24 제외): ' pc2_ip
  [[ -n "$pc2_ip" ]] || exit 1
  docker exec -it -w /opt/g1-edu-loco jsj-monitor bash -ec \
    'exec python3 -m g1stairs.monitoring serve --bind "$1"' _ "$pc2_ip"
)
```

**외부 PC에서** 같은 연구실 네트워크에 연결한 뒤 브라우저로 PC2 터미널의 `Monitoring dashboard at` 뒤에 출력된 URL을 여세요. 주소 형식은 `http://<PC2의 LAN IP>:8765/`입니다. 외부 PC에는 Python이나 Unitree SDK를 설치할 필요가 없습니다. 페이지의 `waiting`은 웹 연결에 성공했고 아직 `rt/lowstate` 첫 샘플을 기다린다는 뜻입니다.

## 기록이 필요할 때

별도 PC2 터미널에서 컨테이너 셸을 여세요.

```bash
docker exec -it -w /opt/g1-edu-loco jsj-monitor bash
```

새 실험 이름을 지정하면 기본 10초 동안 상태를 저장합니다.

```bash
python3 -m g1stairs.monitoring record --run stairs-01 --runs-dir /workspace/jsj-monitor/runs
```

연결만 확인하려면 `python3 -m g1stairs.monitoring probe`로 메시지 한 건을 읽습니다. 기본 실행은 Unitree SDK2 예제의 DDS 도메인 0과 SDK의 인터페이스 선택을 사용합니다. 연결할 NIC가 정해져 있거나 기체가 다른 도메인을 쓰는 현장에서는 해당 명령에 `--nic` 또는 `--domain`을 추가합니다. [Unitree 공식 G1 예제](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/example/g1/low_level/g1_low_level_example.py)

## 읽는 값

`rt/lowstate`의 `LowState_`에서 몸체 모터 인덱스 0–28을 읽습니다. 팔·다리와 허리 세 축(12–14)을 포함합니다. 관절 위치 `q`, 속도 `dq`, 추정 토크 `tau_est`, 외함·권선 온도, IMU와 수신 시각을 기록합니다. 직렬 관절 표현(PR)과 병렬 구동기 표현(AB)은 수신 메시지의 `mode_pr`를 따라 표시합니다. [Unitree 공식 관절 인덱스](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/example/g1/low_level/g1_low_level_example.py) · [온도 배열 정의](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/g1/common/terminations.hpp)
