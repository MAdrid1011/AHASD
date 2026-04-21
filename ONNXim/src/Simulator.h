#pragma once

#include "Common.h"
#include "Core.h"
#include "Dram.h"
#include "Interconnect.h"
#include "Model.h"
#include "scheduler/Scheduler.h"
#include "scheduler/LanguageScheduler.h"
#include "AHASDIntegration.h"
#include "CoSimDriver.h"
#include <queue>
#include <tuple>

#define CORE_MASK 0x1 << 1
#define DRAM_MASK 0x1 << 2
#define ICNT_MASK 0x1 << 3

class Simulator {
 public:
  Simulator(SimulationConfig config, bool language_mode);
  void register_model(std::unique_ptr<Model> model);
  // B2.1: register_language_model honours an optional "role" field in `info`:
  //   absent         -> legacy single-model path (backwards compatible)
  //   "draft"        -> primary model of a speculative scheduler
  //   "target"       -> attached to an existing spec scheduler as TLM
  void register_language_model(json info, std::unique_ptr<LanguageModel> model);
  void finish_language_model(uint32_t model_id);
  void run_simulator();
  const double get_tile_ops();
  const size_t get_number_tile() { return _tile_timestamp.size(); }
  // void run_offline(std::string model_name, uint32_t sample_count);
  // void run_multistream(std::string model_name, uint32_t sample_count,
  // uint32_t ); void run_server(std::string trace_path);
 private:
  void cycle();
  bool running();
  void set_cycle_mask();
  void handle_model();
  uint32_t get_dest_node(MemoryAccess* access);
  SimulationConfig _config;
  uint32_t _n_cores;
  uint32_t _n_memories;
  uint32_t _memory_req_size;

  // Components
  std::vector<std::unique_ptr<Core>> _cores;
  std::unique_ptr<Interconnect> _icnt;
  std::unique_ptr<Dram> _dram;
  std::unique_ptr<Scheduler> _scheduler;
  
  // period information (ps)
  uint64_t _core_period;
  uint64_t _icnt_period;
  uint64_t _dram_period;
  //
  uint64_t _core_time;
  uint64_t _icnt_time;
  uint64_t _dram_time;

  addr_type _dram_ch_stride_size;

  uint64_t _core_cycles;

  uint32_t _cycle_mask;
  bool _single_run;
  bool _language_mode;
  std::unique_ptr<LangScheduler> _lang_scheduler;
  
  // AHASD integration
  std::unique_ptr<AHASD::AHASDIntegration> _ahasd;
  bool _enable_ahasd;

  // B2.2 — PIM co-simulation driver. Inert unless SimulationConfig::pim_enable.
  std::unique_ptr<CoSimDriver> _cosim;
  // Per-channel hold queue: requests routed to a PIM channel that are still
  // waiting on a GTSU switch or TVC hold are parked here instead of being
  // handed to the DRAM backend immediately. Entries are (release_npu_cycle,
  // MemoryAccess*).
  std::vector<std::queue<std::pair<uint64_t, MemoryAccess*>>> _pim_hold_queues;

  // Icnt stat
  uint64_t _nr_from_core=0;
  uint64_t _nr_to_core=0;
  uint64_t _nr_from_mem=0;
  uint64_t _nr_to_mem=0;
  cycle_type _icnt_cycle=0;
  uint64_t _icnt_interval=0;

  struct CompareModel {
    bool operator()(const std::unique_ptr<Model>& a, const std::unique_ptr<Model>& b) const {
        return a->get_request_time() > b->get_request_time();
    }
  };
  robin_hood::unordered_map<std::string, 
    std::vector<std::unique_ptr<Tensor>>> _weight_table;
  std::vector<std::unique_ptr<Model>>  _models;
  robin_hood::unordered_map<std::string, std::unique_ptr<Model>> _language_models;
  std::vector<std::chrono::time_point<std::chrono::high_resolution_clock>> _tile_timestamp;

  bool check_defined_model(std::string model_name);
};