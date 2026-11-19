# G1 EDU 전신 모니터링

허리가 잠기지 않은 **29자유도 G1 EDU** 한 대를 대상으로 합니다. 이미 실행 중인 `jsj-monitor`에 들어갑니다. [컨테이너 최초 실행 및 Git 갱신](../../README.md)

```bash
docker exec -it -w /opt/g1-edu-loco jsj-monitor bash
```

## 실시간 GUI

컨테이너 안에서 다음 한 줄을 실행합니다.

```bash
python3 -m g1stairs.monitoring serve
```

기본 주소는 `http://127.0.0.1:8765`입니다. 개발 PC에서 보려면 별도 터미널에서 기존 PC2 SSH 접속 대상에 `ssh -N -L 8765:127.0.0.1:8765 "$G1_PC2_SSH_TARGET"`로 포트를 연결한 뒤 브라우저에서 같은 주소를 엽니다.

## 기록이 필요할 때

새 실험 이름을 지정하면 기본 10초 동안 상태를 저장합니다.

```bash
python3 -m g1stairs.monitoring record --run stairs-01 --runs-dir /workspace/jsj-monitor/runs
```

연결만 확인하려면 `python3 -m g1stairs.monitoring probe`로 메시지 한 건을 읽습니다. 기본 실행은 Unitree SDK2 예제의 DDS 도메인 0과 SDK의 인터페이스 선택을 사용합니다. 연결할 NIC가 정해져 있거나 기체가 다른 도메인을 쓰는 현장에서는 해당 명령에 `--nic` 또는 `--domain`을 추가합니다. [Unitree 공식 G1 예제](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/example/g1/low_level/g1_low_level_example.py)

## 읽는 값

`rt/lowstate`의 `LowState_`에서 몸체 모터 인덱스 0–28을 읽습니다. 팔·다리와 허리 세 축(12–14)을 포함합니다. 관절 위치 `q`, 속도 `dq`, 추정 토크 `tau_est`, 외함·권선 온도, IMU와 수신 시각을 기록합니다. 직렬 관절 표현(PR)과 병렬 구동기 표현(AB)은 수신 메시지의 `mode_pr`를 따라 표시합니다. [Unitree 공식 관절 인덱스](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/example/g1/low_level/g1_low_level_example.py) · [온도 배열 정의](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/g1/common/terminations.hpp)
