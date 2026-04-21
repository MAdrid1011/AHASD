#ifndef SPEC_DECODE_SCHEDULER_H
#define SPEC_DECODE_SCHEDULER_H
// B2.1 — Speculative decoding scheduler.
//
// Extends LangScheduler to orchestrate a two-model speculative decoding loop:
//   for each request:
//     PROMPT (target prefill)
//     loop:
//       DRAFT x k   (draft model, autoregressive, k == planned_draft_length)
//       VERIFY x 1  (target model, batched over k)
//       commit accepted_length <= k, rollback KV cache if needed
//
// This file only implements the *scheduling* side of the loop. EDC/TVC cycle
// coupling (B2.3) and the synthetic acceptance model (B2.5) are wired in via
// virtual hooks (`pick_draft_length`, `sample_accepted_length`) so that later
// milestones can override them without touching this skeleton.

#include "LanguageScheduler.h"

class SpecDecodeScheduler : public LangScheduler {
 public:
  SpecDecodeScheduler(std::string name, std::string path,
                      std::unique_ptr<LanguageModel> draft_model,
                      SimulationConfig config,
                      json scheduler_config);
  ~SpecDecodeScheduler() override = default;

  bool attach_target_model(std::unique_ptr<LanguageModel> target_model,
                           const json& target_info) override;
  bool is_speculative() const override { return true; }

  void cycle() override;
  std::unique_ptr<Model> pop_model() override;
  void finish_model(uint32_t model_id) override;
  bool busy() override;
  uint64_t get_kv_memory_size() override;

 protected:
  // Hooks for later milestones.
  //   B2.3 will override pick_draft_length() with EDC's decision.
  //   B2.5 will override sample_accepted_length() with the synthetic model.
  virtual uint32_t pick_draft_length(const LangRequest& req);
  virtual uint32_t sample_accepted_length(const LangRequest& req, uint32_t draft_length);

 private:
  struct ModelMeta {
    uint32_t request_id = 0;
    LangTaskType task_type = LangTaskType::AUTOREG;
    const char* role = "single";
    uint32_t draft_length_at_issue = 0;
    uint32_t verify_round = 0;
  };

  std::unique_ptr<LanguageModel> _target_model;
  json _target_info;
  bool _target_attached = false;

  // Bookkeeping for issued models so finish_model can route back properly.
  std::map<uint32_t /*model_id*/, ModelMeta> _model_meta;

  uint32_t _max_draft_length = 1;
  uint32_t _default_draft_length = 1;

  // Step the state machine for one request; returns true if a model was issued.
  bool try_issue_one_task(LangRequest& req);

  // Build a single-request model (draft or target) with seq_length==seq_length
  // and a "virtual" context_length rebase so KV layout stays self-consistent
  // across speculative rounds.
  std::unique_ptr<Model> build_model(LanguageModel& model, LangRequest& req,
                                     LangTaskType task_type,
                                     uint32_t seq_length);

  void apply_verify_result(LangRequest& req, uint32_t draft_length,
                           uint32_t accepted_length);
};

#endif
