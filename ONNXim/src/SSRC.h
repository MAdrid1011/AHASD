#pragma once
// F1 — Speculative State Rollback Control (SSRC).
//
// The sidecar SSRC that pre-dated B2.3 only accumulated "modelled"
// materialisation counters; nothing it did affected _core_cycles and there
// was no coupling back into the real request pipeline. That sidecar was
// removed in B2.3.
//
// F1 reintroduces SSRC as a tiny, auditable, simulator-level coordinator
// that actually couples into cycles via the existing PIM bypass queue.
//
// Keying is by `LangRequest.request_id` throughout: the speculative
// scheduler propagates that id into `LangInput.request_id`, `LanguageModel`
// stores it in `_reqs[batch].request_id`, operation instructions read it
// via `get_request_id(batch)`, and `Core` copies it into every emitted
// `MemoryAccess.request_id`. A PIMBackend lookup by memory-access
// `request_id` therefore resolves to the originating language request
// cleanly — no extra plumbing needed.
//
// Lifecycle:
//   (1) SpecDecodeScheduler calls `should_defer_round` once at
//       DRAFT_ROUND_START with the entropy hint EDC just saw. If SSRC
//       says "yes", the request_id is inserted into `_active_requests`.
//   (2) Every DRAFT launched for that round emits K/V MOVOUT instructions
//       whose request_id == the deferred request_id. At the PIM boundary,
//       `is_active_request(req->request_id)` returns true, and
//       `PIMBackend::try_ssrc_bypass` routes the write through the
//       short-latency bypass queue instead of paying real DRAM cycles.
//   (3) Scheduler calls `on_round_verified` once at VERIFY completion,
//       passing `accepted_length`. The coordinator retires the request
//       from `_active_requests` and credits `replayed_bytes` (accepted)
//       vs `saved_bytes` (discarded) pro-rata.
//
// Modelling caveat for the pilot: on-accept we do NOT retroactively pay
// the DRAM write cost that bypass saved (the paper's "staging flush").
// That would be an incremental change in F2 — see PROGRESS.md. Reject
// savings are modelled exactly as the paper describes.

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <mutex>
#include <string>
#include <unordered_map>

namespace AHASD {

struct SSRCConfig {
  bool     enable                 = false;
  float    confidence_threshold   = 6.0f;
  uint32_t state_bytes_per_token  = 128;
  uint64_t resident_limit_bytes   = 4 * 1024 * 1024;
  uint32_t bypass_ns              = 10;
};

class SSRCCoordinator {
 public:
  struct Stats {
    uint64_t total_round_decisions      = 0;
    uint64_t total_rounds_deferred      = 0;
    uint64_t total_rounds_refused       = 0;
    uint64_t total_rounds_committed     = 0;
    uint64_t total_rounds_discarded     = 0;
    uint64_t total_rounds_partial       = 0;
    uint64_t total_state_bytes_saved    = 0;
    uint64_t total_state_bytes_replayed = 0;
    uint64_t total_bypassed_writes      = 0;
    uint64_t total_bypassed_write_bytes = 0;
    uint64_t peak_resident_bytes        = 0;
  };

  SSRCCoordinator() = default;
  explicit SSRCCoordinator(const SSRCConfig& cfg) : _cfg(cfg) {}

  void configure(const SSRCConfig& cfg) { _cfg = cfg; }
  const SSRCConfig& config() const { return _cfg; }
  bool is_enabled() const { return _cfg.enable; }

  // Scheduler-side API ----------------------------------------------------

  // Called once per DRAFT_ROUND_START. `lang_request_id` is
  // `LangRequest.request_id`, which matches the id that will appear on
  // every MemoryAccess emitted by this round's DRAFT models.
  bool should_defer_round(uint32_t lang_request_id, uint32_t spec_round,
                          uint32_t planned_draft_length, float entropy_hint) {
    if (!_cfg.enable) return false;
    std::lock_guard<std::mutex> lk(_mu);
    ++_stats.total_round_decisions;
    if (!std::isfinite(entropy_hint)) return false;
    if (entropy_hint <= _cfg.confidence_threshold) return false;
    const uint64_t bytes =
        static_cast<uint64_t>(planned_draft_length) * _cfg.state_bytes_per_token;
    if (_resident_bytes + bytes > _cfg.resident_limit_bytes) {
      ++_stats.total_rounds_refused;
      return false;
    }
    RoundRecord rec;
    rec.spec_round           = spec_round;
    rec.planned_draft_length = planned_draft_length;
    rec.reserved_bytes       = bytes;
    _active_requests[lang_request_id] = rec;
    _resident_bytes += bytes;
    if (_resident_bytes > _stats.peak_resident_bytes) {
      _stats.peak_resident_bytes = _resident_bytes;
    }
    ++_stats.total_rounds_deferred;
    return true;
  }

