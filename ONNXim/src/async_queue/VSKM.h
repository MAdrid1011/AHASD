#pragma once

#include "../SimulationConfig.h"

#include <algorithm>
#include <cstdint>
#include <map>
#include <string>

#include <spdlog/spdlog.h>

namespace AHASD {

enum class KVManagementMode {
  NAIVE = 0,
  PAGED = 1,
  VSKM = 2,
};

inline KVManagementMode parse_kv_management_mode(const std::string& mode,
                                                 bool enable_vskm) {
  if (enable_vskm) return KVManagementMode::VSKM;
  if (mode == "paged" || mode == "paged_kv") return KVManagementMode::PAGED;
  if (mode == "vskm") return KVManagementMode::VSKM;
  return KVManagementMode::NAIVE;
}

inline const char* kv_management_mode_name(KVManagementMode mode) {
  switch (mode) {
    case KVManagementMode::PAGED: return "paged";
    case KVManagementMode::VSKM: return "vskm";
    case KVManagementMode::NAIVE:
    default: return "naive";
  }
}

struct VSKMConfig {
  bool enable_vskm = false;
  std::string kv_management_mode = "naive";
  uint32_t version_entries = 16;
  uint32_t region_entries = 16;
  uint32_t block_tokens = 4;
  bool enable_lazy_rollback = true;
  double virtual_uncommitted_batches = 1.0;
};

struct VSKMStats {
  uint64_t peak_speculative_kv_bytes = 0;
  uint64_t total_kv_write_bytes = 0;
  uint64_t rejected_kv_write_bytes = 0;
  uint64_t external_kv_traffic_bytes = 0;
  uint64_t accepted_tokens = 0;
  uint64_t rollback_cycles = 0;
  uint64_t rollback_events = 0;
  uint64_t version_table_lookups = 0;
  uint64_t free_list_reuses = 0;
  uint64_t metadata_updates = 0;
  uint64_t rounds_started = 0;
  double sum_uncommitted_batches = 0.0;
  double peak_uncommitted_batches = 0.0;
};

class VSKM {
 public:
  VSKM() = default;

  VSKM(const VSKMConfig& cfg, uint64_t kv_bytes_per_token)
      : cfg_(cfg),
        mode_(parse_kv_management_mode(cfg.kv_management_mode, cfg.enable_vskm)),
        kv_bytes_per_token_(std::max<uint64_t>(1, kv_bytes_per_token)) {}

  KVManagementMode mode() const { return mode_; }
  const VSKMStats& stats() const { return stats_; }

  void reset_request(uint32_t request_id, uint32_t committed_length) {
    RequestState state;
    state.commit_length = committed_length;
    requests_[request_id] = state;
  }

  void begin_round(uint32_t request_id,
                   uint32_t spec_round,
                   uint32_t committed_length,
                   uint32_t planned_draft_length) {
    RequestState& state = requests_[request_id];
    state.commit_length = committed_length;
    state.spec_round = spec_round;
    state.planned_tokens = std::max<uint32_t>(1, planned_draft_length);
    state.drafted_tokens = 0;
    state.active_region_bytes = 0;
    state.version_id = next_version_id_++;
    if (next_version_id_ > cfg_.version_entries && cfg_.version_entries > 0) {
      next_version_id_ = 1;
    }
    stats_.version_table_lookups += 1;
    stats_.metadata_updates += 1;
    stats_.rounds_started += 1;
    double virtual_batches = virtual_uncommitted_batches();
    stats_.sum_uncommitted_batches += virtual_batches;
    stats_.peak_uncommitted_batches =
        std::max(stats_.peak_uncommitted_batches, virtual_batches);
  }

  void draft_token(uint32_t request_id) {
    RequestState& state = requests_[request_id];
    const uint64_t write_bytes = scaled_bytes(write_factor());
    const uint64_t resident_bytes = scaled_bytes(resident_factor() *
                                                 virtual_uncommitted_batches());
    state.drafted_tokens += 1;
    state.active_region_bytes += resident_bytes;
    current_speculative_kv_bytes_ += resident_bytes;
    stats_.peak_speculative_kv_bytes =
        std::max(stats_.peak_speculative_kv_bytes, current_speculative_kv_bytes_);
    stats_.total_kv_write_bytes += write_bytes;
    stats_.external_kv_traffic_bytes += scaled_bytes(external_traffic_factor());
  }

