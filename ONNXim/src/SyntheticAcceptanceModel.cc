// B2.5 — Synthetic acceptance model implementation.
//
// The three modes (parametric / trace_replay / trace_then_parametric) share
// the parametric sampler; `trace_replay` short-circuits if the CSV row is
// present. The CSV loader is tolerant to blank lines and `#` comments so
// the trace generator can embed provenance at the top of the file.

#include "SyntheticAcceptanceModel.h"

#include <spdlog/spdlog.h>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <random>
#include <sstream>
#include <string>

namespace ahasd_accept {

namespace {

std::string trim(const std::string& s) {
  size_t b = s.find_first_not_of(" \t\r\n");
  if (b == std::string::npos) return "";
  size_t e = s.find_last_not_of(" \t\r\n");
  return s.substr(b, e - b + 1);
}

AcceptanceMode parse_mode(const std::string& s) {
  if (s == "trace_replay") return AcceptanceMode::TRACE_REPLAY;
  if (s == "trace_then_parametric") return AcceptanceMode::TRACE_THEN_PARAMETRIC;
  return AcceptanceMode::PARAMETRIC;
}

}  // namespace

void SyntheticAcceptanceModel::load_from_config(const SimulationConfig& config) {
  _coeffs.base         = config.accept_base;
  _coeffs.alpha        = config.accept_entropy_alpha;
  _coeffs.length_decay = config.accept_length_decay;
  _coeffs.p_min        = config.accept_p_min;
  _seed                = config.accept_rng_seed;
  _mode                = parse_mode(config.accept_mode);
  _trace_rows.clear();
  if (!config.accept_trace_path.empty()) {
    load_trace_csv(config.accept_trace_path);
  }
  spdlog::info("[Acceptance] mode={} base={:.3f} alpha={:.3f} length_decay={:.3f} p_min={:.3f} seed={} trace_rows={}",
               config.accept_mode, _coeffs.base, _coeffs.alpha,
               _coeffs.length_decay, _coeffs.p_min, _seed,
               _trace_rows.size());
}

void SyntheticAcceptanceModel::load_trace_csv(const std::string& path) {
  std::ifstream in(path);
  if (!in) {
    spdlog::warn("[Acceptance] could not open trace '{}'; falling back to parametric", path);
    return;
  }
  std::string line;
  size_t lineno = 0;
  bool header_seen = false;
  // We expect the generator to emit rows with an implicit (request_id=0,
  // spec_round=row_index). Later enhancements can embed request_id. For
  // B2.5 the smoke has a single request so this suffices.
  uint32_t default_request_id = 0;
  uint32_t implicit_round = 0;
  while (std::getline(in, line)) {
    ++lineno;
    std::string t = trim(line);
    if (t.empty() || t[0] == '#') continue;
    if (!header_seen) {
      header_seen = true;
      if (t.find("draft_length") != std::string::npos) continue;
    }
    std::stringstream ss(t);
    std::string cell;
    std::vector<std::string> cells;
    while (std::getline(ss, cell, ',')) cells.push_back(trim(cell));
    // Accept either 4 (round,draft_length,avg_entropy,accepted_length) or
    // 5 (request_id,round,draft_length,avg_entropy,accepted_length) columns.
    TraceKey key{default_request_id, implicit_round};
    TraceRow row;
    try {
      if (cells.size() == 4) {
        key.spec_round = static_cast<uint32_t>(std::stoul(cells[0]));
        row.draft_length = static_cast<uint32_t>(std::stoul(cells[1]));
        row.avg_entropy = std::stof(cells[2]);
        row.accepted_length = static_cast<uint32_t>(std::stoul(cells[3]));
      } else if (cells.size() == 5) {
        key.request_id = static_cast<uint32_t>(std::stoul(cells[0]));
        key.spec_round = static_cast<uint32_t>(std::stoul(cells[1]));
        row.draft_length = static_cast<uint32_t>(std::stoul(cells[2]));
        row.avg_entropy = std::stof(cells[3]);
        row.accepted_length = static_cast<uint32_t>(std::stoul(cells[4]));
      } else {
        spdlog::warn("[Acceptance] skipping trace line {} (expected 4 or 5 columns, got {})",
                     lineno, cells.size());
        continue;
      }
    } catch (const std::exception& e) {
      spdlog::warn("[Acceptance] skipping malformed trace line {}: {}", lineno, e.what());
      continue;
    }
    _trace_rows[key] = row;
    ++implicit_round;
  }
  spdlog::info("[Acceptance] loaded {} rows from '{}'", _trace_rows.size(), path);
}

std::optional<TraceRow> SyntheticAcceptanceModel::lookup_trace(uint32_t request_id,
                                                                uint32_t spec_round) const {
  auto it = _trace_rows.find(TraceKey{request_id, spec_round});
  if (it == _trace_rows.end()) return std::nullopt;
  return it->second;
}

uint32_t SyntheticAcceptanceModel::sample_parametric(uint32_t request_id,
                                                      uint32_t spec_round,
                                                      uint32_t draft_length,
                                                      float entropy_hint) {
  if (draft_length == 0) return 0;
  // Per-(request, round) RNG seed: XORing the three inputs plus the global
  // seed gives us reproducibility without cross-request correlation.
  uint64_t rng_seed = _seed
                       ^ (static_cast<uint64_t>(request_id) * 0x9E3779B97F4A7C15ULL)
                       ^ (static_cast<uint64_t>(spec_round) * 0xBF58476D1CE4E5B9ULL);
  std::mt19937_64 rng(rng_seed);
  std::uniform_real_distribution<double> u01(0.0, 1.0);
  double base = std::max(_coeffs.p_min,
                         std::min(1.0, _coeffs.base * std::exp(-_coeffs.alpha * entropy_hint)));
  uint32_t accepted = 0;
  const double denom = std::max<double>(1.0, static_cast<double>(draft_length - 1));
  for (uint32_t i = 0; i < draft_length; ++i) {
    double frac = static_cast<double>(i) / denom;
    double p = base * (1.0 - _coeffs.length_decay * frac);
    if (p < _coeffs.p_min) p = _coeffs.p_min;
    if (p > 1.0) p = 1.0;
    if (u01(rng) <= p) {
      ++accepted;
    } else {
      break;  // first rejection terminates the chain
    }
  }
  return accepted;
}

uint32_t SyntheticAcceptanceModel::sample(uint32_t request_id,
                                           uint32_t spec_round,
                                           uint32_t draft_length,
                                           float entropy_hint) {
  if (_mode == AcceptanceMode::TRACE_REPLAY ||
      _mode == AcceptanceMode::TRACE_THEN_PARAMETRIC) {
    if (auto row = lookup_trace(request_id, spec_round)) {
      // Honour the trace's recorded acceptance. If the draft length the
      // scheduler picked differs from what the trace row said, clamp.
      return std::min<uint32_t>(row->accepted_length, draft_length);
    }
    if (_mode == AcceptanceMode::TRACE_THEN_PARAMETRIC) {
      spdlog::debug("[Acceptance] fallback parametric for request={} round={} (no trace row)",
                    request_id, spec_round);
    }
  }
  return sample_parametric(request_id, spec_round, draft_length, entropy_hint);
}

}  // namespace ahasd_accept