  // Called once per VERIFY completion. If the request has an active
  // deferral whose spec_round matches, retire and credit accounting.
  void on_round_verified(uint32_t lang_request_id, uint32_t spec_round,
                         uint32_t accepted_length, uint32_t round_draft_length) {
    if (!_cfg.enable) return;
    std::lock_guard<std::mutex> lk(_mu);
    auto it = _active_requests.find(lang_request_id);
    if (it == _active_requests.end()) return;
    if (it->second.spec_round != spec_round) return;  // stale, ignore
    const uint64_t reserved = it->second.reserved_bytes;
    const uint32_t k = std::max<uint32_t>(1u, round_draft_length);
    const uint32_t acc = std::min(accepted_length, k);
    const uint64_t replayed = (reserved * acc) / k;
    const uint64_t saved    = reserved - replayed;
    _stats.total_state_bytes_replayed += replayed;
    _stats.total_state_bytes_saved    += saved;
    if (acc == 0)      ++_stats.total_rounds_discarded;
    else if (acc == k) ++_stats.total_rounds_committed;
    else               ++_stats.total_rounds_partial;
    _resident_bytes = (_resident_bytes >= reserved)
                          ? _resident_bytes - reserved
                          : 0;
    _active_requests.erase(it);
  }

  void abort_request(uint32_t lang_request_id) {
    if (!_cfg.enable) return;
    std::lock_guard<std::mutex> lk(_mu);
    auto it = _active_requests.find(lang_request_id);
    if (it == _active_requests.end()) return;
    _resident_bytes = (_resident_bytes >= it->second.reserved_bytes)
                          ? _resident_bytes - it->second.reserved_bytes
                          : 0;
    _active_requests.erase(it);
  }

  // PIM-side API ----------------------------------------------------------

  bool is_active_request(uint32_t lang_request_id) const {
    if (!_cfg.enable) return false;
    std::lock_guard<std::mutex> lk(_mu);
    return _active_requests.find(lang_request_id) != _active_requests.end();
  }

  void note_bypassed_write(uint32_t lang_request_id, uint64_t bytes) {
    if (!_cfg.enable) return;
    std::lock_guard<std::mutex> lk(_mu);
    if (_active_requests.find(lang_request_id) == _active_requests.end()) return;
    ++_stats.total_bypassed_writes;
    _stats.total_bypassed_write_bytes += bytes;
  }

  // Observability ---------------------------------------------------------

  Stats snapshot() const {
    std::lock_guard<std::mutex> lk(_mu);
    return _stats;
  }

  std::string summary() const {
    std::lock_guard<std::mutex> lk(_mu);
    char buf[640];
    snprintf(buf, sizeof(buf),
             "[SSRC] enable=%d thr=%.3f bytes_per_tok=%u budget=%llu B | "
             "decisions=%llu deferred=%llu refused=%llu commit=%llu "
             "discard=%llu partial=%llu | bypass_writes=%llu bytes=%llu | "
             "saved=%llu B replayed=%llu B peak=%llu B",
             _cfg.enable ? 1 : 0, _cfg.confidence_threshold,
             _cfg.state_bytes_per_token,
             (unsigned long long)_cfg.resident_limit_bytes,
             (unsigned long long)_stats.total_round_decisions,
             (unsigned long long)_stats.total_rounds_deferred,
             (unsigned long long)_stats.total_rounds_refused,
             (unsigned long long)_stats.total_rounds_committed,
             (unsigned long long)_stats.total_rounds_discarded,
             (unsigned long long)_stats.total_rounds_partial,
             (unsigned long long)_stats.total_bypassed_writes,
             (unsigned long long)_stats.total_bypassed_write_bytes,
             (unsigned long long)_stats.total_state_bytes_saved,
             (unsigned long long)_stats.total_state_bytes_replayed,
             (unsigned long long)_stats.peak_resident_bytes);
    return std::string(buf);
  }

 private:
  struct RoundRecord {
    uint32_t spec_round           = 0;
    uint32_t planned_draft_length = 0;
    uint64_t reserved_bytes       = 0;
  };

  SSRCConfig _cfg;
  mutable std::mutex _mu;
  std::unordered_map<uint32_t, RoundRecord> _active_requests;
  uint64_t _resident_bytes = 0;
  Stats    _stats{};
};

}  // namespace AHASD