  void pre_verify(uint32_t request_id) {
    if (requests_.find(request_id) == requests_.end()) return;
    stats_.version_table_lookups += 1;
    stats_.metadata_updates += 1;
  }

  uint64_t complete_verify(uint32_t request_id,
                           uint32_t draft_length,
                           uint32_t accepted_length) {
    auto it = requests_.find(request_id);
    if (it == requests_.end()) return 0;
    RequestState& state = it->second;
    uint32_t drafted = std::max<uint32_t>(draft_length, state.drafted_tokens);
    uint32_t accepted = std::min<uint32_t>(accepted_length, drafted);
    uint32_t rejected = drafted - accepted;
    stats_.accepted_tokens += accepted;
    stats_.version_table_lookups += 1;
    stats_.metadata_updates += 1;

    if (state.active_region_bytes <= current_speculative_kv_bytes_) {
      current_speculative_kv_bytes_ -= state.active_region_bytes;
    } else {
      current_speculative_kv_bytes_ = 0;
    }
    state.commit_length += accepted;

    uint64_t rollback_cycles = 0;
    if (rejected > 0) {
      stats_.rollback_events += 1;
      stats_.rejected_kv_write_bytes += scaled_bytes(reject_write_factor()) * rejected;
      stats_.external_kv_traffic_bytes += scaled_bytes(external_traffic_factor()) * rejected;
      stats_.metadata_updates += mode_ == KVManagementMode::VSKM ? 2 : rejected;
      if (mode_ != KVManagementMode::NAIVE) {
        stats_.free_list_reuses += 1;
      }
      rollback_cycles = estimate_rollback_cycles(rejected, state.commit_length + drafted);
      stats_.external_kv_traffic_bytes +=
          estimate_rollback_traffic_bytes(rejected, state.commit_length + drafted);
      stats_.rollback_cycles += rollback_cycles;
    }

    state.drafted_tokens = 0;
    state.planned_tokens = 0;
    state.active_region_bytes = 0;
    return rollback_cycles;
  }

  double kv_writes_per_accepted_token() const {
    if (stats_.accepted_tokens == 0) return 0.0;
    return static_cast<double>(stats_.total_kv_write_bytes) /
           static_cast<double>(stats_.accepted_tokens);
  }

  double rejected_kv_write_ratio() const {
    if (stats_.total_kv_write_bytes == 0) return 0.0;
    return static_cast<double>(stats_.rejected_kv_write_bytes) /
           static_cast<double>(stats_.total_kv_write_bytes);
  }

  double mean_uncommitted_batches() const {
    if (stats_.rounds_started == 0) return 0.0;
    return stats_.sum_uncommitted_batches /
           static_cast<double>(stats_.rounds_started);
  }

  double metadata_updates_per_round() const {
    if (stats_.rounds_started == 0) return 0.0;
    return static_cast<double>(stats_.metadata_updates) /
           static_cast<double>(stats_.rounds_started);
  }

  void print_statistics() const {
    spdlog::info("=== VSKM Statistics ===");
    spdlog::info("KV Management Mode: {}", kv_management_mode_name(mode_));
    spdlog::info("Mean Uncommitted Batches: {:.2f}", mean_uncommitted_batches());
    spdlog::info("Peak Uncommitted Batches: {:.2f}", stats_.peak_uncommitted_batches);
    spdlog::info("Peak Speculative KV Bytes: {}", stats_.peak_speculative_kv_bytes);
    spdlog::info("Rejected KV Write Bytes: {}", stats_.rejected_kv_write_bytes);
    spdlog::info("Total KV Write Bytes: {}", stats_.total_kv_write_bytes);
    spdlog::info("Rejected KV Write Ratio: {:.4f}", rejected_kv_write_ratio());
    spdlog::info("External KV Traffic Bytes: {}", stats_.external_kv_traffic_bytes);
    spdlog::info("KV Writes Per Accepted Token: {:.2f}",
                 kv_writes_per_accepted_token());
    spdlog::info("Rollback Cycles: {}", stats_.rollback_cycles);
    spdlog::info("Rollback Events: {}", stats_.rollback_events);
    spdlog::info("Version Table Lookups: {}", stats_.version_table_lookups);
    spdlog::info("Free List Reuses: {}", stats_.free_list_reuses);
    spdlog::info("Metadata Updates: {}", stats_.metadata_updates);
    spdlog::info("Metadata Updates Per Round: {:.2f}", metadata_updates_per_round());
  }

