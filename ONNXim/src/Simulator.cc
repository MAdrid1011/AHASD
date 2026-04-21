#include "Simulator.h"

#include <algorithm>
#include <filesystem>
#include <string>

#include "SystolicOS.h"
#include "SystolicWS.h"

namespace fs = std::filesystem;

Simulator::Simulator(SimulationConfig config, bool language_mode)
    : _config(config), _core_cycles(0), _language_mode(language_mode) {
  // Create dram object
  spdlog::info("Simulator Configuration:");
  for (int i=0; i<config.num_cores;i++)
    spdlog::info("[Core {}] Systolic Array Throughput: {} GFLOPS, Spad size: {} KB, Accumulator size: {} KB",
      i, config.max_systolic_flops(i), config.core_config[i].spad_size, config.core_config[i].accum_spad_size);
  spdlog::info("DRAM Bandwidth {} GB/s", config.max_dram_bandwidth());
  _core_period = 1000000 / (config.core_freq);
  _icnt_period = 1000000 / (config.icnt_freq);
  _dram_period = 1000000 / (config.dram_freq);
  _core_time = 0;
  _dram_time = 0;
  _icnt_time = 0;
  char* onnxim_path_env = std::getenv("ONNXIM_HOME");
  std::string onnxim_path = onnxim_path_env != NULL?
  std::string(onnxim_path_env) : std::string("./");
  if (config.dram_type == DramType::SIMPLE) {
    _dram = std::make_unique<SimpleDram>(config);
  } else if (config.dram_type == DramType::RAMULATOR1) {
    std::string ramulator_config = fs::path(onnxim_path)
                                       .append("configs")
                                       .append(config.dram_config_path)
                                       .string();
    spdlog::info("Ramulator config: {}", ramulator_config);
    config.dram_config_path = ramulator_config;
    _dram = std::make_unique<DramRamulator>(config);
  } 
  else if (config.dram_type == DramType::RAMULATOR2) 
  {
    std::string ramulator_config = fs::path(onnxim_path)
                                       .append("configs")
                                       .append(config.dram_config_path)
                                       .string();
    spdlog::info("Ramulator2 config: {}", ramulator_config);
    config.dram_config_path = ramulator_config;
    _dram = std::make_unique<DramRamulator2>(config);
  } 
  else {
    spdlog::error("[Configuration] Invalid DRAM type...!");
    exit(EXIT_FAILURE);
  }

  // Create interconnect object
  if (config.icnt_type == IcntType::SIMPLE) {
    _icnt = std::make_unique<SimpleInterconnect>(config);
  } else if (config.icnt_type == IcntType::BOOKSIM2) {
    _icnt = std::make_unique<Booksim2Interconnect>(config);
  } else {
    spdlog::error("[Configuration] {} Invalid interconnect type...!");
    exit(EXIT_FAILURE);
  }
  _icnt_interval = config.icnt_print_interval;

  // Create core objects
  _cores.resize(config.num_cores);
  _n_cores = config.num_cores;
  _n_memories = config.dram_channels;
  _memory_req_size = config.dram_req_size;
  for (int core_index = 0; core_index < _n_cores; core_index++) {
    _cores[core_index] = Core::create(core_index, config);
  }

  //Configure Hardware Scheduler
  _scheduler = Scheduler::create(_config, &_core_cycles, &_core_time, this);
  
  // B2.2 — instantiate PIM co-simulation driver (no-op when pim_enable=false).
  _cosim = std::make_unique<CoSimDriver>(_config);
  _pim_hold_queues.resize(_n_memories);
  if (_cosim->is_active()) {
    spdlog::info("[Simulator] PIM co-sim active; per-channel hold queues sized to {}", _n_memories);
  }

  // Initialize AHASD if enabled
  _enable_ahasd = _config.enable_ahasd;
  if (_enable_ahasd) {
    AHASD::AHASDConfig ahasd_config;
    ahasd_config.enable_edc = _config.enable_edc;
    ahasd_config.enable_tvc = _config.enable_tvc;
    ahasd_config.enable_aau = _config.enable_aau;
    ahasd_config.pim_freq_mhz = _config.dram_freq;  // PIM freq = DRAM freq
    ahasd_config.npu_freq_mhz = _config.core_freq;  // NPU freq = Core freq
    ahasd_config.max_draft_length = _config.max_draft_length;
    ahasd_config.enable_ssrc = _config.enable_ssrc;
    ahasd_config.enable_ssrc_proxy = _config.enable_ssrc_proxy;
    ahasd_config.enable_ssrc_trace = _config.enable_ssrc_trace;
    ahasd_config.ssrc_state_bytes_per_token = _config.ssrc_state_bytes_per_token;
    ahasd_config.ssrc_resident_limit_bytes = _config.ssrc_resident_limit_bytes;
    ahasd_config.ssrc_confidence_threshold = _config.ssrc_confidence_threshold;
    ahasd_config.dram_req_size = _config.dram_req_size;
    ahasd_config.dram_latency = _config.dram_latency;
    _ahasd = std::make_unique<AHASD::AHASDIntegration>(ahasd_config);
    spdlog::info("[AHASD] Enabled - EDC:{} TVC:{} AAU:{} SSRC:{} Proxy:{} Trace:{}",
                 ahasd_config.enable_edc, ahasd_config.enable_tvc, ahasd_config.enable_aau,
                 ahasd_config.enable_ssrc, ahasd_config.enable_ssrc_proxy,
                 ahasd_config.enable_ssrc_trace);
  }
  
  /* Create heap */
  std::make_heap(_models.begin(), _models.end(), CompareModel());
}

