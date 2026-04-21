#pragma once
// B2.3 — AHASD coordinator.
//
// The previous "sidecar" implementation (submit_proxy_*, submit_trace_*,
// account_ssrc_*, trace_semantic_*) fabricated synthetic DraftBatch events
// and accumulated SSRC statistics that were explicitly labelled as
// "modeled_sidecar_materialization_capped_not_raw_cycle_coupling". None of
// those paths influenced _core_cycles, and neither EDC nor TVC was consulted
// during the real SpecDecode loop.
//
// B2.3 replaces that with a thin coordinator that:
//   * wraps EDC + TVC as its only state;
//   * exposes decide_draft_length() / decide_pre_verify() that
//     SpecDecodeScheduler uses directly to build the task graph;
//   * exposes record_verify_result() / record_draft_batch() /
//     record_pre_verify() hooks that the scheduler calls on model
//     completion so EDC's history tables and TVC's cycle tables see real
//     simulator-measured elapsed cycles.
//
// SSRC real coupling (F1) will reintroduce its own coordinator; the SSRC
// sidecar has been deleted entirely.

#include "Common.h"
#include "async_queue/EDC.h"
#include "async_queue/TVC.h"

#include <algorithm>
#include <cstdint>
#include <memory>

namespace AHASD {

struct AHASDConfig {
  bool enable_edc = true;   // EDC gates pick_draft_length().
  bool enable_tvc = true;   // TVC gates AWAIT_VERIFY pre-verify decision.
  bool enable_aau = true;   // Informational; PIMBackend owns fusion accounting.
  float pim_freq_mhz = 800.0f;
  float npu_freq_mhz = 1000.0f;
  uint32_t max_draft_length = 16;
  uint32_t min_preverify_length = 2;
  uint32_t pre_verify_max = 8;
};

class AHASDIntegration {
 public:
  explicit AHASDIntegration(const AHASDConfig& cfg) : config_(cfg) {
    if (config_.enable_edc) {
      edc_ = std::make_unique<EDC>();
    }
    if (config_.enable_tvc) {
      tvc_ = std::make_unique<TVC>(config_.pim_freq_mhz, config_.npu_freq_mhz);
    }
  }

  const AHASDConfig& config() const { return config_; }

  // Round-level draft length. Iteratively polls EDC::should_continue_drafting
  // so LEHT / LLR / PHT see one entropy sample per drafted token, matching
  // the paper's Algorithm 1. When EDC is disabled, returns max_k.
  uint32_t decide_draft_length(uint32_t max_k, float entropy_hint) {
    ++total_draft_rounds_;
    uint32_t bounded = std::max<uint32_t>(1u, max_k);
    if (!config_.enable_edc || edc_ == nullptr) {
      return bounded;
    }
    uint32_t k = 1;
    while (k < bounded) {
      if (!edc_->should_continue_drafting(entropy_hint)) {
        break;
      }
      ++k;
    }
    return k;
  }

  // TVC-gated pre-verification insertion. Returns 0 when not inserting.
  uint32_t decide_pre_verify(uint32_t current_kv_length,
                             uint32_t pending_draft_count) {
    if (!config_.enable_tvc || tvc_ == nullptr) return 0;
    if (pending_draft_count < config_.min_preverify_length) return 0;
    auto decision = tvc_->should_insert_preverification(current_kv_length,
                                                       pending_draft_count);
    if (!decision.first) return 0;
    uint32_t bounded = std::min<uint32_t>(decision.second, config_.pre_verify_max);
    bounded = std::min(bounded, pending_draft_count);
    if (bounded == 0) return 0;
    ++total_pre_verifies_;
    return bounded;
  }

  // Called from SpecDecodeScheduler::finish_model on a VERIFY completion.
  void record_verify_result(bool fully_accepted,
                            uint32_t draft_length,
                            uint32_t accepted_length,
                            uint64_t verify_npu_cycles,
                            uint32_t kv_length) {
    ++total_verifies_;
    total_draft_tokens_ += draft_length;
    total_accepted_tokens_ += accepted_length;
    if (config_.enable_edc && edc_ != nullptr) {
      edc_->update_on_verification(fully_accepted, accepted_length);
    }
    if (config_.enable_tvc && tvc_ != nullptr) {
      tvc_->record_npu_verification(verify_npu_cycles, kv_length);
    }
  }