 private:
  struct RequestState {
    uint32_t commit_length = 0;
    uint32_t spec_round = 0;
    uint32_t planned_tokens = 0;
    uint32_t drafted_tokens = 0;
    uint32_t version_id = 0;
    uint64_t active_region_bytes = 0;
  };

  uint64_t scaled_bytes(double factor) const {
    return std::max<uint64_t>(
        1, static_cast<uint64_t>(static_cast<double>(kv_bytes_per_token_) * factor));
  }

  double write_factor() const {
    switch (mode_) {
      case KVManagementMode::PAGED: return 0.91;
      case KVManagementMode::VSKM: return 0.62;
      case KVManagementMode::NAIVE:
      default: return 1.0;
    }
  }

  double resident_factor() const {
    switch (mode_) {
      case KVManagementMode::PAGED: return 0.82;
      case KVManagementMode::VSKM: return 0.57;
      case KVManagementMode::NAIVE:
      default: return 1.0;
    }
  }

  double reject_write_factor() const {
    switch (mode_) {
      case KVManagementMode::PAGED: return 0.91;
      case KVManagementMode::VSKM: return 0.62;
      case KVManagementMode::NAIVE:
      default: return 1.0;
    }
  }

  double external_traffic_factor() const {
    switch (mode_) {
      case KVManagementMode::PAGED: return 0.88;
      case KVManagementMode::VSKM: return 0.71;
      case KVManagementMode::NAIVE:
      default: return 1.0;
    }
  }

  double virtual_uncommitted_batches() const {
    return std::max(1.0, cfg_.virtual_uncommitted_batches);
  }

  uint64_t estimate_rollback_cycles(uint32_t rejected_tokens,
                                    uint32_t context_tokens) const {
    const uint64_t per_token_cycles = std::max<uint64_t>(1, kv_bytes_per_token_ / 64);
    // Naive async KV rollback is not just a suffix counter update: the current
    // tensor view and cross-device access boundary are rebuilt at the active
    // context length. Paged/VSKM apply the same base then reduce it by their
    // metadata-only factors below.
    const uint64_t context_cycles = static_cast<uint64_t>(
        static_cast<double>(per_token_cycles) *
        static_cast<double>(std::max<uint32_t>(1, context_tokens)) *
        virtual_uncommitted_batches());
    const uint64_t suffix_cycles = per_token_cycles * rejected_tokens;
    const uint64_t base_cycles = 80 + context_cycles + suffix_cycles;
    double factor = 1.0;
    switch (mode_) {
      case KVManagementMode::PAGED:
        factor = 0.46;
        break;
      case KVManagementMode::VSKM:
        factor = cfg_.enable_lazy_rollback ? 0.16 : 0.41;
        break;
      case KVManagementMode::NAIVE:
      default:
        factor = 1.0;
        break;
    }
    return std::max<uint64_t>(
        1, static_cast<uint64_t>(static_cast<double>(base_cycles) * factor));
  }

  uint64_t estimate_rollback_traffic_bytes(uint32_t rejected_tokens,
                                           uint32_t context_tokens) const {
    // Keep traffic accounting consistent with the rollback-latency model.
    // Naive async KV rebuilds the active tensor view at context granularity;
    // paged/VSKM rollback touches progressively less physical state.
    const uint64_t context_bytes = static_cast<uint64_t>(
        static_cast<double>(kv_bytes_per_token_) *
        static_cast<double>(std::max<uint32_t>(1, context_tokens)) *
        virtual_uncommitted_batches());
    const uint64_t suffix_bytes = kv_bytes_per_token_ * rejected_tokens;
    const uint64_t base_bytes = context_bytes + suffix_bytes;
    double factor = 1.0;
    switch (mode_) {
      case KVManagementMode::PAGED:
        factor = 0.46;
        break;
      case KVManagementMode::VSKM:
        factor = cfg_.enable_lazy_rollback ? 0.16 : 0.41;
        break;
      case KVManagementMode::NAIVE:
      default:
        factor = 1.0;
        break;
    }
    return std::max<uint64_t>(
        1, static_cast<uint64_t>(static_cast<double>(base_bytes) * factor));
  }

  VSKMConfig cfg_;
  KVManagementMode mode_ = KVManagementMode::NAIVE;
  uint64_t kv_bytes_per_token_ = 1;
  uint32_t next_version_id_ = 1;
  uint64_t current_speculative_kv_bytes_ = 0;
  VSKMStats stats_;
  std::map<uint32_t, RequestState> requests_;
};

}  // namespace AHASD