void Simulator::run_simulator() {
  spdlog::info("======Start Simulation=====");
  cycle();
}

void Simulator::handle_model() {
  if(_language_mode) {
    _lang_scheduler->cycle();
    if(_lang_scheduler->can_schedule_model()) {
      _models.push_back(_lang_scheduler->pop_model());
      std::push_heap(_models.begin(), _models.end(), CompareModel());
      if (_enable_ahasd && _ahasd && _config.enable_ssrc_proxy &&
          !_config.enable_ssrc_trace) {
        _ahasd->submit_proxy_draft(_core_cycles);
      }
    }
  }
  while (!_models.empty() && _models.front()->get_request_time() <= _core_time) {
    std::unique_ptr<Model> launch_model = std::move(_models.front());
    std::pop_heap(_models.begin(), _models.end(), CompareModel());
    _models.pop_back();

    launch_model->initialize_model(_weight_table[launch_model->get_name()]);
    launch_model->set_request_time(_core_time);
    spdlog::info("Schedule model: {} at {} us", launch_model->get_name(), _core_time);
    _scheduler->schedule_model(std::move(launch_model), 1);
  }
}

void Simulator::cycle() {
  OpStat op_stat;
  ModelStat model_stat;
  uint32_t tile_count;
  bool is_accum_tile;
  while (running()) {
    int model_id = 0;

    set_cycle_mask();
    // Core Cycle
    if (_cycle_mask & CORE_MASK) {
      /* Handle requested model */
      handle_model();

      for (int core_id = 0; core_id < _n_cores; core_id++) {
        std::unique_ptr<Tile> finished_tile = _cores[core_id]->pop_finished_tile();
        if (finished_tile->status == Tile::Status::FINISH) {
          _scheduler->finish_tile(core_id, finished_tile->layer_id);
        }
        // Issue new tile to core
        if (!_scheduler->empty()) {
          is_accum_tile = _scheduler->is_accum_tile(core_id, 0);
          if (_cores[core_id]->can_issue(is_accum_tile)) {
            std::unique_ptr<Tile> tile = _scheduler->get_tile(core_id);
            if (tile->status == Tile::Status::INITIALIZED) {
              _cores[core_id]->issue(std::move(tile));
              _tile_timestamp.push_back(std::chrono::high_resolution_clock::now());
            }
          }
        }
        _cores[core_id]->cycle();
      }
      _core_cycles++;
    }

    // DRAM cycle
    if (_cycle_mask & DRAM_MASK) {
      _dram->cycle();
    }
    // Interconnect cycle
    if (_cycle_mask & ICNT_MASK) {
      _icnt_cycle++;

      for (int core_id = 0; core_id < _n_cores; core_id++) {
        // PUHS core to ICNT. memory request
        if (_cores[core_id]->has_memory_request()) {
          MemoryAccess *front = _cores[core_id]->top_memory_request();
          front->core_id = core_id;
          if (!_icnt->is_full(core_id, front)) {
            _icnt->push(core_id, get_dest_node(front), front);
            _cores[core_id]->pop_memory_request();
            _nr_from_core++;
          }
        }
        // Push response from ICNT. to Core.
        if (!_icnt->is_empty(core_id)) {
          _cores[core_id]->push_memory_response(_icnt->top(core_id));
          _icnt->pop(core_id);
          _nr_to_core++;
        }
      }

      for (int mem_id = 0; mem_id < _n_memories; mem_id++) {
        // B2.2 — drain PIM hold queue: any request whose GTSU/TVC stall
        // deadline has expired is now released into the DRAM backend.
        if (_cosim && _cosim->is_active() && !_pim_hold_queues[mem_id].empty()) {
          auto& front = _pim_hold_queues[mem_id].front();
          if (front.first <= _core_cycles && !_dram->is_full(mem_id, front.second)) {
            _dram->push(mem_id, front.second);
            _pim_hold_queues[mem_id].pop();
            _nr_to_mem++;
          }
        }
        // ICNT to memory
        if (!_icnt->is_empty(_n_cores + mem_id) &&
            !_dram->is_full(mem_id, _icnt->top(_n_cores + mem_id))) {
          MemoryAccess* front = _icnt->top(_n_cores + mem_id);
          // B2.2 — PIM overlay: may request that this push be held for a few
          // NPU cycles (GTSU switch, TVC pre-verify window). When active and
          // a hold is requested, park the request rather than passing to DRAM.
          uint32_t hold = 0;
          if (_cosim && _cosim->is_active()) {
            hold = _cosim->on_dram_push(mem_id, front, _core_cycles);
          }
          if (hold == 0) {
            _dram->push(mem_id, front);
          } else {
            _pim_hold_queues[mem_id].push({_core_cycles + hold, front});
          }
          _icnt->pop(_n_cores + mem_id);
          _nr_to_mem++;
        }
        // Pop response to ICNT from dram
        if (!_dram->is_empty(mem_id) &&
            !_icnt->is_full(_n_cores + mem_id, _dram->top(mem_id))) {
          MemoryAccess* resp = _dram->top(mem_id);
          if (_cosim && _cosim->is_active()) {
            _cosim->on_dram_pop(mem_id, resp, _core_cycles);
          }
          _icnt->push(_n_cores + mem_id, get_dest_node(resp), resp);
          _dram->pop(mem_id);
          _nr_from_mem++;
        }
      }
      if (_icnt_interval!=0 && _icnt_cycle % _icnt_interval == 0) {
        spdlog::info("[ICNT] Core->ICNT request {}GB/Sec", ((_memory_req_size*_nr_from_core*(1000/_icnt_period)/_icnt_interval)));
        spdlog::info("[ICNT] Core<-ICNT request {}GB/Sec", ((_memory_req_size*_nr_to_core*(1000/_icnt_period)/_icnt_interval)));
        spdlog::info("[ICNT] ICNT->MEM request {}GB/Sec", ((_memory_req_size*_nr_to_mem*(1000/_icnt_period)/_icnt_interval)));
        spdlog::info("[ICNT] ICNT<-MEM request {}GB/Sec", ((_memory_req_size*_nr_from_mem*(1000/_icnt_period)/_icnt_interval)));
        _nr_from_core=0;
        _nr_to_core=0;
        _nr_to_mem=0;
        _nr_from_mem=0;
      }
      _icnt->cycle();
    }
    
    // AHASD cycle update
    if (_enable_ahasd && _ahasd) {
      if (_cycle_mask & CORE_MASK) {
        _ahasd->cycle_npu();
        _ahasd->update_npu_progress(_core_cycles);
      }
      if (_cycle_mask & DRAM_MASK) {
        _ahasd->cycle_pim();
      }
    }

    // B2.2 — advance PIM-domain clock tracking and drain any held PIM pushes
    // that have reached their deadline (the in-loop drain above handles
    // matching with DRAM availability; this call only updates the driver's
    // internal cycle tracker).
    if (_cosim && _cosim->is_active() && (_cycle_mask & CORE_MASK)) {
      _cosim->cycle(_core_cycles);
    }
  }
  spdlog::info("Simulation Finished at {} cycle {} us", _core_cycles, _core_cycles / (_config.core_freq) );
  if (_enable_ahasd && _ahasd) {
    if (_cosim && _cosim->is_active()) {
      // B2.2 — real cycle coupling is now possible: GTSU/TVC holds (and, in
      // B2.3, EDC/AAU via PIMBackend) modulate _core_cycles via the push path.
      spdlog::info("AHASD Metric Scope: coupled_accounting");
      spdlog::info("AHASD Cycle Coupling: real_coupling (pim_channels={}/{})",
                   _cosim->pim()->num_pim_channels(),
                   _cosim->pim()->total_channels());
    } else {
      spdlog::info("AHASD Metric Scope: sidecar_accounting");
      spdlog::info("AHASD Cycle Coupling: sidecar_only");
    }
  }
  uint64_t request_identity_tagged_requests = 0;
  uint64_t request_identity_tagged_bytes = 0;
  uint64_t request_identity_tagged_read_bytes = 0;
  uint64_t request_identity_tagged_write_bytes = 0;
  for (int core_id = 0; core_id < _n_cores; core_id++) {
    request_identity_tagged_requests += _cores[core_id]->get_request_identity_tagged_requests();
    request_identity_tagged_bytes += _cores[core_id]->get_request_identity_tagged_bytes();
    request_identity_tagged_read_bytes += _cores[core_id]->get_request_identity_tagged_read_bytes();
    request_identity_tagged_write_bytes += _cores[core_id]->get_request_identity_tagged_write_bytes();
  }
  spdlog::info("SSRC Request Identity Bridge Active: {}",
               request_identity_tagged_requests > 0 ? 1 : 0);
  spdlog::info("SSRC Request Identity Tagged Requests: {}",
               request_identity_tagged_requests);
  spdlog::info("SSRC Request Identity Tagged Bytes: {}",
               request_identity_tagged_bytes);
  spdlog::info("SSRC Request Identity Tagged Read Bytes: {}",
               request_identity_tagged_read_bytes);
  spdlog::info("SSRC Request Identity Tagged Write Bytes: {}",
               request_identity_tagged_write_bytes);
  spdlog::info("SSRC Request Identity Tagged Class: kv_cache_write");
  
  /* Print simulation stats */
  for (int core_id = 0; core_id < _n_cores; core_id++) {
    _cores[core_id]->print_stats();
  }
  _icnt->print_stats();
  _dram->print_stat();
  
  // Print AHASD statistics
  if (_enable_ahasd && _ahasd) {
    _ahasd->print_statistics(_core_cycles);
  }
  // B2.2 — PIM / CoSim statistics (feeds into B2.4 energy extraction).
  if (_cosim) {
    _cosim->print_statistics(_core_cycles);
  }
}

