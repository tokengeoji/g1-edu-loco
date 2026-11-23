// Author: 김명준 (Kim Myeongjun), IIC 연구실
// 용도: Unitree G1-EDU 배터리 상태 / 모터 발열·저온 모니터 (읽기 전용, 로봇에 명령을 보내지 않음)
// 사용: ./g1_health_monitor <network_interface> [warn] [danger] [cold_warn] [cold_danger]
//   예: ./g1_health_monitor eth0 70 80 10 5
//   조건: cold_danger < cold_warn < warn < danger

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <string>
#include <thread>

#include <unitree/idl/hg/BmsState_.hpp>
#include <unitree/idl/hg/LowState_.hpp>
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/channel/channel_subscriber.hpp>

using unitree::robot::ChannelFactory;
using unitree::robot::ChannelSubscriber;
using unitree_hg::msg::dds_::BmsState_;
using unitree_hg::msg::dds_::LowState_;

namespace {

// 모터 상태 토픽: SDK 예제(example/g1)에서 확인된 이름
const std::string kLowStateTopic = "rt/lowstate";
// 배터리(BMS) 토픽: SDK 예제에는 없는 이름. 로봇에서 실제 토픽 이름을 확인하고 다르면 수정할 것
const std::string kBmsStateTopic = "rt/lf/bmsstate";

constexpr int kNumJoints = 29;  // G1 29DoF 기준

const std::array<const char*, kNumJoints> kJointNames = {
    "LeftHipPitch",      "LeftHipRoll",       "LeftHipYaw",       "LeftKnee",
    "LeftAnklePitch",    "LeftAnkleRoll",     "RightHipPitch",    "RightHipRoll",
    "RightHipYaw",       "RightKnee",         "RightAnklePitch",  "RightAnkleRoll",
    "WaistYaw",          "WaistRoll",         "WaistPitch",       "LeftShoulderPitch",
    "LeftShoulderRoll",  "LeftShoulderYaw",   "LeftElbow",        "LeftWristRoll",
    "LeftWristPitch",    "LeftWristYaw",      "RightShoulderPitch", "RightShoulderRoll",
    "RightShoulderYaw",  "RightElbow",        "RightWristRoll",   "RightWristPitch",
    "RightWristYaw"};

// 온도 기준. 저온 기준(cold_*)의 기본값은 임시값이므로 실제 로봇 기준을 확인해 고칠 것
struct Limits {
  int warn = 70;
  int danger = 80;
  int cold_warn = 10;
  int cold_danger = 5;
};

// 배터리 온도 기준(모터와 따로 둠). 배터리 매뉴얼의 충전 가능 범위 0~50도를 참고한 값.
// BMS 온도 값의 단위가 섭씨인지 확인 전이므로 확인 후 조정할 것
const Limits kBatteryLimits = {45, 50, 10, 5};

using Clock = std::chrono::steady_clock;
constexpr auto kTemperaturePeriod = std::chrono::seconds(10);

struct Shared {
  std::mutex mtx;
  LowState_ low;
  BmsState_ bms;
  bool has_low = false;
  bool has_bms = false;
  Clock::time_point low_time;
  Clock::time_point bms_time;
};

Shared g_shared;

void LowStateHandler(const void* message) {
  std::lock_guard<std::mutex> lock(g_shared.mtx);
  g_shared.low = *static_cast<const LowState_*>(message);
  g_shared.has_low = true;
  g_shared.low_time = Clock::now();
}

void BmsStateHandler(const void* message) {
  std::lock_guard<std::mutex> lock(g_shared.mtx);
  g_shared.bms = *static_cast<const BmsState_*>(message);
  g_shared.has_bms = true;
  g_shared.bms_time = Clock::now();
}

// hot: 과열 판단에 쓸 값(큰 쪽), cold: 저온 판단에 쓸 값(작은 쪽)
const char* Level(int hot, int cold, const Limits& lim) {
  if (hot >= lim.danger) return "DANGER";
  if (cold <= lim.cold_danger) return "COLD-DANGER";
  if (hot >= lim.warn) return "WARN";
  if (cold <= lim.cold_warn) return "COLD-WARN";
  return "ok";
}

double AgeSec(Clock::time_point t) {
  return std::chrono::duration<double>(Clock::now() - t).count();
}

void PrintUsage(const char* prog) {
  std::printf(
      "Usage: %s <network_interface> [warn=70] [danger=80] [cold_warn=10] [cold_danger=5]\n"
      "  required: cold_danger < cold_warn < warn < danger\n",
      prog);
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    PrintUsage(argv[0]);
    return 1;
  }
  const std::string iface = argv[1];
  Limits lim;
  if (argc > 2) lim.warn = std::atoi(argv[2]);
  if (argc > 3) lim.danger = std::atoi(argv[3]);
  if (argc > 4) lim.cold_warn = std::atoi(argv[4]);
  if (argc > 5) lim.cold_danger = std::atoi(argv[5]);
  if (!(lim.cold_danger < lim.cold_warn && lim.cold_warn < lim.warn && lim.warn < lim.danger)) {
    PrintUsage(argv[0]);
    return 1;
  }

