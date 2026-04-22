#include "Simulator.h"

#include <algorithm>
#include <filesystem>
#include <string>

#include "SystolicOS.h"
#include "SystolicWS.h"
#include "scheduler/SpecDecodeScheduler.h"

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
  _pim_bypass_queues.resize(_n_memories);
  if (_cosim->is_active()) {
    spdlog::info("[Simulator] PIM co-sim active; per-channel hold queues sized to {}", _n_memories);
  }

  // B2.3 — AHASD coordinator. Construction is independent of the scheduler;
  // the scheduler is injected with a pointer via attach_ahasd() after the
  // first language model is registered.
  _enable_ahasd = _config.enable_ahasd;
  if (_enable_ahasd) {
    AHASD::AHASDConfig ahasd_config;
    ahasd_config.enable_edc = _config.enable_edc;
    ahasd_config.enable_tvc = _config.enable_tvc;
    ahasd_config.enable_aau = _config.enable_aau;
    ahasd_config.pim_freq_mhz = _config.dram_freq;
    ahasd_config.npu_freq_mhz = _config.core_freq;
    ahasd_config.max_draft_length = _config.max_draft_length;
    _ahasd = std::make_unique<AHASD::AHASDIntegration>(ahasd_config);
    spdlog::info("[AHASD] Enabled - EDC:{} TVC:{} AAU:{} max_k={}",
                 ahasd_config.enable_edc, ahasd_config.enable_tvc,
                 ahasd_config.enable_aau, ahasd_config.max_draft_length);
    if (_enable_ahasd && !(_cosim && _cosim->is_active())) {
      spdlog::warn("[AHASD] enabled without PIM co-sim: GTSU stalls and AAU "
                    "fusion accounting will be inert; EDC/TVC decisions still "
                    "run but do not feed the DRAM hold queue.");
    }
  }
  
  /* Create heap */
  std::make_heap(_models.begin(), _models.end(), CompareModel());

  // B2.4 — initialise energy model from SimulationConfig coefficients.
  // Coefficients already defaulted in SimulationConfig.h; overrides are
  // applied by Common::initialize_config when optional json keys present.
  ahasd_energy::EnergyCoeffs ec;
  ec.npu_active_pj_per_cycle          = _config.energy_npu_active_pj_per_cycle;
  ec.npu_vector_pj_per_cycle          = _config.energy_npu_vector_pj_per_cycle;
  ec.npu_idle_pj_per_cycle            = _config.energy_npu_idle_pj_per_cycle;
  ec.pim_read_pj_per_byte             = _config.energy_pim_read_pj_per_byte;
  ec.pim_write_pj_per_byte            = _config.energy_pim_write_pj_per_byte;
  ec.pim_rank_leak_pj_per_pim_cycle   = _config.energy_pim_rank_leak_pj_per_pim_cycle;
  ec.aau_fusion_save_pj_per_event     = _config.energy_aau_fusion_save_pj_per_event;
  ec.bus_pj_per_byte                  = _config.energy_bus_pj_per_byte;
  ec.gtsu_switch_pj_per_event         = _config.energy_gtsu_switch_pj_per_event;
  _energy_model = ahasd_energy::EnergyModel(ec);
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
            _tot_nr_from_core++;
          }
        }
        // Push response from ICNT. to Core.
        if (!_icnt->is_empty(core_id)) {
          _cores[core_id]->push_memory_response(_icnt->top(core_id));
          _icnt->pop(core_id);
          _nr_to_core++;
          _tot_nr_to_core++;
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
            _tot_nr_to_mem++;
          }
        }
        // ICNT to memory
        if (!_icnt->is_empty(_n_cores + mem_id) &&
            !_dram->is_full(mem_id, _icnt->top(_n_cores + mem_id))) {
          MemoryAccess* front = _icnt->top(_n_cores + mem_id);
          // B2.2/issue-15 — AAU bypass: attention-class K/V reads on PIM
          // channels never hit DRAM; AAU serves them with a short bypass
          // latency and routes the response back through ICNT directly.
          bool bypassed = false;
          if (_cosim && _cosim->is_active()) {
            bypassed = _cosim->try_aau_bypass(mem_id, front, _core_cycles);
          }
          if (bypassed) {
            // Build fake completion: response mode flips to read-done.
            front->request = false;
            _pim_bypass_queues[mem_id].push(
                {_core_cycles + _cosim->bypass_latency_npu_cycles(), front});
            _icnt->pop(_n_cores + mem_id);
            _nr_to_mem++;
            _tot_nr_to_mem++;
          } else {
            // B2.2 — PIM overlay: may request that this push be held for a
            // few NPU cycles (GTSU switch, TVC pre-verify window).
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
            _tot_nr_to_mem++;
          }
        }
        // B2.2/issue-15 — drain AAU bypass queue: ready requests go straight
        // into the ICNT response path (skipping DRAM entirely).
        if (_cosim && _cosim->is_active() && !_pim_bypass_queues[mem_id].empty()) {
          auto& bfront = _pim_bypass_queues[mem_id].front();
          if (bfront.first <= _core_cycles &&
              !_icnt->is_full(_n_cores + mem_id, bfront.second)) {
            _icnt->push(_n_cores + mem_id, get_dest_node(bfront.second), bfront.second);
            _pim_bypass_queues[mem_id].pop();
            _nr_from_mem++;
            _tot_nr_from_mem++;
          }
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
          _tot_nr_from_mem++;
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
    
    // B2.3 — AHASD per-cycle update. The coordinator no longer owns
    // queue bookkeeping (AsyncQueueManager was deleted with the sidecar);
    // we only feed TVC's NCR with the current NPU cycle so its
    // should_insert_preverification() decisions see real progress.
    if (_enable_ahasd && _ahasd && (_cycle_mask & CORE_MASK)) {
      _ahasd->cycle_npu_with_progress(_core_cycles);
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
      // B2.3 — cycle coupling is genuine: GTSU switches (requested by
      // SpecDecodeScheduler on DRAFT<->VERIFY phase boundaries) park PIM
      // pushes in _pim_hold_queues, and PRE_VERIFY tasks inserted by TVC
      // run as real simulator tasks.  Both mechanisms feed _core_cycles.
      spdlog::info("AHASD Metric Scope: coupled_accounting");
      spdlog::info("AHASD Cycle Coupling: real_coupling (pim_channels={}/{})",
                   _cosim->pim()->num_pim_channels(),
                   _cosim->pim()->total_channels());
    } else {
      // AHASD is enabled but PIM co-sim is off. EDC/TVC still modulate the
      // task graph (draft length k and PRE_VERIFY insertion), which still
      // changes _core_cycles; only the GTSU / AAU paths are inert.
      spdlog::info("AHASD Metric Scope: task_graph_coupling_only");
      spdlog::info("AHASD Cycle Coupling: task_graph_only");
    }
  }
  // B2.2/B2.3 — attention-class (KV cache) traffic counters. The tag is
  // consumed by PIMBackend::should_apply_aau_fusion(); keeping the
  // aggregate visible in the log lets B2.4 derive energy from the byte
  // totals and lets validation scripts confirm the AAU path is exercised.
  uint64_t attn_tagged_requests = 0;
  uint64_t attn_tagged_bytes = 0;
  uint64_t attn_tagged_read_bytes = 0;
  uint64_t attn_tagged_write_bytes = 0;
  for (int core_id = 0; core_id < _n_cores; core_id++) {
    attn_tagged_requests += _cores[core_id]->get_request_identity_tagged_requests();
    attn_tagged_bytes += _cores[core_id]->get_request_identity_tagged_bytes();
    attn_tagged_read_bytes += _cores[core_id]->get_request_identity_tagged_read_bytes();
    attn_tagged_write_bytes += _cores[core_id]->get_request_identity_tagged_write_bytes();
  }
  spdlog::info("Attention-Class Tagged Requests: {}", attn_tagged_requests);
  spdlog::info("Attention-Class Tagged Bytes: {}", attn_tagged_bytes);
  spdlog::info("Attention-Class Tagged Read Bytes: {}", attn_tagged_read_bytes);
  spdlog::info("Attention-Class Tagged Write Bytes: {}", attn_tagged_write_bytes);

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
  // B2.5 — synthetic acceptance model summary. Only present in speculative
  // language mode; silent otherwise so legacy runs don't gain noise.
  if (_lang_scheduler && _lang_scheduler->is_speculative()) {
    if (auto* spec = dynamic_cast<SpecDecodeScheduler*>(_lang_scheduler.get())) {
      spec->print_acceptance_stats();
    }
  }

  // B2.4 — assemble final energy aggregate and emit `Total Energy` line.
  // Core stats were updated by print_stats() above, so `_stat_tot_*` reflect
  // final per-core totals and can be safely summed here.
  ahasd_energy::CoreAggregate core_agg;
  core_agg.num_cores = _n_cores;
  core_agg.core_cycle = _core_cycles;
  for (int core_id = 0; core_id < _n_cores; core_id++) {
    core_agg.tot_systolic_active_cycle +=
        _cores[core_id]->get_systolic_active_cycles();
    core_agg.tot_vec_compute_cycle +=
        _cores[core_id]->get_vec_compute_cycles();
    core_agg.tot_idle_cycle += _cores[core_id]->get_idle_cycles();
    core_agg.tot_memory_idle_cycle +=
        _cores[core_id]->get_memory_idle_cycles();
  }
  ahasd_energy::PIMAggregate pim_agg;
  if (_cosim && _cosim->is_active() && _cosim->pim()) {
    const auto& ps = _cosim->pim()->stats();
    pim_agg.total_pim_read_bytes   = ps.total_pim_read_bytes;
    pim_agg.total_pim_write_bytes  = ps.total_pim_write_bytes;
    pim_agg.total_aau_fused_events = ps.total_aau_fused_events;
    pim_agg.total_gtsu_switches    = ps.total_gtsu_switches;
    pim_agg.pim_cycle              = ps.pim_cycle;
    pim_agg.num_pim_channels       = _cosim->pim()->num_pim_channels();
  }
  ahasd_energy::BusAggregate bus_agg;
  // NPU->MEM = `_tot_nr_to_mem`, MEM->NPU = `_tot_nr_from_mem`. Per-request
  // payload size is `_memory_req_size` bytes.
  bus_agg.total_bytes_npu_to_mem = _tot_nr_to_mem   * _memory_req_size;
  bus_agg.total_bytes_mem_to_npu = _tot_nr_from_mem * _memory_req_size;

  const auto breakdown = _energy_model.compute(core_agg, pim_agg, bus_agg);
  _energy_model.print(breakdown);
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
    // B2.3 — inject AHASD + PIM into the speculative scheduler so EDC/TVC/
    // GTSU run on its real decisions. Non-speculative schedulers ignore.
    if (_lang_scheduler->is_speculative()) {
      auto* spec = dynamic_cast<SpecDecodeScheduler*>(_lang_scheduler.get());
      if (spec != nullptr) {
        spec->attach_ahasd(_enable_ahasd ? _ahasd.get() : nullptr,
                           (_cosim && _cosim->is_active()) ? _cosim->pim() : nullptr);
      }
    }
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
  // B2.3 — AHASD is now called inside SpecDecodeScheduler::finish_model via
  // the AHASDIntegration pointer attach_ahasd() injected; there is no
  // longer a post-finish sidecar submission step here.
  _lang_scheduler->finish_model(model_id);
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
    for (const auto& q : _pim_bypass_queues) {
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