void Simulator::register_model(std::unique_ptr<Model> model) {
  if(_weight_table.find(model->get_name()) == _weight_table.end()) {
    model->initialize_weight(_weight_table[model->get_name()]);
  } 
  _models.push_back(std::move(model));
  std::push_heap(_models.begin(), _models.end(), CompareModel());
}

void Simulator::register_language_model(json info, std::unique_ptr<LanguageModel> model) {
  std::string name = info["name"];
  std::string trace_file = info["trace_file"];
  char* onnxim_path_env = std::getenv("ONNXIM_HOME");
  std::string onnxim_path = onnxim_path_env != NULL?
  std::string(onnxim_path_env) : std::string("./");
  trace_file = fs::path(onnxim_path).append("traces").append(trace_file).string();
  if(_weight_table.find(name) == _weight_table.end()) {
    model->initialize_weight(_weight_table[name]);
  }
  // B2.1: support draft/target role separation. When a scheduler is already
  // instantiated and a new model comes in with role="target", we delegate
  // attachment to the existing scheduler rather than overwriting it (the old
  // behaviour was to silently overwrite, which was what blocked TLM entirely).
  std::string role = info.contains("role") ? info["role"].get<std::string>() : std::string("");
  if (!_lang_scheduler) {
    if (role == "target") {
      spdlog::error("[Simulator] role=target given before any draft model; cannot attach");
      throw std::runtime_error("target model registered before draft");
    }
    _lang_scheduler = LangScheduler::create(name, trace_file, std::move(model), _config, info);
    spdlog::info("[Simulator] language scheduler created with model '{}' (role='{}')",
                 name, role.empty() ? "single" : role);
    return;
  }
  if (role == "target") {
    if (_lang_scheduler->attach_target_model(std::move(model), info)) {
      spdlog::info("[Simulator] target language model '{}' attached to scheduler '{}'",
                   name, _lang_scheduler->get_name());
    } else {
      spdlog::warn("[Simulator] scheduler '{}' refused target model '{}'; continuing without TLM",
                   _lang_scheduler->get_name(), name);
    }
    return;
  }
  // Legacy: second non-target registration overwrites (DAC behaviour).
  spdlog::warn("[Simulator] overwriting existing language scheduler with model '{}' (role='{}')",
               name, role.empty() ? "single" : role);
  _lang_scheduler = LangScheduler::create(name, trace_file, std::move(model), _config, info);
}

