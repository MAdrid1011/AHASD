// B2.1 — Speculative decoding scheduler implementation.
// B2.3 — plugged into AHASDIntegration (EDC/TVC) and PIMBackend (GTSU) so
//        the DRAFT / PRE_VERIFY / VERIFY cadence actually drives the
//        architectural decisions rather than being a hardcoded constant.
//
// In-scope now:
//   * DRAFT (k times) -> optional PRE_VERIFY -> VERIFY cadence on a pair of
//     LanguageModel objects (DLM + TLM).
//   * EDC decides k per round; TVC decides whether to insert a PRE_VERIFY.
//   * GTSU switches on every DRAFT<->VERIFY phase boundary, which feeds
//     into PIMBackend's per-channel hold queue and therefore into real
//     wall-cycle progress.
//   * record_verify_result / record_draft_batch / record_pre_verify feed
//     elapsed cycles back to TVC and decision outcomes to EDC.
//
// Intentionally NOT in scope yet:
//   * Real KV-cache rollback beyond a length truncation (real rollback
//     including dirty-region management belongs to F1 alongside SSRC).
//   * Acceptance driven by entropy: sample_accepted_length() still uses
//     the placeholder from B2.1 until B2.5 lands the synthetic sampler.

#include "SpecDecodeScheduler.h"

#include "../AHASDIntegration.h"
#include "../PIMBackend.h"

#include <algorithm>

SpecDecodeScheduler::SpecDecodeScheduler(std::string name, std::string path,
                                         std::unique_ptr<LanguageModel> draft_model,
                                         SimulationConfig config,
                                         json scheduler_config)
    : LangScheduler(name, path, std::move(draft_model), config, scheduler_config) {
  _max_draft_length = std::max<uint32_t>(1u, _config.max_draft_length);
  _default_draft_length = _max_draft_length;
  if (_scheduler_config.contains("default_draft_length")) {
    _default_draft_length =
        std::max<uint32_t>(1u, _scheduler_config["default_draft_length"].get<uint32_t>());
  }
  spdlog::info("[SpecDecode] max_draft_length={} default_draft_length={}",
               _max_draft_length, _default_draft_length);
}

bool SpecDecodeScheduler::attach_target_model(std::unique_ptr<LanguageModel> target_model,
                                              const json& target_info) {
  if (_target_attached) {
    spdlog::warn("[SpecDecode] target model already attached; ignoring extra model '{}'",
                 target_info.contains("name") ? target_info["name"].get<std::string>() : std::string("?"));
    return false;
  }
  _target_model = std::move(target_model);
  _target_info = target_info;
  _target_attached = true;
  spdlog::info("[SpecDecode] target model attached: {}",
               target_info.contains("name") ? target_info["name"].get<std::string>() : std::string("?"));
  return true;
}

void SpecDecodeScheduler::attach_ahasd(AHASD::AHASDIntegration* ahasd,
                                        PIMBackend* pim) {
  _ahasd = ahasd;
  _pim = pim;
  spdlog::info("[SpecDecode] AHASD attached: edc={} tvc={} ; PIM attached={}",
               (_ahasd != nullptr) && _ahasd->config().enable_edc,
               (_ahasd != nullptr) && _ahasd->config().enable_tvc,
               (_pim != nullptr) && _pim->is_active());
}

float SpecDecodeScheduler::compute_entropy_hint(const LangRequest& req) const {
  // Synthetic entropy in the [0, H_MAX=10] range expected by EDC.
  // B2.5 will replace this with the trace-driven sampler output.
  //
  // Heuristic: (a) early in a request (current_length near prompt_length) we
  // seed mid entropy (~3) so EDC explores; (b) as we approach target_length,
  // entropy rises (harder to predict the last tokens); (c) per-round the
  // spec_round modulo adds a small jitter so consecutive rounds do not
  // collapse to identical PHT indices.
  uint32_t progress = req.current_length > req.prompt_length
                          ? req.current_length - req.prompt_length
                          : 0u;
  uint32_t span = req.target_length > req.prompt_length
                      ? req.target_length - req.prompt_length
                      : 1u;
  float ratio = std::min(1.0f, static_cast<float>(progress) /
                                    static_cast<float>(std::max(1u, span)));
  float base = 2.5f + 2.5f * ratio;               // 2.5 → 5.0 across request lifetime
  float jitter = 0.5f * static_cast<float>(req.spec_round % 4);  // 0.0 / 0.5 / 1.0 / 1.5
  return std::min(9.5f, std::max(0.5f, base + jitter));
}

