#pragma once
// B2.4 — Energy model (LUT-based) for AHASD co-simulation.
//
// Goal:
//   Convert the cycle-level / byte-level statistics that B2.1–B2.3 already
//   collect into a single `Total Energy (mJ)` figure (+ breakdown) that
//   Section 5.2 / 5.3 energy columns can consume.
//
// Sources of truth:
//   - Core::_stat_tot_systolic_active_cycle / _stat_tot_vec_compute_cycle /
//     _stat_tot_idle_cycle / _stat_tot_memory_idle_cycle (per-core, summed)
//   - PIMBackend::Stats (total_pim_read_bytes, total_pim_write_bytes,
//     total_aau_fused_events, total_gtsu_switches, pim_cycle)
//   - Simulator per-run ICNT byte traffic (cumulative NPU↔MEM bytes)
//
// Honesty:
//   This is a LUT-based model, not SPICE. Default coefficients are literature
//   estimates for 7 nm-class NPU @ 1 GHz + LPDDR5-PIM @ 800 MHz. E2 will
//   re-calibrate from re-synthesised AAU RTL and update `EnergyCoeffs`.
//   Coefficients are overridable via JSON (`energy_*` keys).

#include "SimulationConfig.h"

#include <cstdint>

namespace ahasd_energy {

struct EnergyCoeffs {
  // NPU core energy — per-core-cycle, multiplied by active cycle counts.
  double npu_active_pj_per_cycle   = 3000.0;   // systolic active: 128x128 MAC @ 1GHz -> ~3 nJ/cycle
  double npu_vector_pj_per_cycle   = 500.0;    // vector unit active
  double npu_idle_pj_per_cycle     = 300.0;    // leakage + clock gating residual

  // Off-chip / PIM channel access energy — per byte.
  double pim_read_pj_per_byte      = 35.0;     // LPDDR5 class: ~4 pJ/bit read
  double pim_write_pj_per_byte     = 55.0;     // writes cost more (precharge + driver)
  double pim_rank_leak_pj_per_pim_cycle = 50.0;  // per-rank idle leakage, per PIM cycle

  // AAU fusion credit — energy NOT spent because softmax/sum did not return
  // to NPU vector unit; applied as negative contribution.
  double aau_fusion_save_pj_per_event = 80000.0;  // ~80 nJ saved per fused attention op

  // Off-chip bus — every byte crossing ICNT↔DRAM boundary.
  double bus_pj_per_byte           = 40.0;

  // GTSU switch overhead — per rank-mode switch.
  double gtsu_switch_pj_per_event  = 20000.0;  // ~20 nJ per DLM↔TLM flip
};

struct CoreAggregate {
  uint64_t tot_systolic_active_cycle = 0;
  uint64_t tot_vec_compute_cycle     = 0;
  uint64_t tot_idle_cycle            = 0;
  uint64_t tot_memory_idle_cycle     = 0;
  uint64_t core_cycle                = 0;   // wall-clock cycles
  uint32_t num_cores                 = 1;
};

struct PIMAggregate {
  uint64_t total_pim_read_bytes    = 0;
  uint64_t total_pim_write_bytes   = 0;
  uint64_t total_aau_fused_events  = 0;
  uint64_t total_gtsu_switches     = 0;
  uint64_t pim_cycle               = 0;
  uint32_t num_pim_channels        = 0;
};

struct BusAggregate {
  uint64_t total_bytes_npu_to_mem = 0;   // core -> dram
  uint64_t total_bytes_mem_to_npu = 0;   // dram -> core
};

struct Breakdown {
  double npu_active_mj     = 0.0;
  double npu_vector_mj     = 0.0;
  double npu_idle_mj       = 0.0;
  double pim_read_mj       = 0.0;
  double pim_write_mj      = 0.0;
  double pim_leak_mj       = 0.0;
  double bus_mj            = 0.0;
  double gtsu_mj           = 0.0;
  double aau_savings_mj    = 0.0;   // reported as negative in totals
  double total_mj          = 0.0;
};

class EnergyModel {
 public:
  EnergyModel() = default;
  explicit EnergyModel(EnergyCoeffs coeffs) : _coeffs(coeffs) {}

  // Override defaults from SimulationConfig JSON (forward-compatible: keys
  // absent ⇒ leave defaults in place).
  void load_from_config(const json& config);

  // Compute end-of-simulation breakdown. `core` stats should be summed across
  // cores by the caller (Simulator does this naturally).
  Breakdown compute(const CoreAggregate& core,
                    const PIMAggregate& pim,
                    const BusAggregate& bus) const;

  // Pretty-print to spdlog::info. Called from Simulator::run_simulator.
  void print(const Breakdown& b) const;

  const EnergyCoeffs& coeffs() const { return _coeffs; }

 private:
  EnergyCoeffs _coeffs;
};

}  // namespace ahasd_energy
