#ifndef LANGUAGE_SCHEDULER_H
#define LANGUAGE_SCHEDULER_H
#include <string>
#include <vector>

#include "../Common.h"
#include "../models/LanguageModel.h"

// B2.1: task types for speculative decoding orchestration.
// AUTOREG retains the legacy single-model path (prefill + auto-regressive
// decoding of one token at a time). The remaining tags drive the two-model
// speculative flow handled by SpecDecodeScheduler.
enum class LangTaskType {
  AUTOREG = 0,       // legacy single-model step (prefill or 1-token gen)
  PROMPT = 1,        // target-model prefill on an incoming request
  DRAFT = 2,         // draft-model single-token forward (one of k in a round)
  VERIFY = 3,        // target-model batched verify of k draft tokens
  PRE_VERIFY = 4     // target-model speculative early verify (TVC)
};

inline const char* lang_task_type_name(LangTaskType t) {
  switch (t) {
    case LangTaskType::AUTOREG: return "autoreg";
    case LangTaskType::PROMPT: return "prompt";
    case LangTaskType::DRAFT: return "draft";
    case LangTaskType::VERIFY: return "verify";
    case LangTaskType::PRE_VERIFY: return "pre_verify";
  }
  return "unknown";
}

// Phase inside the speculative decoding state machine (per request).
enum class LangSpecPhase {
  PROMPT_PENDING = 0,      // trace said the request is here but prefill not done
  DRAFT_ROUND_START = 1,   // ready to start another (EDC-decided) draft round
  DRAFTING = 2,            // issuing the k draft tasks of current round
  AWAIT_VERIFY = 3,        // k drafts done, waiting for verify to come back
  DONE = 4
};

struct LangRequest {
  uint32_t request_id;
  bool running;
  bool gen_phase;
  uint64_t request_time;
  uint64_t start_time;
  uint64_t finish_time;
  uint32_t prompt_length;
  uint32_t current_length;
  uint32_t target_length;
  std::vector<std::unique_ptr<Tensor>> key_cache;
  std::vector<std::unique_ptr<Tensor>> value_cache;
  // --- B2.1: speculative decoding metadata (ignored by legacy schedulers) ---
  LangSpecPhase spec_phase = LangSpecPhase::PROMPT_PENDING;
  uint32_t spec_round = 0;
  uint32_t planned_draft_length = 0;   // set at DRAFT_ROUND_START by EDC (or k_max)
  uint32_t drafted_in_round = 0;       // drafted so far this round
  uint32_t verify_round_id = 0;        // to tag which verify model finishes which round
  LangTaskType last_task_type = LangTaskType::AUTOREG;
};

struct LangStepEvent {
  uint32_t request_id;
  uint32_t prompt_length;
  uint32_t previous_length;
  uint32_t current_length;
  uint32_t target_length;
  uint32_t generated_tokens;
  bool was_generation_phase;
  // --- B2.1: speculative decoding annotations (default values preserve
  //     legacy behaviour of sidecar / trace consumers). ---
  LangTaskType task_type = LangTaskType::AUTOREG;
  const char* model_role = "single";   // "draft" / "target" / "single"
  uint32_t draft_length = 0;           // planned k for this VERIFY event
  uint32_t accepted_length = 0;        // tokens accepted (0 for non-VERIFY)
  uint32_t spec_round = 0;
  float avg_entropy = 0.0f;            // populated when EDC sampling exposed
};

class LangScheduler {
  public:
    static std::unique_ptr<LangScheduler> create(std::string name, std::string path, 
                                                  std::unique_ptr<LanguageModel> model,
                                                  SimulationConfig config,
                                                  json scheduler_config);
    LangScheduler(std::string name, std::string path, 
                  std::unique_ptr<LanguageModel> model,
                  SimulationConfig config,
                  json scheduler_config);
    virtual ~LangScheduler() = default;
    bool can_schedule_model();
    virtual std::unique_ptr<Model> pop_model();
    virtual void finish_model(uint32_t model_id);
    std::vector<LangStepEvent> consume_finished_events();
    virtual void cycle();
    virtual bool busy();
    virtual uint64_t get_kv_memory_size();
    // B2.1: attach a target (TLM) model for speculative decoding. Default base
    // class is single-model and rejects the attach; SpecDecodeScheduler
    // overrides it to accept.
    virtual bool attach_target_model(std::unique_ptr<LanguageModel> target_model,
                                     const json& target_info);
    virtual bool is_speculative() const { return false; }
    const std::string& get_name() const { return _name; }
  protected:
    SimulationConfig _config;
    json _scheduler_config;
    std::string _name;
    std::unique_ptr<LanguageModel> _language_model;
    std::queue<std::unique_ptr<LangRequest>> _request_queue;
    std::map<uint32_t, std::unique_ptr<LangRequest>> _active_requests;
    std::map<uint32_t, std::vector<uint32_t>> _requests_in_model;
    std::queue<std::unique_ptr<Model>> _model_queue;
    std::vector<LangStepEvent> _last_finished_events;
    uint64_t _cycle;

    uint32_t _num_layers;
    uint32_t _num_sim_layers;
    uint32_t _num_attention_heads;
    uint32_t _num_kv_heads;
    uint32_t _hidden_size;
    uint32_t _cache_dim;
    uint32_t _max_seq_length;
    uint32_t _max_batch_size; 
    bool _run_single_layer;
    bool _check_mem_size;



    std::vector<uint32_t> _max_dims;

    void parse_request_trace(std::string trace_path);
    void init_request(std::unique_ptr<LangRequest>& request);
    void init_inputs_and_model();
};

#endif