uint32_t SpecDecodeScheduler::pick_draft_length(const LangRequest& req) {
  uint32_t remaining =
      req.target_length > req.current_length ? req.target_length - req.current_length : 0u;
  uint32_t cap = std::min<uint32_t>(_max_draft_length, std::max<uint32_t>(1u, remaining));
  if (_ahasd != nullptr && _ahasd->config().enable_edc) {
    return _ahasd->decide_draft_length(cap, compute_entropy_hint(req));
  }
  uint32_t k = std::min<uint32_t>(_default_draft_length, cap);
  return std::max<uint32_t>(1u, k);
}

uint32_t SpecDecodeScheduler::sample_accepted_length(const LangRequest& req,
                                                     uint32_t draft_length) {
  // B2.5 will replace this with a trace-driven or synthetic sampler.
  // Placeholder: accept half of the draft tokens (rounded up), capped by target.
  (void)req;
  if (draft_length == 0) return 0;
  return std::max<uint32_t>(1u, (draft_length + 1u) / 2u);
}

bool SpecDecodeScheduler::busy() {
  if (LangScheduler::busy()) return true;
  // Any request still mid-round?
  for (const auto& kv : _active_requests) {
    if (kv.second->spec_phase != LangSpecPhase::DONE) return true;
  }
  return false;
}

uint64_t SpecDecodeScheduler::get_kv_memory_size() {
  // KV usage is identical to the base accounting; target model shares the
  // request's KV tensors (same hidden size assumption — acceptable for B2.1,
  // revisit in B2.3 when DLM/TLM differ).
  return LangScheduler::get_kv_memory_size();
}

std::unique_ptr<Model> SpecDecodeScheduler::pop_model() {
  // Defer to the base queue; meta is already recorded in _model_meta when we
  // pushed the model in cycle().
  return LangScheduler::pop_model();
}

std::unique_ptr<Model> SpecDecodeScheduler::build_model(LanguageModel& model,
                                                        LangRequest& req,
                                                        LangTaskType task_type,
                                                        uint32_t seq_length) {
  LangInput input;
  input.request_id = req.request_id;
  input.seq_length = seq_length;
  input.context_length = req.current_length;
  for (uint32_t i = 0; i < _num_sim_layers; i++) {
    input.key_cache.push_back(req.key_cache[i].get());
    input.value_cache.push_back(req.value_cache[i].get());
  }
  std::vector<LangInput> inputs{input};
  auto built = model.generate_model(inputs);
  req.last_task_type = task_type;
  return built;
}

