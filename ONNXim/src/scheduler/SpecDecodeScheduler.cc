// B2.1 — Speculative decoding scheduler implementation.
//
// Scope for this milestone:
//   * Drive the DRAFT (k times) -> VERIFY (1 time) cadence on a pair of
//     LanguageModel objects (DLM + TLM).
//   * Route model-finish callbacks back to the request that issued the model
//     and update its per-round state.
//   * Provide extension points (pick_draft_length / sample_accepted_length)
//     that B2.3 (EDC coupling) and B2.5 (synthetic acceptance) will fill in.
//
// Intentionally NOT in scope yet:
//   * Real KV-cache rollback beyond a length truncation (the resize below is
//     a placeholder — real rollback including dirty-region management lands
//     in B2.3 together with AHASD's SSRC path).
//   * PRE_VERIFY tasks: the state machine reserves the enum value and will be
//     activated by TVC in B2.3.
//   * Acceptance driven by entropy: pick_draft_length() returns the
//     configured max_draft_length for now.

#include "SpecDecodeScheduler.h"

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

uint32_t SpecDecodeScheduler::pick_draft_length(const LangRequest& req) {
  // B2.3 will override this with EDC::decide(draft_length_limit, entropy_hist).
  uint32_t remaining =
      req.target_length > req.current_length ? req.target_length - req.current_length : 0u;
  uint32_t k = std::min<uint32_t>(_default_draft_length, std::max<uint32_t>(1u, remaining));
  return std::min<uint32_t>(k, _max_draft_length);
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
  // Only one outstanding model per request at a time to keep accounting simple;
  // B2.3 will lift this restriction once EDC can overlap DLM/TLM queues.
  if (_requests_in_model.find(req.request_id) != _requests_in_model.end()) {
    return false;  // already has an in-flight model for this request
  }

  switch (req.spec_phase) {
    case LangSpecPhase::PROMPT_PENDING: {
      // Target-model prefill; emit one PROMPT task.
      LanguageModel& model = _target_attached ? *_target_model : *_language_model;
      auto infer_model = build_model(model, req, LangTaskType::PROMPT, req.prompt_length);
      uint32_t mid = infer_model->get_id();
      _model_meta[mid] = {req.request_id, LangTaskType::PROMPT,
                          _target_attached ? "target" : "single",
                          0, 0};
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
      // fallthrough: issue first draft immediately
      [[fallthrough]];
    }
    case LangSpecPhase::DRAFTING: {
      LanguageModel& model = *_language_model;  // DLM
      auto infer_model = build_model(model, req, LangTaskType::DRAFT, 1u);
      uint32_t mid = infer_model->get_id();
      _model_meta[mid] = {req.request_id, LangTaskType::DRAFT, "draft",
                          req.planned_draft_length, req.spec_round};
      req.running = true;
      _requests_in_model[mid].push_back(req.request_id);
      _model_queue.push(std::move(infer_model));
      return true;
    }
    case LangSpecPhase::AWAIT_VERIFY: {
      LanguageModel& model = _target_attached ? *_target_model : *_language_model;
      uint32_t k = std::max<uint32_t>(1u, req.planned_draft_length);
      auto infer_model = build_model(model, req, LangTaskType::VERIFY, k);
      uint32_t mid = infer_model->get_id();
      _model_meta[mid] = {req.request_id, LangTaskType::VERIFY,
                          _target_attached ? "target" : "single",
                          k, req.spec_round};
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
      if (req.spec_phase == LangSpecPhase::DONE) {
        _active_requests.erase(req.request_id);
      }
      break;
    }
    case LangTaskType::PRE_VERIFY:
    case LangTaskType::AUTOREG:
    default:
      // Not used in B2.1 spec path; treat as a no-op update.
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
