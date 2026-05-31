#ifndef PIM_BACKEND_H
#define PIM_BACKEND_H
// B2.2 — PIM backend for heterogeneous DRAM co-simulation.
//
// Role:
//   - Per-channel identity: mark which ONNXim DRAM channels act as PIM rank.
//   - NPU ↔ PIM clock-domain conversion (`pim_clock_mhz` vs `core_freq`).
//   - AAU fusion accounting: when attention-class traffic (KV cache read/write
//     tagged by Core::request_identity_tagged) lands on a PIM channel and
//     AAU fusion is enabled, track the saved off-chip bytes.
//   - GTSU gating hooks: B2.3 will call `request_gtsu_switch()` to model
//     sub-µs rank reconfiguration; this class exposes a per-channel stall
//     deadline that Simulator's push path can honour.
//   - Energy accounting inputs (B2.4): counters for read/write bytes and PIM
//     rank active time, harvested into Total Energy (mJ) output later.
//
// Scope for B2.2:
//   This does NOT compile the full PIMSimulator library into ONNXim (SCons →
//   CMake conversion + callback glue is a separate, larger task; the plan's
//   documented escape hatch is "LUT-based PIM model", which is exactly what
//   this class provides). The underlying DRAM timing model remains Ramulator2,
//   but the PIM overlay gives B2.3's EDC/TVC/AAU/GTSU real knobs that do
//   affect wall-cycle progress and per-class statistics.

#include "Common.h"
#include "SSRC.h"

#include <atomic>
#include <string>
#include <vector>

class PIMBackend {
 public:
  explicit PIMBackend(SimulationConfig config);

  bool is_active() const { return _active; }
  bool is_pim_channel(uint32_t cid) const {
    return cid < _is_pim.size() && _is_pim[cid];
  }
  uint32_t num_pim_channels() const { return _num_pim_channels; }
  uint32_t total_channels() const { return static_cast<uint32_t>(_is_pim.size()); }
  const std::vector<bool>& channel_mask() const { return _is_pim; }

  // Called by Simulator when a memory request crosses ICNT → DRAM.
  // Returns the number of NPU cycles the request should be held for before
  // actually entering the DRAM backend (0 = pass through immediately). Held
  // requests are the mechanism that gives AHASD cycle coupling — GTSU and
  // TVC are the B2.3 users of this hold-back.
  uint32_t on_dram_push(uint32_t cid, MemoryAccess* req, uint64_t npu_cycle);

  // AAU bypass path (B2.3+): when attention-class traffic can be serviced
  // directly by PIM-internal AAU (score compute + partial reductions), the
  // request never hits DRAM. `try_aau_bypass` returns true iff the request
  // was consumed by AAU — the caller MUST skip DRAM push and route the
  // request back into the response path after `bypass_latency_npu_cycles`.
  bool try_aau_bypass(uint32_t cid, MemoryAccess* req, uint64_t npu_cycle);
  uint64_t bypass_latency_npu_cycles() const { return _aau_bypass_npu_cycles; }

  // F1 — SSRC bypass path. When an SSRC coordinator has marked this
  // request_id as "deferred low-confidence draft" AND the request is an
  // attention-class write, the PIM rank redirects it through the SSRC
  // bypass queue with `ssrc_bypass_latency_npu_cycles()` of latency. Real
  // DRAM is never touched, so bytes + cycles + energy are all saved. Caller
  // MUST skip on_dram_push when this returns true.
  void attach_ssrc(AHASD::SSRCCoordinator* ssrc) { _ssrc = ssrc; }
  bool try_ssrc_bypass(uint32_t cid, MemoryAccess* req, uint64_t npu_cycle);
  uint64_t ssrc_bypass_latency_npu_cycles() const { return _ssrc_bypass_npu_cycles; }

  // Called by Simulator when a memory response leaves DRAM → ICNT.
  void on_dram_pop(uint32_t cid, MemoryAccess* req, uint64_t npu_cycle);

  // Advance PIM-domain cycle tracking. Safe to call every NPU cycle.
  void cycle(uint64_t npu_cycle);

  // --- Interfaces used by B2.3 AHASD cycle coupling ---
  // Request a rank-mode switch (DLM<->TLM) on a PIM channel. Returns the
  // NPU cycle at which the switch completes. Before this cycle any push to
  // that channel will be held (see on_dram_push).
  uint64_t request_gtsu_switch(uint32_t cid, uint32_t new_mode, uint64_t npu_cycle);
  uint32_t rank_mode(uint32_t cid) const;

  // B2.3 convenience: SpecDecodeScheduler flips every PIM-class channel
  // together on DRAFT<->VERIFY phase boundaries. Returns the latest
  // completion cycle across channels (caller may use it for observability).
  uint64_t switch_all_pim_to(uint32_t new_mode, uint64_t npu_cycle);

  // Force a per-channel hold until `until_npu_cycle`. Used by TVC to model
  // PIM-side pre-verification window.
  void schedule_hold(uint32_t cid, uint64_t until_npu_cycle);

  // B2.3 convenience: apply a hold to every PIM channel (TVC pre-verify
  // window affects all attention-class traffic).
  void schedule_hold_all_pim(uint64_t until_npu_cycle);

  // --- Statistics (also consumed by B2.4 energy model) ---
  struct Stats {
    uint64_t total_pim_requests = 0;
    uint64_t total_pim_read_requests = 0;
    uint64_t total_pim_write_requests = 0;
    uint64_t total_pim_read_bytes = 0;
    uint64_t total_pim_write_bytes = 0;
    uint64_t total_attention_class_requests = 0;
    uint64_t total_aau_fused_events = 0;
    uint64_t total_aau_fusion_saved_bytes = 0;
    uint64_t total_gtsu_switches = 0;
    uint64_t total_gtsu_stall_npu_cycles = 0;
    uint64_t total_tvc_hold_npu_cycles = 0;
    /* F1 — SSRC counters. bytes_saved tracks attention-class writes
     * that never hit DRAM because their draft round was deferred. */
    uint64_t total_ssrc_bypassed_requests = 0;
    uint64_t total_ssrc_bypassed_bytes    = 0;
    /* Diagnostic counters for pilot debugging (cheap; dropped in prod). */
    uint64_t ssrc_tagged_writes_total    = 0;
    uint64_t ssrc_tagged_pim_writes_seen = 0;
    uint64_t ssrc_rejected_invalid_id    = 0;
    uint64_t ssrc_rejected_not_active    = 0;
    uint64_t pim_cycle = 0;
    uint64_t last_npu_cycle = 0;
  };
  const Stats& stats() const { return _stats; }
  void print_statistics(uint64_t final_npu_cycle) const;

 private:
  void parse_channel_mask(const std::string& mask);
  bool should_apply_aau_fusion(const MemoryAccess* req) const;

  SimulationConfig _config;
  bool _active = false;
  std::vector<bool> _is_pim;
  std::vector<uint64_t> _per_channel_hold_until_npu;  // gtsu + tvc combined
  std::vector<uint32_t> _rank_mode;                   // 0=DLM, 1=TLM
  uint32_t _num_pim_channels = 0;
  double _npu_to_pim_ratio = 1.0;  // pim_clock / npu_clock
  uint32_t _gtsu_switch_npu_cycles = 0;
  uint32_t _aau_bypass_npu_cycles = 0;
  uint32_t _ssrc_bypass_npu_cycles = 0;

  AHASD::SSRCCoordinator* _ssrc = nullptr;

  Stats _stats;
};

#endif