bool SpecDecodeScheduler::try_issue_one_task(LangRequest& req) {
  // Only one outstanding model per request at a time to keep accounting simple.
  // B2.3 — previously this used `_requests_in_model.find(req.request_id)`,
  // which is wrong because `_requests_in_model` is keyed by model_id, not
  // request_id. That bug caused the scheduler to issue a fresh task every
  // cycle for the same request, filling the Simulator queue with hundreds of
  // duplicate TLM inferences. `req.running` is the correct per-request
  // outstanding-model flag (set when we issue, cleared in finish_model).
  if (req.running) {
    return false;
  }

  // B2.3 — request a GTSU rank-mode switch on the PIM channels when we are
  // about to issue a task whose rank-mode differs from the current one.
  // Rank mode 0 = DLM (draft weights), 1 = TLM (target weights). The GTSU
  // request parks subsequent pushes to PIM channels until the switch
  // completes, which is the real cycle-coupling mechanism.
  auto request_rank_switch = [&](uint32_t desired_mode) {
    if (_pim == nullptr || !_pim->is_active()) return;
    auto it = _last_rank_mode.find(req.request_id);
    uint32_t current = (it == _last_rank_mode.end()) ? 0u : it->second;
    if (current == desired_mode) return;
    _pim->switch_all_pim_to(desired_mode, _cycle);
    _last_rank_mode[req.request_id] = desired_mode;
  };

  switch (req.spec_phase) {
    case LangSpecPhase::PROMPT_PENDING: {
      request_rank_switch(1);  // PROMPT runs on TLM.
      LanguageModel& model = _target_attached ? *_target_model : *_language_model;
      auto infer_model = build_model(model, req, LangTaskType::PROMPT, req.prompt_length);
      uint32_t mid = infer_model->get_id();
      _model_meta[mid] = {req.request_id, LangTaskType::PROMPT,
                          _target_attached ? "target" : "single",
                          0, 0, _cycle};
      req.running = true;
      _requests_in_model[mid].push_back(req.request_id);
      _model_queue.push(std::move(infer_model));
      return true;
    }
    case LangSpecPhase::DRAFT_ROUND_START: {
      req.planned_draft_length = pick_draft_length(req);
      req.drafted_in_round = 0;
      req.spec_round += 1;
      req.spec_phase = LangSpecPhase::DRAFTING;
      [[fallthrough]];
    }
    case LangSpecPhase::DRAFTING: {
      request_rank_switch(0);  // DRAFT runs on DLM.
      LanguageModel& model = *_language_model;
      auto infer_model = build_model(model, req, LangTaskType::DRAFT, 1u);
      uint32_t mid = infer_model->get_id();
      _model_meta[mid] = {req.request_id, LangTaskType::DRAFT, "draft",
                          req.planned_draft_length, req.spec_round, _cycle};
      req.running = true;
      _requests_in_model[mid].push_back(req.request_id);
      _model_queue.push(std::move(infer_model));
      return true;
    }
    case LangSpecPhase::AWAIT_VERIFY: {
      // B2.3 — TVC gating: does it want a PRE_VERIFY before the full VERIFY?
      // We only allow one PRE_VERIFY per spec_round to avoid livelock.
      uint32_t pv_len = 0;
      auto pv_it = _pre_verified_in_round.find(req.request_id);
      bool already_pre_verified = (pv_it != _pre_verified_in_round.end()) &&
                                  (pv_it->second == req.spec_round);
      if (_ahasd != nullptr && _ahasd->config().enable_tvc &&
          !already_pre_verified) {
        pv_len = _ahasd->decide_pre_verify(req.current_length,
                                           req.planned_draft_length);
      }

      LanguageModel& model = _target_attached ? *_target_model : *_language_model;
      uint32_t k = std::max<uint32_t>(1u, req.planned_draft_length);
      LangTaskType task = LangTaskType::VERIFY;
      uint32_t task_k = k;
      if (pv_len > 0 && pv_len < k) {
        task = LangTaskType::PRE_VERIFY;
        task_k = pv_len;
        _pre_verified_in_round[req.request_id] = req.spec_round;
      }

      request_rank_switch(1);  // VERIFY / PRE_VERIFY run on TLM.
      auto infer_model = build_model(model, req, task, task_k);
      uint32_t mid = infer_model->get_id();
      _model_meta[mid] = {req.request_id, task,
                          _target_attached ? "target" : "single",
                          task_k, req.spec_round, _cycle};
      req.verify_round_id = req.spec_round;
      req.running = true;
      _requests_in_model[mid].push_back(req.request_id);
      _model_queue.push(std::move(infer_model));
      return true;
    }
    case LangSpecPhase::DONE:
      return false;
  }
  return false;
}

void SpecDecodeScheduler::cycle() {
  _cycle++;
  if (_active_requests.size() <= _max_batch_size || _max_batch_size == 0) {
    while (!_request_queue.empty()) {
      if (_request_queue.front()->request_time <= _cycle) {
        init_request(_request_queue.front());
        auto& r = _request_queue.front();
        r->spec_phase = _target_attached ? LangSpecPhase::PROMPT_PENDING
                                         : LangSpecPhase::DRAFT_ROUND_START;
        r->spec_round = 0;
        r->drafted_in_round = 0;
        r->planned_draft_length = 0;
        _active_requests[r->request_id] = std::move(r);
        _request_queue.pop();
      } else {
        break;
      }
      if (_max_batch_size > 0 && _active_requests.size() >= _max_batch_size) {
        break;
      }
    }
  }

  if (!_target_attached) {
    // Fallback path: run the draft model as a single-model autoregressive
    // scheduler so Simulator can still boot when target fails to attach.
    // This preserves pre-B2.1 behaviour for that case.
    if (_model_queue.empty() && _requests_in_model.empty()) {
      LangScheduler::cycle();  // reuse base init_inputs_and_model
    }
    return;
  }

  // Spec mode: issue at most one model per cycle across all requests
  // (scheduler throughput, not architectural throughput — hardware-side
  // parallelism is handled by the Core/DRAM stages downstream).
  for (auto& kv : _active_requests) {
    if (try_issue_one_task(*kv.second)) {
      break;
    }
  }
}

