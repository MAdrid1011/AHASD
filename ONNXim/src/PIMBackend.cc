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

  spdlog::info("[PIMBackend] active: pim_channels={}/{} pim_clock={} MHz npu/pim ratio={:.3f} "
               "gtsu_switch={} ns ({} NPU cycles) aau_fusion={} ratio={:.2f}",
               _num_pim_channels, n_ch, _config.pim_clock_mhz, _npu_to_pim_ratio,
               _config.pim_gtsu_switch_ns, _gtsu_switch_npu_cycles,
               _config.pim_enable_aau_fusion, _config.pim_aau_fusion_ratio);
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
  if (should_apply_aau_fusion(req)) {
    const uint64_t saved = static_cast<uint64_t>(
        static_cast<double>(req->size) * static_cast<double>(_config.pim_aau_fusion_ratio));
    _stats.total_aau_fused_events++;
    _stats.total_aau_fusion_saved_bytes += saved;
  }
  uint64_t hold_until = _per_channel_hold_until_npu[cid];
  if (hold_until > npu_cycle) {
    uint64_t hold = hold_until - npu_cycle;
    _stats.total_gtsu_stall_npu_cycles += hold;
    return static_cast<uint32_t>(std::min<uint64_t>(
        hold, std::numeric_limits<uint32_t>::max()));
  }
  return 0;
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
  spdlog::info("[PIMBackend] AAU fused events: {} ; saved bytes: {}",
               _stats.total_aau_fused_events, _stats.total_aau_fusion_saved_bytes);
  spdlog::info("[PIMBackend] GTSU switches: {} ; total stall cycles: {}",
               _stats.total_gtsu_switches, _stats.total_gtsu_stall_npu_cycles);
  spdlog::info("[PIMBackend] TVC hold cycles: {}", _stats.total_tvc_hold_npu_cycles);
}
