// B2.2 — PIMBackend implementation. See PIMBackend.h for scope/rationale.

#include "PIMBackend.h"

#include <algorithm>
#include <sstream>

PIMBackend::PIMBackend(SimulationConfig config) : _config(config) {
  if (!_config.pim_enable) {
    _active = false;
    return;
  }
  _active = true;
  uint32_t n_ch = _config.dram_channels;
  _is_pim.assign(n_ch, false);
  _per_channel_hold_until_npu.assign(n_ch, 0);
  _rank_mode.assign(n_ch, 0);  // DLM default

  parse_channel_mask(_config.pim_channel_mask);
  for (uint32_t cid = 0; cid < n_ch; ++cid) {
    if (_is_pim[cid]) _num_pim_channels++;
  }
  if (_num_pim_channels == 0) {
    spdlog::warn("[PIMBackend] pim_enable=true but 0 channels marked as PIM; disabling backend");
    _active = false;
    return;
  }

  // Clock-domain ratio. Example: core_freq=1000MHz, pim_clock=800MHz → 0.8
  const double npu_mhz = std::max<double>(1.0, static_cast<double>(_config.core_freq));
  const double pim_mhz = std::max<double>(1.0, static_cast<double>(_config.pim_clock_mhz));
  _npu_to_pim_ratio = pim_mhz / npu_mhz;

  // GTSU switch latency in NPU cycles: (switch_ns * 1e-9) * (core_freq * 1e6)
  _gtsu_switch_npu_cycles =
      static_cast<uint32_t>((static_cast<double>(_config.pim_gtsu_switch_ns) * 1e-9) *
                            (static_cast<double>(_config.core_freq) * 1e6));
  if (_gtsu_switch_npu_cycles == 0) _gtsu_switch_npu_cycles = 1;
  _aau_bypass_npu_cycles =
      static_cast<uint32_t>((static_cast<double>(_config.pim_aau_bypass_ns) * 1e-9) *
                            (static_cast<double>(_config.core_freq) * 1e6));
  _ssrc_bypass_npu_cycles =
      static_cast<uint32_t>((static_cast<double>(_config.ssrc_bypass_ns) * 1e-9) *
                            (static_cast<double>(_config.core_freq) * 1e6));
  if (_config.ssrc_enable && _ssrc_bypass_npu_cycles == 0) _ssrc_bypass_npu_cycles = 1;

  spdlog::info("[PIMBackend] active: pim_channels={}/{} pim_clock={} MHz npu/pim ratio={:.3f} "
               "gtsu_switch={} ns ({} NPU cycles) aau_fusion={} ratio={:.2f} "
               "ssrc_enable={} ssrc_bypass_ns={} ({} NPU cycles)",
               _num_pim_channels, n_ch, _config.pim_clock_mhz, _npu_to_pim_ratio,
               _config.pim_gtsu_switch_ns, _gtsu_switch_npu_cycles,
               _config.pim_enable_aau_fusion, _config.pim_aau_fusion_ratio,
               _config.ssrc_enable, _config.ssrc_bypass_ns, _ssrc_bypass_npu_cycles);
}

void PIMBackend::parse_channel_mask(const std::string& mask) {
  uint32_t n_ch = static_cast<uint32_t>(_is_pim.size());
  if (!mask.empty()) {
    std::stringstream ss(mask);
    std::string tok;
    while (std::getline(ss, tok, ',')) {
      if (tok.empty()) continue;
      try {
        uint32_t cid = static_cast<uint32_t>(std::stoul(tok));
        if (cid < n_ch) _is_pim[cid] = true;
      } catch (...) {
        spdlog::warn("[PIMBackend] ignoring non-numeric channel id '{}' in pim_channel_mask", tok);
      }
    }
    return;
  }
  // Auto: pick every `pim_channel_stride`-th channel (default 2 → half).
  uint32_t stride = std::max(1u, _config.pim_channel_stride);
  for (uint32_t cid = 0; cid < n_ch; cid += stride) {
    _is_pim[cid] = true;
  }
}

bool PIMBackend::should_apply_aau_fusion(const MemoryAccess* req) const {
  // Use the existing request_identity_tagged flag as the proxy for
  // attention-class (KV cache) traffic. B2.5 / F1 can refine to a per-tag
  // class id; for now, tagged==attention.
  return _config.pim_enable_aau_fusion && req != nullptr && req->request_identity_tagged;
}