void SpecDecodeScheduler::apply_verify_result(LangRequest& req,
                                              uint32_t draft_length,
                                              uint32_t accepted_length) {
  // Commit accepted tokens; truncate KV cache to the accepted length.
  // (Placeholder: we do not distinguish between "accepted + bonus" and
  //  "reject + correction" here — that arrives with B2.5's sampler.)
  uint32_t pre_current_length = req.current_length;
  uint32_t new_length =
      std::min(req.target_length, pre_current_length + accepted_length);
  req.current_length = new_length;
  std::vector<uint32_t> new_cache_dim{new_length, _cache_dim};
  for (uint32_t i = 0; i < _num_sim_layers; i++) {
    req.key_cache[i]->resize_tensor(new_cache_dim);
    req.value_cache[i]->resize_tensor(new_cache_dim);
  }
  if (req.current_length >= req.target_length) {
    req.spec_phase = LangSpecPhase::DONE;
    req.finish_time = _cycle;
    spdlog::info("[SpecDecode] Request {} completed in {} cycles "
                 "(spec_rounds={}, last draft_len={}, last accepted={})",
                 req.request_id, req.finish_time - req.start_time,
                 req.spec_round, draft_length, accepted_length);
  } else {
    req.spec_phase = LangSpecPhase::DRAFT_ROUND_START;
  }
}