void Simulator::finish_language_model(uint32_t model_id) {
  _lang_scheduler->finish_model(model_id);
  if (_enable_ahasd && _ahasd && _config.enable_ssrc_trace) {
    auto events = _lang_scheduler->consume_finished_events();
    for (const auto& event : events) {
      if (!event.was_generation_phase) {
        continue;
      }
      uint32_t remaining = event.target_length > event.previous_length
          ? event.target_length - event.previous_length
          : event.generated_tokens;
      uint32_t draft_length =
          std::max(1u, std::min(_config.max_draft_length, remaining));
      uint32_t accepted_length =
          std::max(1u, std::min(event.generated_tokens, draft_length));
      float draft_pressure = std::min(
          1.0f, static_cast<float>(remaining) /
                    static_cast<float>(std::max(1u, _config.max_draft_length)));
      float avg_entropy = 1.2f + 1.5f * draft_pressure +
                          0.1f * static_cast<float>(event.request_id % 3);
      _ahasd->submit_trace_verified_draft(draft_length, accepted_length,
                                          event.request_id,
                                          event.previous_length,
                                          event.current_length,
                                          event.target_length, _core_cycles,
                                          avg_entropy);
    }
  }
  if (_enable_ahasd && _ahasd && _config.enable_ssrc_proxy &&
      !_config.enable_ssrc_trace) {
    _ahasd->submit_proxy_verification(_core_cycles);
  }
}