uint32_t PIMBackend::on_dram_push(uint32_t cid, MemoryAccess* req, uint64_t npu_cycle) {
  if (!_active || !is_pim_channel(cid)) return 0;
  _stats.total_pim_requests++;
  if (req != nullptr) {
    if (req->write) {
      _stats.total_pim_write_requests++;
      _stats.total_pim_write_bytes += req->size;
    } else {
      _stats.total_pim_read_requests++;
      _stats.total_pim_read_bytes += req->size;
    }
    if (req->request_identity_tagged) _stats.total_attention_class_requests++;
  }
  // Note: AAU fusion statistics are now emitted in try_aau_bypass(), which
  // Simulator calls BEFORE on_dram_push so fused requests never hit DRAM.
  // Anything reaching on_dram_push is non-fused traffic that still pays
  // GTSU/TVC holds on PIM channels.
  uint64_t hold_until = _per_channel_hold_until_npu[cid];
  if (hold_until > npu_cycle) {
    uint64_t hold = hold_until - npu_cycle;
    _stats.total_gtsu_stall_npu_cycles += hold;
    return static_cast<uint32_t>(std::min<uint64_t>(
        hold, std::numeric_limits<uint32_t>::max()));
  }
  return 0;
}

bool PIMBackend::try_ssrc_bypass(uint32_t cid, MemoryAccess* req,
                                 uint64_t /*npu_cycle*/) {
  if (!_active) return false;
  if (_ssrc == nullptr || !_ssrc->is_enabled()) return false;
  if (req == nullptr) return false;
  // F1 diag: count every tagged write reaching the bypass path so the
  // §5.6 report can distinguish "SSRC saw a candidate" from "SSRC chose
  // to defer".  Pre-gated on is_enabled() so ahasd_full paths stay
  // bit-identical.
  if (req->write && req->request_identity_tagged) {
    _stats.ssrc_tagged_writes_total++;
    if (is_pim_channel(cid)) _stats.ssrc_tagged_pim_writes_seen++;
  }
  if (!is_pim_channel(cid)) return false;
  // SSRC defers speculative draft state (KV cache writes); reads still
  // need to go to DRAM because subsequent rounds may read committed
  // prefix state. Non-attention-class traffic is never deferred.
  if (!req->write || !req->request_identity_tagged) return false;
  if (_ssrc_bypass_npu_cycles == 0) return false;
  if (req->request_id == INVALID_REQUEST_ID) {
    _stats.ssrc_rejected_invalid_id++;
    return false;
  }
  if (!_ssrc->is_active_request(req->request_id)) {
    _stats.ssrc_rejected_not_active++;
    return false;
  }

  // Route through SSRC bypass queue — request never hits DRAM.
  _ssrc->note_bypassed_write(req->request_id, req->size);
  _stats.total_pim_requests++;
  _stats.total_pim_write_requests++;
  _stats.total_pim_write_bytes += req->size;
  _stats.total_attention_class_requests++;
  _stats.total_ssrc_bypassed_requests++;
  _stats.total_ssrc_bypassed_bytes += req->size;
  return true;
}

bool PIMBackend::try_aau_bypass(uint32_t cid, MemoryAccess* req,
                                uint64_t /*npu_cycle*/) {
  if (!_active || !is_pim_channel(cid)) return false;
  if (!should_apply_aau_fusion(req)) return false;
  if (_aau_bypass_npu_cycles == 0) return false;
  // AAU absorbs this K/V fetch entirely — the request will complete via
  // the bypass queue in Simulator with _aau_bypass_npu_cycles of latency.
  // Since Simulator skips on_dram_push for bypassed requests, ALL stats
  // normally maintained there must be attributed here for this request.
  _stats.total_pim_requests++;
  if (req->write) {
    _stats.total_pim_write_requests++;
    _stats.total_pim_write_bytes += req->size;
  } else {
    _stats.total_pim_read_requests++;
    _stats.total_pim_read_bytes += req->size;
  }
  _stats.total_attention_class_requests++;
  const uint64_t saved = static_cast<uint64_t>(
      static_cast<double>(req->size) * static_cast<double>(_config.pim_aau_fusion_ratio));
  _stats.total_aau_fused_events++;
  _stats.total_aau_fusion_saved_bytes += saved;
  return true;
}

void PIMBackend::on_dram_pop(uint32_t cid, MemoryAccess* req, uint64_t npu_cycle) {
  (void)cid;
  (void)req;
  (void)npu_cycle;
  // Reserved for B2.4 per-response energy sampling.
}

void PIMBackend::cycle(uint64_t npu_cycle) {
  if (!_active) return;
  _stats.last_npu_cycle = npu_cycle;
  // PIM cycle is the floor of NPU cycle * ratio; allow non-integer ratios by
  // accumulating an auxiliary fractional counter on the Stats.
  _stats.pim_cycle = static_cast<uint64_t>(static_cast<double>(npu_cycle) * _npu_to_pim_ratio);
}