void SpecDecodeScheduler::finish_model(uint32_t model_id) {
  auto meta_it = _model_meta.find(model_id);
  if (meta_it == _model_meta.end()) {
    // Unknown model id — delegate to base to be safe.
    LangScheduler::finish_model(model_id);
    return;
  }
  ModelMeta meta = meta_it->second;
  _model_meta.erase(meta_it);

  _last_finished_events.clear();
  auto req_it = _active_requests.find(meta.request_id);
  if (req_it == _active_requests.end()) {
    _requests_in_model.erase(model_id);
    return;
  }
  LangRequest& req = *req_it->second;

  LangStepEvent event;
  event.request_id = req.request_id;
  event.prompt_length = req.prompt_length;
  event.previous_length = req.current_length;
  event.target_length = req.target_length;
  event.task_type = meta.task_type;
  event.model_role = meta.role;
  event.draft_length = meta.draft_length_at_issue;
  event.spec_round = meta.verify_round;

  switch (meta.task_type) {
    case LangTaskType::PROMPT: {
      // Target prefill complete. Model KV cache covers prompt_length tokens.
      req.current_length += req.prompt_length;
      req.gen_phase = true;
      std::vector<uint32_t> new_cache_dim{req.current_length, _cache_dim};
      for (uint32_t i = 0; i < _num_sim_layers; i++) {
        req.key_cache[i]->resize_tensor(new_cache_dim);
        req.value_cache[i]->resize_tensor(new_cache_dim);
      }
      event.was_generation_phase = false;
      event.generated_tokens = 0;
      event.current_length = req.current_length;
      req.spec_phase = LangSpecPhase::DRAFT_ROUND_START;
      break;
    }
    case LangTaskType::DRAFT: {
      // Draft wrote one speculative token into KV cache; accept-or-roll-back
      // happens during VERIFY. Keep KV growing until VERIFY decides.
      uint32_t projected_len = req.current_length + req.drafted_in_round + 1;
      std::vector<uint32_t> new_cache_dim{projected_len, _cache_dim};
      for (uint32_t i = 0; i < _num_sim_layers; i++) {
        req.key_cache[i]->resize_tensor(new_cache_dim);
        req.value_cache[i]->resize_tensor(new_cache_dim);
      }
      req.drafted_in_round += 1;
      event.was_generation_phase = true;
      event.generated_tokens = 1;
      event.current_length = req.current_length;  // not committed yet
      if (req.drafted_in_round >= req.planned_draft_length) {
        req.spec_phase = LangSpecPhase::AWAIT_VERIFY;
        // B2.3 — feed TVC PDCT with cycles spent drafting the whole round.
        if (_ahasd != nullptr && _ahasd->config().enable_tvc) {
          uint64_t elapsed = (_cycle > meta.issue_cycle)
                                 ? (_cycle - meta.issue_cycle)
                                 : 0;
          // meta.issue_cycle is the *last* draft of the round. We use its
          // elapsed cycles as a per-draft sample; PDCT then computes
          // cycles/draft_length downstream. Pass draft_length=1 (one forward).
          _ahasd->record_draft_batch(std::max<uint64_t>(1, elapsed), 1);
        }
      } else {
        req.spec_phase = LangSpecPhase::DRAFTING;
      }
      break;
    }
    case LangTaskType::VERIFY: {
      uint32_t k = std::max<uint32_t>(1u, meta.draft_length_at_issue);
      uint32_t accepted = std::min<uint32_t>(
          k, sample_accepted_length(req, k));
      event.accepted_length = accepted;
      event.was_generation_phase = true;
      event.generated_tokens = accepted;
      apply_verify_result(req, k, accepted);
      event.current_length = req.current_length;
      // B2.3 — feed EDC + TVC the verify outcome.
      if (_ahasd != nullptr) {
        uint64_t verify_cycles = (_cycle > meta.issue_cycle)
                                     ? (_cycle - meta.issue_cycle)
                                     : 0;
        _ahasd->record_verify_result(accepted == k, k, accepted,
                                      std::max<uint64_t>(1, verify_cycles),
                                      req.current_length);
      }
      if (req.spec_phase == LangSpecPhase::DONE) {
        _last_rank_mode.erase(req.request_id);
        _pre_verified_in_round.erase(req.request_id);
        _active_requests.erase(req.request_id);
      }
      break;
    }
    case LangTaskType::PRE_VERIFY: {
      // PRE_VERIFY resolves a prefix of the round's draft; the remaining
      // drafts still need a full VERIFY. We DO NOT commit here — we only
      // feed TVC/EDC the outcome so their cycle tables / PHT counters see
      // the intermediate evidence. spec_phase stays AWAIT_VERIFY so the
      // next try_issue_one_task() still issues the VERIFY.
      uint32_t pv_k = std::max<uint32_t>(1u, meta.draft_length_at_issue);
      uint32_t pv_accepted = std::min<uint32_t>(
          pv_k, sample_accepted_length(req, pv_k));
      event.accepted_length = pv_accepted;
      event.was_generation_phase = true;
      event.generated_tokens = pv_accepted;
      event.current_length = req.current_length;
      if (_ahasd != nullptr) {
        uint64_t pv_cycles = (_cycle > meta.issue_cycle)
                                  ? (_cycle - meta.issue_cycle)
                                  : 0;
        _ahasd->record_pre_verify(std::max<uint64_t>(1, pv_cycles), pv_k);
        _ahasd->record_verify_result(pv_accepted == pv_k, pv_k, pv_accepted,
                                      std::max<uint64_t>(1, pv_cycles),
                                      req.current_length);
      }
      break;
    }
    case LangTaskType::AUTOREG:
    default:
      // Not used in the B2.3 spec path; treat as a no-op update.
      event.was_generation_phase = true;
      event.generated_tokens = 0;
      event.current_length = req.current_length;
      break;
  }

  _last_finished_events.push_back(event);
  // Release the request<->model tie.
  auto it_rim = _requests_in_model.find(model_id);
  if (it_rim != _requests_in_model.end()) {
    _requests_in_model.erase(it_rim);
  }
  if (_active_requests.count(meta.request_id) && !_active_requests[meta.request_id]->running) {
    // nothing to do; cycle() will pick up next step
  }
  if (_active_requests.count(meta.request_id)) {
    _active_requests[meta.request_id]->running = false;
  }
}
