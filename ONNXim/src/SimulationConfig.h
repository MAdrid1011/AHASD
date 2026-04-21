#pragma once

#include <nlohmann/json.hpp>
#include <string>

using json = nlohmann::json;

enum class CoreType { SYSTOLIC_OS, SYSTOLIC_WS };

enum class DramType { SIMPLE, RAMULATOR1, RAMULATOR2 };

enum class IcntType { SIMPLE, BOOKSIM2 };

struct CoreConfig {
  CoreType core_type;
  uint32_t core_width;
  uint32_t core_height;

  /* Vector config*/
  uint32_t vector_process_bit;
  uint32_t layernorm_latency = 1;
  uint32_t softmax_latency = 1;
  uint32_t add_latency = 1;
  uint32_t mul_latency = 1;
  uint32_t mac_latency = 1;
  uint32_t div_latency = 1;
  uint32_t exp_latency = 1;
  uint32_t gelu_latency = 1;
  uint32_t add_tree_latency = 1;
  uint32_t scalar_sqrt_latency = 1;
  uint32_t scalar_add_latency = 1;
  uint32_t scalar_mul_latency = 1;

  /* SRAM config */
  uint32_t sram_width;
  uint32_t spad_size;
  uint32_t accum_spad_size;
};

struct SimulationConfig {
  /* Core config */
  uint32_t num_cores;
  uint32_t core_freq;
  uint32_t core_print_interval;
  struct CoreConfig *core_config;

  /* DRAM config */
  DramType dram_type;
  uint32_t dram_freq;
  uint32_t dram_channels;
  uint32_t dram_req_size;
  uint32_t dram_latency;
  uint32_t dram_size; // in GB
  uint32_t dram_nbl = 1; // busrt length in clock cycles (bust_length 8 in DDR -> 4 nbl)
  uint32_t dram_print_interval;
  std::string dram_config_path;

  /* ICNT config */
  IcntType icnt_type;
  std::string icnt_config_path;
  uint32_t icnt_freq;
  uint32_t icnt_latency;
  uint32_t icnt_print_interval=0;

  /* Sheduler config */
  std::string scheduler_type;

  /* Other configs */
  uint32_t precision;
  uint32_t full_precision = 4;
  std::string layout;
  
  /* AHASD config */
  bool enable_ahasd = false;
  bool enable_edc = true;
  bool enable_tvc = true;
  bool enable_aau = true;
  bool enable_ssrc = false;
  bool enable_ssrc_proxy = false;
  bool enable_ssrc_trace = false;
  uint32_t max_draft_length = 16;
  uint64_t ssrc_state_bytes_per_token = 524288;
  uint64_t ssrc_resident_limit_bytes = 33554432;
  float ssrc_confidence_threshold = 0.55f;

  /* B2.2 — PIM co-simulation (NPU + PIM heterogeneous DRAM).
   *   pim_enable:          master flag; when false Simulator behaves as legacy.
   *   pim_channel_mask:    channel ids routed as "PIM rank" (vs standard LPDDR).
   *                        Empty => use pim_channel_stride to auto-assign.
   *   pim_channel_stride:  when mask empty, pick every N-th channel (default 2).
   *   pim_clock_mhz:       PIM-side clock, used for NPU/PIM domain conversion.
   *   pim_enable_aau_fusion:
   *                        AAU fuses exp/sum/normalize inside PIM rank, so
   *                        attention-class traffic does NOT return to NPU.
   *   pim_aau_fusion_ratio:
   *                        fraction of attention bytes saved per fused op.
   *   pim_gtsu_switch_ns:  NPU↔PIM rank switching latency (tRRD_L/tRCD class).
   */
  bool pim_enable = false;
  std::string pim_channel_mask = "";
  uint32_t pim_channel_stride = 2;
  uint32_t pim_clock_mhz = 800;
  bool pim_enable_aau_fusion = true;
  float pim_aau_fusion_ratio = 0.75f;
  uint32_t pim_gtsu_switch_ns = 55;

  /*
   * This map stores the partition information: <partition_id, core_id>
   *
   * Note: Each core belongs to one partition. Through these partition IDs,
   * it is possible to assign a specific DNN model to a particular group of cores.
   */
  std::map<uint32_t, std::vector<uint32_t>> partiton_map;

  uint64_t align_address(uint64_t addr) {
    return addr - (addr % dram_req_size);
  }

  float max_systolic_flops(uint32_t id) {
    return core_config[id].core_width * core_config[id].core_height * core_freq * 2 * num_cores / 1000; // GFLOPS
  }

  float max_vector_flops(uint32_t id) {
    return (core_config[id].vector_process_bit >> 3) / precision * 2 * core_freq / 1000; // GFLOPS
  }

  float max_dram_bandwidth() {
    return dram_freq * dram_channels * dram_req_size / dram_nbl / 1000; // GB/s
  }

};
