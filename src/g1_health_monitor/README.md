# 🌡️ G1 Health Monitor

배터리 상태와 모터 온도를 1초마다 터미널에 보여주는 프로그램.
**읽기 전용**이라 로봇에 명령을 보내지 않는다. 로봇이 서 있든 걷고 있든 언제 켜도 안전하다.

---

## 1. G1 호스트에서 컨테이너 접속

실행 파일은 통합 이미지 빌드 때 설치된다. 첫 설치는 [G1에서 베이스·통합 이미지 빌드와 컨테이너 생성](../../README.md#pc2)을 따른다. 생성한 `jsj-g1-tools`가 실행 중이면 아래 명령으로 들어간다.

**G1 호스트**

```bash
docker exec -it jsj-g1-tools bash
```

## 2. 컨테이너 내부에서 온도 측정

먼저 로봇용 유선 인터페이스 이름을 확인한다. 아래 `eth0`는 현장에서 수신을 확인한 예시다. 모니터는 `Ctrl+C`로 종료한다.

**컨테이너 내부**

```bash
g1 interfaces
g1 health eth0
```

**컨테이너 내부 · 모터 경보 기준을 바꾸는 경우**. 다음 예시는 경고·위험을 65·80°C, 저온 경고·위험을 10·5°C로 지정한다.

```bash
g1 health eth0 65 80 10 5
```

온도 측정에는 Unitree SDK2 기반의 [연구실 원본 C++ 코드](https://github.com/duckptr/g1-edu-tools/tree/0f761000a0b78d9437f9d7166f41725a5924e441/g1_health_monitor)를 사용한다.

- 인자 순서: `warn danger cold_warn cold_danger`
- 반드시 `cold_danger < cold_warn < warn < danger` 순서여야 한다. 아니면 사용법을 출력하고 종료한다.

로봇이 연결되지 않았을 때 화면:

```text
=== G1 health monitor (iface: lo, hot: 70/80C, cold: 10/5C) ===

[Battery]
  no BMS message on 'rt/lf/bmsstate' (check topic name)

[Motors]
  no message on 'rt/lowstate' (check network interface / robot power)
```

---

## 3. 온도 기준과 근거

| 대상 | 저온 위험 | 저온 경고 | 경고 | 위험 |
| --- | --- | --- | --- | --- |
| 모터 | 5 이하 | 10 이하 | 70 이상 | 80 이상 |
| 배터리 | 5 이하 | 10 이하 | 45 이상 | 50 이상 |

- **모터 과열**: 다른 G1 사용자 보고에 따르면 모터 90도에서 로봇 자체 고온 경고가 뜬다. 그보다 10도 낮은 80도를 위험, 70도를 경고로 둔다. ([GR00T-WholeBodyControl 이슈 #174](https://github.com/NVlabs/GR00T-WholeBodyControl/issues/174))
- **저온**: G1 사용 설명서의 사용 환경이 0~40도다. 범위를 벗어나기 전에 알 수 있게 5도를 위험, 10도를 경고로 둔다. ([G1 User Manual V1.0](https://fcc.report/FCC-ID/2A5PE-YUSHU008/8087916.pdf))
- **배터리**: 배터리 설명서에 배터리 온도 0도 미만 또는 50도 초과에서는 충전이 비정상이 된다고 되어 있다. 방전 중 한계는 설명서에서 찾지 못해 충전 범위를 대신 쓴다. ([G1 Battery and Charger User Manual](https://manuals.plus/unitree-robotics/g1-humanoid-robot-manual-2))
- 모터 기준 4개는 실행 인자로 바꾼다. 배터리 기준은 코드의 `kBatteryLimits`를 고친다.

DANGER, COLD-DANGER가 뜨면 터미널 경고음(`\a`)이 울린다.

---

## 4. 코드 읽는 법

[`g1_health_monitor.cpp`](g1_health_monitor.cpp)는 위에서부터 이 순서로 되어 있다.

### ① 토픽 이름

```cpp
const std::string kLowStateTopic = "rt/lowstate";      // 모터 상태 (SDK 예제에서 확인됨)
const std::string kBmsStateTopic = "rt/lf/bmsstate";   // 배터리 (확인 필요!)
```

unitree_sdk2는 DDS로 통신하고, 로봇은 상태를 토픽으로 계속 내보낸다. 이 프로그램은 두 토픽을 **구독**만 한다.

### ② 온도 기준 `Limits`

```cpp
struct Limits { int warn = 70; int danger = 80; int cold_warn = 10; int cold_danger = 5; };
const Limits kBatteryLimits = {45, 50, 10, 5};
```

모터용 기본값은 실행 인자로 덮어쓰고, 배터리용은 코드에 고정해 둔다.

### ③ 콜백과 `Shared`

```cpp
void LowStateHandler(const void* message) {
  std::lock_guard<std::mutex> lock(g_shared.mtx);
  g_shared.low = *static_cast<const LowState_*>(message);
  ...
}
```

메시지가 오면 SDK가 **별도 스레드**에서 콜백을 부른다. 메인 루프도 같은 데이터를 읽기 때문에 `mutex`로 잠그고 복사만 한다. 받은 시각(`low_time`)도 같이 저장해서 "마지막 메시지가 몇 초 전인지"로 연결 끊김을 판단한다.

### ④ `Level()`: 상태 판정

```cpp
if (hot >= lim.danger) return "DANGER";
if (cold <= lim.cold_danger) return "COLD-DANGER";
if (hot >= lim.warn) return "WARN";
if (cold <= lim.cold_warn) return "COLD-WARN";
return "ok";
```

위험 → 경고 순서로 검사해서 더 심각한 쪽이 먼저 나오게 했다. 모터마다 온도가 두 개(`temp0`, `temp1`)라서 과열은 큰 값, 저온은 작은 값으로 본다.

### ⑤ 메인 루프

1. 인자 읽기 → 기준 순서 검사
2. `ChannelFactory::Instance()->Init(0, iface)`: 해당 인터페이스로 DDS 시작
3. `ChannelSubscriber` 두 개 생성 → 구독 시작
4. 1초마다: 공유 데이터 복사 → 화면 지우기(`\033[2J\033[H`) → 배터리 출력 → 모터 29개 표 출력 → 가장 뜨거운/차가운 관절, 평균 전압 출력

---

## 5. 아직 확인 안 된 것

- [ ] **배터리 토픽 이름**: `rt/lf/bmsstate`는 SDK 예제에 없는 이름. 배터리 값이 안 나오면 실제 토픽 이름을 찾아 `kBmsStateTopic`을 고친다.
- [ ] **단위**: 배터리 전류·전압·온도는 raw 값 그대로 출력한다. 앱에 보이는 값과 비교해 단위를 확인한다.
- [ ] **모터 온도 2개**: `temp0`, `temp1`이 각각 어느 부위인지 모름. 한쪽이 항상 0이면 COLD-DANGER가 계속 뜨므로, 그때는 쓰는 쪽만 보도록 고친다. 배터리 온도 배열도 같은 문제가 있을 수 있다.
- [ ] **저온 기준값**: 5/10도는 임시값. 실제로 넘어진 온도를 알게 되면 맞춘다.

## 6. 나중에 추가할 것

- [ ] CSV로 저장해서 실험별 발열 추이 보기
- [ ] GUI(그래프) 버전
- [ ] 보드 온도와 팬 상태(`MainBoardState`) 추가