uint64_t PIMBackend::request_gtsu_switch(uint32_t cid, uint32_t new_mode, uint64_t npu_cycle) {
  if (!_active || !is_pim_channel(cid)) return npu_cycle;
  if (_rank_mode[cid] == new_mode) return npu_cycle;
  uint64_t switch_done = npu_cycle + _gtsu_switch_npu_cycles;
  // Back-to-back switches cumulate latency: use max of existing hold and new.
  if (_per_channel_hold_until_npu[cid] < switch_done) {
    _per_channel_hold_until_npu[cid] = switch_done;
  }
  _rank_mode[cid] = new_mode;
  _stats.total_gtsu_switches++;
  return switch_done;
}

uint32_t PIMBackend::rank_mode(uint32_t cid) const {
  if (cid >= _rank_mode.size()) return 0;
  return _rank_mode[cid];
}

uint64_t PIMBackend::switch_all_pim_to(uint32_t new_mode, uint64_t npu_cycle) {
  if (!_active) return npu_cycle;
  uint64_t latest = npu_cycle;
  for (uint32_t cid = 0; cid < _is_pim.size(); ++cid) {
    if (!_is_pim[cid]) continue;
    uint64_t done = request_gtsu_switch(cid, new_mode, npu_cycle);
    if (done > latest) latest = done;
  }
  return latest;
}

void PIMBackend::schedule_hold_all_pim(uint64_t until_npu_cycle) {
  if (!_active) return;
  for (uint32_t cid = 0; cid < _is_pim.size(); ++cid) {
    if (!_is_pim[cid]) continue;
    schedule_hold(cid, until_npu_cycle);
  }
}

void PIMBackend::schedule_hold(uint32_t cid, uint64_t until_npu_cycle) {
  if (!_active || !is_pim_channel(cid)) return;
  if (_per_channel_hold_until_npu[cid] < until_npu_cycle) {
    uint64_t prev = _per_channel_hold_until_npu[cid];
    _per_channel_hold_until_npu[cid] = until_npu_cycle;
    if (until_npu_cycle > prev) {
      _stats.total_tvc_hold_npu_cycles += until_npu_cycle - prev;
    }
  }
}

void PIMBackend::print_statistics(uint64_t final_npu_cycle) const {
  if (!_active) return;
  spdlog::info("[PIMBackend] === B2.2 statistics ===");
  spdlog::info("[PIMBackend] final_npu_cycle={} final_pim_cycle={}", final_npu_cycle,
               _stats.pim_cycle);
  spdlog::info("[PIMBackend] PIM channels active: {}/{}", _num_pim_channels,
               static_cast<uint32_t>(_is_pim.size()));
  spdlog::info("[PIMBackend] total PIM requests: {} (read={}, write={})",
               _stats.total_pim_requests,
               _stats.total_pim_read_requests, _stats.total_pim_write_requests);
  spdlog::info("[PIMBackend] total PIM bytes: read={} write={}",
               _stats.total_pim_read_bytes, _stats.total_pim_write_bytes);
  spdlog::info("[PIMBackend] attention-class requests through PIM: {}",
               _stats.total_attention_class_requests);
  spdlog::info("[PIMBackend] AAU bypass latency (NPU cycles/event): {}",
               _aau_bypass_npu_cycles);
  spdlog::info("[PIMBackend] AAU fused events: {} ; saved bytes: {}",
               _stats.total_aau_fused_events, _stats.total_aau_fusion_saved_bytes);
  spdlog::info("[PIMBackend] GTSU switches: {} ; total stall cycles: {}",
               _stats.total_gtsu_switches, _stats.total_gtsu_stall_npu_cycles);
  spdlog::info("[PIMBackend] TVC hold cycles: {}", _stats.total_tvc_hold_npu_cycles);
  spdlog::info("[PIMBackend] SSRC bypassed writes: {} ; bytes: {} ; bypass latency (NPU cycles/event): {}",
               _stats.total_ssrc_bypassed_requests, _stats.total_ssrc_bypassed_bytes,
               _ssrc_bypass_npu_cycles);
  spdlog::info("[PIMBackend] SSRC diag: tagged_writes_total={} tagged_pim_writes_seen={} rejected_invalid_id={} rejected_not_active={}",
               _stats.ssrc_tagged_writes_total,
               _stats.ssrc_tagged_pim_writes_seen,
               _stats.ssrc_rejected_invalid_id,
               _stats.ssrc_rejected_not_active);
}