bool Simulator::running() {
  bool running = false;
  running |= !_models.empty();
  for (auto &core : _cores) {
    running = running || core->running();
  }
  running = running || _icnt->running();
  running = running || _dram->running();
  running = running || !_scheduler->empty();
  if(_language_mode) {
    running = running || _lang_scheduler->busy();
  }
  // B2.2 — outstanding PIM holds count as running work.
  if (_cosim && _cosim->is_active()) {
    for (const auto& q : _pim_hold_queues) {
      if (!q.empty()) { running = true; break; }
    }
  }
  return running;
}

void Simulator::set_cycle_mask() {
  _cycle_mask = 0x0;
  uint64_t minimum_time = MIN3(_core_time, _dram_time, _icnt_time);
  if (_core_time <= minimum_time) {
    _cycle_mask |= CORE_MASK;
    _core_time += _core_period;
  }
  if (_dram_time <= minimum_time) {
    _cycle_mask |= DRAM_MASK;
    _dram_time += _dram_period;
  }
  if (_icnt_time <= minimum_time) {
    _cycle_mask |= ICNT_MASK;
    _icnt_time += _icnt_period;
  }
}

uint32_t Simulator::get_dest_node(MemoryAccess *access) {
  if (access->request) {
    return _config.num_cores + _dram->get_channel_id(access);
  } else {
    return access->core_id;
  }
}

const double Simulator::get_tile_ops() {
  std::chrono::duration<double> duration = _tile_timestamp.back() - _tile_timestamp.front();
  if (_tile_timestamp.empty())
    return 0.0;
  else
    return _tile_timestamp.size() / duration.count();
}