  ChannelFactory::Instance()->Init(0, iface);

  ChannelSubscriber<LowState_> low_sub(kLowStateTopic);
  low_sub.InitChannel(LowStateHandler, 1);

  ChannelSubscriber<BmsState_> bms_sub(kBmsStateTopic);
  bms_sub.InitChannel(BmsStateHandler, 1);

  auto next_sample = Clock::now() + std::chrono::seconds(1);  // Allow discovery before the first report.
  while (true) {
    std::this_thread::sleep_until(next_sample);
    next_sample = Clock::now() + kTemperaturePeriod;

    LowState_ low;
    BmsState_ bms;
    bool has_low, has_bms;
    double low_age = 0.0, bms_age = 0.0;
    {
      std::lock_guard<std::mutex> lock(g_shared.mtx);
      low = g_shared.low;
      bms = g_shared.bms;
      has_low = g_shared.has_low;
      has_bms = g_shared.has_bms;
      if (has_low) low_age = AgeSec(g_shared.low_time);
      if (has_bms) bms_age = AgeSec(g_shared.bms_time);
    }

    std::printf("\033[2J\033[H");  // 화면 지우기
    std::printf("=== G1 health monitor (iface: %s, hot: %d/%dC, cold: %d/%dC) ===\n\n",
                iface.c_str(), lim.warn, lim.danger, lim.cold_warn, lim.cold_danger);

    // ---- 배터리 ----
    std::printf("[Battery]\n");
    if (!has_bms) {
      std::printf("  no BMS message on '%s' (check topic name)\n", kBmsStateTopic.c_str());
    } else {
      const auto& bt = bms.temperature();
      const int bms_max = *std::max_element(bt.begin(), bt.end());
      const int bms_min = *std::min_element(bt.begin(), bt.end());
      std::printf("  SOC: %d %%   SOH: %d %%   cycles: %d\n", static_cast<int>(bms.soc()),
                  static_cast<int>(bms.soh()), static_cast<int>(bms.cycle()));
      std::printf("  current (raw): %d   voltage (raw): %u\n", bms.current(),
                  static_cast<unsigned>(bms.bmsvoltage()[0]));
      std::printf("  battery temp (raw) max: %d  min: %d   [%s]\n", bms_max, bms_min,
                  Level(bms_max, bms_min, kBatteryLimits));
      if (bms_age > 3.0) std::printf("  !! BMS data is %.1f s old\n", bms_age);
    }

    // ---- 모터 ----
    std::printf("\n[Motors]\n");
    if (!has_low) {
      std::printf("  no message on '%s' (check network interface / robot power)\n",
                  kLowStateTopic.c_str());
      std::fflush(stdout);
      continue;
    }
    if (low_age > 1.0) std::printf("  !! CONNECTION LOST? last message %.1f s ago\n", low_age);

    int max_temp = -1000, max_idx = 0;
    int min_temp = 1000, min_idx = 0;
    double vol_sum = 0.0;
    std::printf("  %-3s %-20s %6s %6s  %s\n", "idx", "joint", "temp0", "temp1", "level");
    for (int i = 0; i < kNumJoints; ++i) {
      const auto& m = low.motor_state()[i];
      const int t0 = m.temperature()[0];
      const int t1 = m.temperature()[1];
      const int hot = std::max(t0, t1);
      const int cold = std::min(t0, t1);
      vol_sum += m.vol();
      if (hot > max_temp) {
        max_temp = hot;
        max_idx = i;
      }
      if (cold < min_temp) {
        min_temp = cold;
        min_idx = i;
      }
      std::printf("  %-3d %-20s %6d %6d  %s\n", i, kJointNames[i], t0, t1, Level(hot, cold, lim));
    }

    std::printf("\n  hottest: %s = %d C  [%s]\n", kJointNames[max_idx], max_temp,
                Level(max_temp, max_temp, lim));
    std::printf("  coldest: %s = %d C  [%s]\n", kJointNames[min_idx], min_temp,
                Level(min_temp, min_temp, lim));
    std::printf("  avg motor bus voltage: %.1f V\n", vol_sum / kNumJoints);
    if (max_temp >= lim.danger) {
      std::printf("\n  !!! DANGER: %d C or more. Robot may fall. Stop and cool down. !!!\a\n",
                  lim.danger);
    }
    if (min_temp <= lim.cold_danger) {
      std::printf("\n  !!! COLD-DANGER: %d C or less. Robot may fall. Stop. !!!\a\n",
                  lim.cold_danger);
    }
    std::fflush(stdout);
  }
  return 0;
}
