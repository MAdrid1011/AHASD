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
#include "../SyntheticAcceptanceModel.h"

// B2.3: forward declarations so we do not leak AHASD / PIM headers via the
// scheduler interface (Simulator.cc injects them via attach_ahasd()).
namespace AHASD { class AHASDIntegration; class SSRCCoordinator; }
class PIMBackend;

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

  // B2.3 — late binding for AHASD + PIM. Simulator calls this after
  // constructing the scheduler (both pointers may be null in the legacy
  // build where AHASD is disabled; callers must be null-safe).
  void attach_ahasd(AHASD::AHASDIntegration* ahasd, PIMBackend* pim);

  // F1 — late binding for SSRC. Simulator calls this alongside attach_ahasd.
  // nullptr is valid (SSRC coordinator present but disabled is also OK;
  // `is_enabled()` guards every code path inside the scheduler).
  void attach_ssrc(AHASD::SSRCCoordinator* ssrc);

  void cycle() override;
  std::unique_ptr<Model> pop_model() override;
  void finish_model(uint32_t model_id) override;
  bool busy() override;
  uint64_t get_kv_memory_size() override;

  // B2.5 — end-of-simulation summary of synthetic acceptance outcomes.
  // Simulator calls this once run completes.
  void print_acceptance_stats() const;

 protected:
  // Hooks for later milestones.
  //   B2.3 overrides pick_draft_length() with EDC's decision when AHASD is
  //     attached; the default implementation returns _default_draft_length.
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
    uint64_t issue_cycle = 0;  // B2.3 — elapsed cycles fed into TVC tables.
  };

  std::unique_ptr<LanguageModel> _target_model;
  json _target_info;
  bool _target_attached = false;

  // Bookkeeping for issued models so finish_model can route back properly.
  std::map<uint32_t /*model_id*/, ModelMeta> _model_meta;

  uint32_t _max_draft_length = 1;
  uint32_t _default_draft_length = 1;

  // B2.3 — non-owning pointers injected by Simulator::attach_ahasd().
  AHASD::AHASDIntegration* _ahasd = nullptr;
  PIMBackend* _pim = nullptr;
  // F1 — non-owning pointer injected by Simulator::attach_ssrc().
  AHASD::SSRCCoordinator* _ssrc = nullptr;
  // Per-request: which (spec_round) we most recently asked SSRC to defer.
  // Used to invoke on_round_verified with the right round even when the
  // scheduler has already advanced spec_phase for the next round.
  std::map<uint32_t, uint32_t> _ssrc_deferred_round;

  // Per-request bookkeeping for B2.3 TVC pre-verify gating.
  std::map<uint32_t, uint32_t> _pre_verified_in_round;  // request_id -> round idx last pre-verified
  // Per-request rank mode tracker (0 = DLM bank, 1 = TLM bank); we only
  // request a GTSU switch when the desired mode differs. Separate per
  // request so co-scheduled requests do not thrash each other.
  std::map<uint32_t, uint32_t> _last_rank_mode;

  // Synthetic entropy hint for EDC (B2.3). Real entropy arrives once the
  // synthetic acceptance model lands in B2.5.
  float compute_entropy_hint(const LangRequest& req) const;

  // B2.5 — synthetic acceptance model. Owned by the scheduler so mode /
  // coeffs are scoped to the speculative path; load_from_config is called
  // once in the constructor.
  ahasd_accept::SyntheticAcceptanceModel _accept_model;

  // B2.5 — smoke + B2.7 consumption: tally of how many rounds the EDC
  // picked each (k, accepted_length) pair so the end-of-simulation log
  // can show acceptance distribution without rereading the event stream.
  uint64_t _accept_samples = 0;
  uint64_t _accept_sum     = 0;
  uint64_t _accept_k_sum   = 0;

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