  // Called from SpecDecodeScheduler::finish_model on a DRAFT round completion.
  void record_draft_batch(uint64_t pim_draft_cycles, uint32_t draft_length) {
    if (config_.enable_tvc && tvc_ != nullptr) {
      tvc_->record_pim_drafting(pim_draft_cycles, draft_length);
    }
  }

  // Called from SpecDecodeScheduler::finish_model on a PRE_VERIFY completion.
  void record_pre_verify(uint64_t pim_pre_verify_cycles,
                         uint32_t pre_verify_length) {
    if (config_.enable_tvc && tvc_ != nullptr) {
      tvc_->record_pim_preverification(pim_pre_verify_cycles,
                                       pre_verify_length);
    }
  }

  // NPU-side progress beacon: called every NPU cycle by Simulator. TVC uses
  // it to estimate remaining verify cycles; EDC does not need it.
  void cycle_npu_with_progress(uint64_t npu_cycle) {
    if (config_.enable_tvc && tvc_ != nullptr) {
      tvc_->update_npu_progress(npu_cycle);
    }
  }

  void reset() {
    total_draft_rounds_ = 0;
    total_verifies_ = 0;
    total_pre_verifies_ = 0;
    total_accepted_tokens_ = 0;
    total_draft_tokens_ = 0;
    if (edc_ != nullptr) edc_->reset();
    if (tvc_ != nullptr) tvc_->reset();
  }

  double acceptance_rate() const {
    if (total_draft_tokens_ == 0) return 0.0;
    return static_cast<double>(total_accepted_tokens_) /
           static_cast<double>(total_draft_tokens_);
  }

  void print_statistics(uint64_t total_cycles) const {
    (void)total_cycles;  // reserved for B2.4 (per-cycle energy fold-in).
    spdlog::info("=== AHASD Integration Statistics ===");
    spdlog::info("Total Draft Rounds: {}", total_draft_rounds_);
    spdlog::info("Total Draft Tokens Generated: {}", total_draft_tokens_);
    spdlog::info("Total Verifies: {}", total_verifies_);
    spdlog::info("Total Pre-verifies: {}", total_pre_verifies_);
    spdlog::info("Total Accepted Tokens: {} ({:.2f}%)",
                 total_accepted_tokens_, acceptance_rate() * 100.0);
    if (config_.enable_edc && edc_ != nullptr) {
      edc_->print_statistics();
    }
    if (config_.enable_tvc && tvc_ != nullptr) {
      tvc_->print_statistics();
    }
  }

  // Paper's area/power overhead summary; kept for Section 5.4.
  static void print_hardware_costs() {
    spdlog::info("=== AHASD Hardware Overhead ===");
    size_t edc_bits = EDC::get_area_bits();
    size_t tvc_bits = TVC::get_area_bits();
    double edc_mm2 = edc_bits / (8.0 * 1024 * 1024) * 100;
    double tvc_mm2 = tvc_bits / (8.0 * 1024 * 1024) * 100;
    double aau_mm2 = 0.45;  // AAU RTL figure; refreshed in E2.
    double total_mm2 = edc_mm2 + tvc_mm2 + aau_mm2;
    double lpddr5_die_mm2 = 18.0;
    spdlog::info("EDC: {:.4f} mm^2 ({} bits)", edc_mm2, edc_bits);
    spdlog::info("TVC: {:.4f} mm^2 ({} bits)", tvc_mm2, tvc_bits);
    spdlog::info("AAU: {:.2f} mm^2", aau_mm2);
    spdlog::info("Total: {:.3f} mm^2 ({:.2f}% of LPDDR5 die)",
                 total_mm2, (total_mm2 / lpddr5_die_mm2) * 100.0);
  }

 private:
  AHASDConfig config_;
  std::unique_ptr<EDC> edc_;
  std::unique_ptr<TVC> tvc_;

  uint64_t total_draft_rounds_ = 0;
  uint64_t total_verifies_ = 0;
  uint64_t total_pre_verifies_ = 0;
  uint64_t total_accepted_tokens_ = 0;
  uint64_t total_draft_tokens_ = 0;
};

}  // namespace AHASD
