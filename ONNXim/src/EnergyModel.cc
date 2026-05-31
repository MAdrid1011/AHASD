// B2.4 — Energy model implementation.
//
// All energy values are computed in pJ internally and reported in mJ (1e-9
// conversion) so the final `Total Energy` line is directly comparable to
// numbers reported in the literature.

#include "EnergyModel.h"

#include <spdlog/spdlog.h>
#include <algorithm>
#include <cmath>

namespace ahasd_energy {

namespace {
constexpr double kPJtoMJ = 1e-9;  // 1 mJ = 1e9 pJ

template <typename T>
T get_or(const json& cfg, const char* key, T fallback) {
  if (cfg.contains(key)) {
    try {
      return cfg[key].get<T>();
    } catch (...) {
      spdlog::warn("[Energy] failed to parse '{}' from config; using default", key);
    }
  }
  return fallback;
}
}  // namespace

void EnergyModel::load_from_config(const json& config) {
  _coeffs.npu_active_pj_per_cycle =
      get_or<double>(config, "energy_npu_active_pj_per_cycle", _coeffs.npu_active_pj_per_cycle);
  _coeffs.npu_vector_pj_per_cycle =
      get_or<double>(config, "energy_npu_vector_pj_per_cycle", _coeffs.npu_vector_pj_per_cycle);
  _coeffs.npu_idle_pj_per_cycle =
      get_or<double>(config, "energy_npu_idle_pj_per_cycle", _coeffs.npu_idle_pj_per_cycle);
  _coeffs.pim_read_pj_per_byte =
      get_or<double>(config, "energy_pim_read_pj_per_byte", _coeffs.pim_read_pj_per_byte);
  _coeffs.pim_write_pj_per_byte =
      get_or<double>(config, "energy_pim_write_pj_per_byte", _coeffs.pim_write_pj_per_byte);
  _coeffs.pim_rank_leak_pj_per_pim_cycle =
      get_or<double>(config, "energy_pim_rank_leak_pj_per_pim_cycle",
                     _coeffs.pim_rank_leak_pj_per_pim_cycle);
  _coeffs.aau_fusion_save_pj_per_event =
      get_or<double>(config, "energy_aau_fusion_save_pj_per_event",
                     _coeffs.aau_fusion_save_pj_per_event);
  _coeffs.bus_pj_per_byte =
      get_or<double>(config, "energy_bus_pj_per_byte", _coeffs.bus_pj_per_byte);
  _coeffs.gtsu_switch_pj_per_event =
      get_or<double>(config, "energy_gtsu_switch_pj_per_event",
                     _coeffs.gtsu_switch_pj_per_event);
}

Breakdown EnergyModel::compute(const CoreAggregate& core,
                               const PIMAggregate& pim,
                               const BusAggregate& bus) const {
  Breakdown b;

  // --- NPU compute ---
  // systolic / vector active cycles are summed across cores by the caller.
  b.npu_active_mj = static_cast<double>(core.tot_systolic_active_cycle) *
                    _coeffs.npu_active_pj_per_cycle * kPJtoMJ;
  b.npu_vector_mj = static_cast<double>(core.tot_vec_compute_cycle) *
                    _coeffs.npu_vector_pj_per_cycle * kPJtoMJ;

  // Idle energy: per-core leakage * wall cycles. Fallback to `tot_idle_cycle`
  // summed across cores if wall cycles unavailable.
  const uint64_t idle_cycles =
      core.core_cycle > 0
          ? static_cast<uint64_t>(core.core_cycle) * core.num_cores
          : core.tot_idle_cycle;
  b.npu_idle_mj = static_cast<double>(idle_cycles) *
                  _coeffs.npu_idle_pj_per_cycle * kPJtoMJ;

  // --- PIM access ---
  b.pim_read_mj  = static_cast<double>(pim.total_pim_read_bytes) *
                   _coeffs.pim_read_pj_per_byte * kPJtoMJ;
  b.pim_write_mj = static_cast<double>(pim.total_pim_write_bytes) *
                   _coeffs.pim_write_pj_per_byte * kPJtoMJ;
  b.pim_leak_mj  = static_cast<double>(pim.pim_cycle) *
                   static_cast<double>(pim.num_pim_channels) *
                   _coeffs.pim_rank_leak_pj_per_pim_cycle * kPJtoMJ;

  // --- Off-chip bus ---
  const uint64_t total_bus_bytes = bus.total_bytes_npu_to_mem +
                                   bus.total_bytes_mem_to_npu;
  b.bus_mj = static_cast<double>(total_bus_bytes) *
             _coeffs.bus_pj_per_byte * kPJtoMJ;

  // --- GTSU switch overhead ---
  b.gtsu_mj = static_cast<double>(pim.total_gtsu_switches) *
              _coeffs.gtsu_switch_pj_per_event * kPJtoMJ;

  // --- AAU savings (negative contribution) ---
  // The per-event LUT is an upper-bound estimate. On long-context runs the
  // number of fused attention requests can be very high, so cap the credit by
  // the byte traffic that AAU actually prevented from crossing PIM/bus paths.
  double event_credit_mj = static_cast<double>(pim.total_aau_fused_events) *
                           _coeffs.aau_fusion_save_pj_per_event * kPJtoMJ;
  double byte_credit_mj = event_credit_mj;
  if (pim.total_aau_fusion_saved_bytes > 0) {
    byte_credit_mj = static_cast<double>(pim.total_aau_fusion_saved_bytes) *
                     (_coeffs.pim_read_pj_per_byte + _coeffs.bus_pj_per_byte) *
                     kPJtoMJ;
  }
  b.aau_savings_mj = std::min(event_credit_mj, byte_credit_mj);

  b.total_mj = b.npu_active_mj + b.npu_vector_mj + b.npu_idle_mj +
               b.pim_read_mj + b.pim_write_mj + b.pim_leak_mj +
               b.bus_mj + b.gtsu_mj - b.aau_savings_mj;
  if (b.total_mj < 0.0) {
    spdlog::warn("[Energy] AAU savings exceeded accumulated energy "
                 "(savings={:.3f} mJ, gross={:.3f} mJ); clamping total to 0.",
                 b.aau_savings_mj, b.total_mj + b.aau_savings_mj);
    b.total_mj = 0.0;
  }
  return b;
}

void EnergyModel::print(const Breakdown& b) const {
  spdlog::info("=== Energy Breakdown (LUT model, coefficients literature-derived) ===");
  spdlog::info("NPU compute:   {:.4f} mJ  (systolic={:.4f}, vector={:.4f}, idle={:.4f})",
               b.npu_active_mj + b.npu_vector_mj + b.npu_idle_mj,
               b.npu_active_mj, b.npu_vector_mj, b.npu_idle_mj);
  spdlog::info("PIM access:    {:.4f} mJ  (read={:.4f}, write={:.4f}, leak={:.4f})",
               b.pim_read_mj + b.pim_write_mj + b.pim_leak_mj,
               b.pim_read_mj, b.pim_write_mj, b.pim_leak_mj);
  spdlog::info("Off-chip bus:  {:.4f} mJ", b.bus_mj);
  spdlog::info("GTSU switches: {:.4f} mJ", b.gtsu_mj);
  spdlog::info("AAU savings:  -{:.4f} mJ  (applied as negative credit)", b.aau_savings_mj);
  spdlog::info("Total Energy: {:.4f} mJ", b.total_mj);
}

}  // namespace ahasd_energy
