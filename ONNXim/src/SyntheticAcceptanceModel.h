#pragma once
// B2.5 — Synthetic acceptance model for speculative decoding.
//
// Replaces the `accepted_length = ceil(k/2)` placeholder that B2.1 left in
// SpecDecodeScheduler. Acceptance now depends on both the EDC-selected
// draft length `k` AND the per-round entropy hint that SpecDecodeScheduler
// already computes.
//
// Two modes:
//   - parametric        : p_accept(i | k, H) = base * exp(-alpha*H)
//                         * (1 - length_decay * i / max(1, k-1)),
//                         clamped to [p_min, 1.0]; first rejection
//                         terminates the chain (standard spec-decode
//                         semantics).
//   - trace_replay      : read a CSV with header
//                         `round,draft_length,avg_entropy,accepted_length`;
//                         lookup by (request_id, spec_round) falls back
//                         to parametric if the row is absent.
//   - trace_then_parametric : same as trace_replay but logs an `[Acceptance]
//                         fallback` line when falling through.
//
// Determinism: each (request_id, spec_round) pair seeds an independent
// `std::mt19937_64`. Re-running with the same `accept_rng_seed` yields
// identical accepted_length sequences, which is what B2.7's "AHASD on vs
// off produces different `total_cycles`" smoke needs to compare against a
// stable baseline.

#include "SimulationConfig.h"

#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>

namespace ahasd_accept {

struct AcceptanceCoeffs {
  double base         = 0.85;
  double alpha        = 0.12;   // entropy scale
  double length_decay = 0.30;   // p at i=k-1 vs p at i=0
  double p_min        = 0.05;
};

enum class AcceptanceMode {
  PARAMETRIC,
  TRACE_REPLAY,
  TRACE_THEN_PARAMETRIC,
};

struct TraceKey {
  uint32_t request_id;
  uint32_t spec_round;
  bool operator==(const TraceKey& other) const {
    return request_id == other.request_id && spec_round == other.spec_round;
  }
};
struct TraceKeyHash {
  size_t operator()(const TraceKey& k) const noexcept {
    return (static_cast<size_t>(k.request_id) << 32) ^ k.spec_round;
  }
};

struct TraceRow {
  uint32_t draft_length   = 0;
  float    avg_entropy    = 0.0f;
  uint32_t accepted_length = 0;
};

class SyntheticAcceptanceModel {
 public:
  SyntheticAcceptanceModel() = default;
  void load_from_config(const SimulationConfig& config);

  // Returns the number of accepted tokens in [0, draft_length].
  uint32_t sample(uint32_t request_id, uint32_t spec_round,
                  uint32_t draft_length, float entropy_hint);

  AcceptanceMode mode() const { return _mode; }
  const AcceptanceCoeffs& coeffs() const { return _coeffs; }
  size_t trace_rows_loaded() const { return _trace_rows.size(); }

 private:
  uint32_t sample_parametric(uint32_t request_id, uint32_t spec_round,
                             uint32_t draft_length, float entropy_hint);
  std::optional<TraceRow> lookup_trace(uint32_t request_id,
                                       uint32_t spec_round) const;
  void load_trace_csv(const std::string& path);

  AcceptanceCoeffs _coeffs;
  AcceptanceMode   _mode = AcceptanceMode::PARAMETRIC;
  uint64_t         _seed = 0x5A5A5A5A5A5A5A5AULL;
  std::unordered_map<TraceKey, TraceRow, TraceKeyHash> _trace_rows;
};

}  // namespace ahasd_accept
