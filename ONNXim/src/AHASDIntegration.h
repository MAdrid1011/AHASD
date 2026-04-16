#pragma once

#include "Common.h"
#include "async_queue/AsyncQueue.h"
#include "async_queue/EDC.h"
#include "async_queue/TVC.h"
#include <algorithm>
#include <memory>
#include <fstream>
#include <string>
#include <unordered_map>

// AHASD Integration Layer
// Coordinates NPU-side and PIM-side operations for speculative decoding

namespace AHASD {

enum class SSRCDecision {
    RESIDENT,
    DEFERRED,
    PREFETCHED,
    RECLAIMED
};

struct SSRCBatchState {
    uint32_t draft_length;
    uint64_t state_bytes;
    bool resident;
    bool trace_identity_valid;
    SSRCDecision decision;
    float queue_pressure;
    float residency_pressure;
    float tvc_slack_proxy;

    SSRCBatchState()
        : draft_length(0), state_bytes(0), resident(false),
          trace_identity_valid(false), decision(SSRCDecision::DEFERRED),
          queue_pressure(0.0f), residency_pressure(0.0f),
          tvc_slack_proxy(0.0f) {}
};

struct AHASDConfig {
    bool enable_edc;  // Enable Entropy-History-Aware Drafting Control
    bool enable_tvc;  // Enable Time-Aware Pre-Verification Control
    bool enable_aau;  // Enable Attention Algorithm Unit
    bool enable_ssrc; // Enable Speculative State Residency Control
    bool enable_ssrc_proxy; // Use a trace-level proxy when draft path is unavailable
    bool enable_ssrc_trace; // Use language-scheduler events as draft evidence
    float pim_freq_mhz;
    float npu_freq_mhz;
    uint32_t max_draft_length;
    uint32_t min_preverify_length;
    uint64_t ssrc_state_bytes_per_token;
    uint64_t ssrc_resident_limit_bytes;
    float ssrc_confidence_threshold;
    uint32_t dram_req_size;
    uint32_t dram_latency;
    
    AHASDConfig() 
        : enable_edc(true), enable_tvc(true), enable_aau(true),
          enable_ssrc(false), enable_ssrc_proxy(false), enable_ssrc_trace(false),
          pim_freq_mhz(800.0f), npu_freq_mhz(1000.0f),
          max_draft_length(16), min_preverify_length(2),
          ssrc_state_bytes_per_token(524288),
          ssrc_resident_limit_bytes(33554432),
          ssrc_confidence_threshold(0.55f),
          dram_req_size(32), dram_latency(1) {}
};

class AHASDIntegration {
private:
    AHASDConfig config_;
    
    // Core components
    std::unique_ptr<AsyncQueueManager> queue_manager_;
    std::unique_ptr<EDC> edc_;
    std::unique_ptr<TVC> tvc_;
    
    // State tracking
    uint32_t current_kv_length_;
    uint32_t current_batch_id_;
    bool npu_busy_;
    bool pim_busy_;
    
    // Performance statistics
    uint64_t total_drafts_generated_;
    uint64_t total_drafts_accepted_;
    uint64_t total_draft_tokens_generated_;
    uint64_t total_preverifications_;
    uint64_t total_npu_idle_cycles_;
    uint64_t total_pim_idle_cycles_;
    double total_draft_entropy_;

    // SSRC proxy/accounting statistics
    std::unordered_map<uint32_t, SSRCBatchState> ssrc_batches_;
    uint64_t ssrc_baseline_materialized_bytes_;
    uint64_t ssrc_actual_materialized_bytes_;
    uint64_t ssrc_reclaimed_bytes_;
    uint64_t ssrc_resident_bytes_;
    uint64_t ssrc_peak_resident_bytes_;
    uint64_t ssrc_committed_bytes_;
    uint64_t ssrc_deferred_batches_;
    uint64_t ssrc_prefetched_batches_;
    uint64_t ssrc_resident_batches_;
    uint64_t ssrc_reclaimed_batches_;
    uint64_t ssrc_trace_identity_batches_;
    uint64_t ssrc_trace_identity_verified_batches_;
    uint64_t ssrc_trace_semantic_resident_batches_;
    uint64_t ssrc_trace_semantic_deferred_batches_;
    uint64_t ssrc_trace_semantic_prefetched_batches_;
    uint64_t ssrc_trace_semantic_reclaimed_batches_;
    uint64_t ssrc_trace_semantic_accepted_bytes_;
    double ssrc_trace_semantic_queue_pressure_sum_;
    double ssrc_trace_semantic_residency_pressure_sum_;
    double ssrc_trace_semantic_tvc_slack_sum_;
    
    // Timing
    uint64_t last_verification_start_;
    uint64_t last_drafting_start_;
    
    // Logging
    std::ofstream trace_file_;
    bool enable_tracing_;

    float clamp01(float value) const {
        return std::max(0.0f, std::min(1.0f, value));
    }

    uint64_t estimate_state_bytes(uint32_t draft_length) const {
        return static_cast<uint64_t>(draft_length) * config_.ssrc_state_bytes_per_token;
    }

    std::string decision_to_string(SSRCDecision decision) const {
        switch (decision) {
            case SSRCDecision::RESIDENT:
                return "resident";
            case SSRCDecision::DEFERRED:
                return "deferred";
            case SSRCDecision::PREFETCHED:
                return "prefetched";
            case SSRCDecision::RECLAIMED:
                return "reclaimed";
        }
        return "unknown";
    }

    void record_trace_semantic_submit(const SSRCBatchState& state) {
        if (!state.trace_identity_valid) {
            return;
        }

        ssrc_trace_semantic_queue_pressure_sum_ += state.queue_pressure;
        ssrc_trace_semantic_residency_pressure_sum_ += state.residency_pressure;
        ssrc_trace_semantic_tvc_slack_sum_ += state.tvc_slack_proxy;

        switch (state.decision) {
            case SSRCDecision::RESIDENT:
                ssrc_trace_semantic_resident_batches_++;
                break;
            case SSRCDecision::DEFERRED:
                ssrc_trace_semantic_deferred_batches_++;
                break;
            case SSRCDecision::PREFETCHED:
                ssrc_trace_semantic_prefetched_batches_++;
                break;
            case SSRCDecision::RECLAIMED:
                ssrc_trace_semantic_reclaimed_batches_++;
                break;
        }
    }

    void account_ssrc_submit(const DraftBatch& batch, float avg_entropy) {
        if (!config_.enable_ssrc && !config_.enable_ssrc_proxy &&
            !config_.enable_ssrc_trace) {
            return;
        }

        uint64_t state_bytes = estimate_state_bytes(batch.draft_length);
        ssrc_baseline_materialized_bytes_ += state_bytes;
        float queue_pressure = clamp01(static_cast<float>(queue_manager_->get_unverified_count()) /
                                       std::max(1u, config_.max_draft_length));
        float residency_pressure = clamp01(
            static_cast<float>(ssrc_resident_bytes_ + state_bytes) /
            static_cast<float>(std::max<uint64_t>(1ULL, config_.ssrc_resident_limit_bytes)));
        float tvc_slack_proxy = config_.enable_tvc ? clamp01(1.0f - queue_pressure) : 0.0f;

        if (!config_.enable_ssrc) {
            SSRCBatchState state;
            state.draft_length = batch.draft_length;
            state.state_bytes = state_bytes;
            state.decision = SSRCDecision::RESIDENT;
            state.resident = true;
            state.trace_identity_valid = batch.trace_identity_valid;
            state.queue_pressure = queue_pressure;
            state.residency_pressure = residency_pressure;
            state.tvc_slack_proxy = tvc_slack_proxy;
            ssrc_actual_materialized_bytes_ += state_bytes;
            ssrc_resident_bytes_ += state_bytes;
            ssrc_peak_resident_bytes_ = std::max(ssrc_peak_resident_bytes_,
                                                 ssrc_resident_bytes_);
            ssrc_resident_batches_++;
            ssrc_batches_[batch.batch_id] = state;
            record_trace_semantic_submit(state);
            return;
        }

        float confidence = clamp01(1.0f - (avg_entropy / 10.0f));

        SSRCDecision decision = SSRCDecision::RESIDENT;
        if (residency_pressure > 0.95f) {
            decision = SSRCDecision::RECLAIMED;
        } else if (confidence < config_.ssrc_confidence_threshold ||
                   residency_pressure > 0.80f) {
            decision = SSRCDecision::DEFERRED;
        } else if (tvc_slack_proxy > 0.50f) {
            decision = SSRCDecision::PREFETCHED;
        }

        SSRCBatchState state;
        state.draft_length = batch.draft_length;
        state.state_bytes = state_bytes;
        state.decision = decision;
        state.resident = (decision == SSRCDecision::RESIDENT ||
                          decision == SSRCDecision::PREFETCHED);
        state.trace_identity_valid = batch.trace_identity_valid;
        state.queue_pressure = queue_pressure;
        state.residency_pressure = residency_pressure;
        state.tvc_slack_proxy = tvc_slack_proxy;

        if (state.resident) {
            ssrc_actual_materialized_bytes_ += state_bytes;
            ssrc_resident_bytes_ += state_bytes;
            ssrc_peak_resident_bytes_ = std::max(ssrc_peak_resident_bytes_,
                                                 ssrc_resident_bytes_);
            if (decision == SSRCDecision::PREFETCHED) {
                ssrc_prefetched_batches_++;
            } else {
                ssrc_resident_batches_++;
            }
        } else if (decision == SSRCDecision::RECLAIMED) {
            ssrc_reclaimed_batches_++;
        } else {
            ssrc_deferred_batches_++;
        }

        ssrc_batches_[batch.batch_id] = state;
        record_trace_semantic_submit(state);

        if (enable_tracing_) {
            trace_file_ << batch.timestamp << ",ssrc_decision," << batch.batch_id
                       << "," << batch.draft_length << "," << avg_entropy
                       << "," << decision_to_string(decision) << "\n";
        }
    }

    void account_ssrc_verify(uint32_t batch_id, uint32_t accepted_length) {
        if (!config_.enable_ssrc && !config_.enable_ssrc_proxy &&
            !config_.enable_ssrc_trace) {
            return;
        }

        auto it = ssrc_batches_.find(batch_id);
        if (it == ssrc_batches_.end()) {
            return;
        }

        const SSRCBatchState state = it->second;
        uint32_t accepted = std::min(accepted_length, state.draft_length);
        uint64_t accepted_bytes = estimate_state_bytes(accepted);
        if (state.trace_identity_valid) {
            ssrc_trace_semantic_accepted_bytes_ += accepted_bytes;
        }

        if (state.resident) {
            ssrc_resident_bytes_ = (ssrc_resident_bytes_ > state.state_bytes)
                ? (ssrc_resident_bytes_ - state.state_bytes) : 0;
            if (state.state_bytes > accepted_bytes) {
                ssrc_reclaimed_bytes_ += (state.state_bytes - accepted_bytes);
            }
        } else if (accepted_bytes > 0) {
            // Deferred materialization pays only for the accepted prefix.
            ssrc_actual_materialized_bytes_ += accepted_bytes;
        }

        ssrc_committed_bytes_ += accepted_bytes;
        ssrc_batches_.erase(it);
    }

public:
    AHASDIntegration(const AHASDConfig& config = AHASDConfig())
        : config_(config), current_kv_length_(0), current_batch_id_(0),
          npu_busy_(false), pim_busy_(false),
          total_drafts_generated_(0), total_drafts_accepted_(0),
          total_draft_tokens_generated_(0),
          total_preverifications_(0), total_npu_idle_cycles_(0),
          total_pim_idle_cycles_(0), total_draft_entropy_(0.0),
          ssrc_baseline_materialized_bytes_(0), ssrc_actual_materialized_bytes_(0),
          ssrc_reclaimed_bytes_(0), ssrc_resident_bytes_(0),
          ssrc_peak_resident_bytes_(0), ssrc_committed_bytes_(0),
          ssrc_deferred_batches_(0), ssrc_prefetched_batches_(0),
          ssrc_resident_batches_(0), ssrc_reclaimed_batches_(0),
          ssrc_trace_identity_batches_(0),
          ssrc_trace_identity_verified_batches_(0),
          ssrc_trace_semantic_resident_batches_(0),
          ssrc_trace_semantic_deferred_batches_(0),
          ssrc_trace_semantic_prefetched_batches_(0),
          ssrc_trace_semantic_reclaimed_batches_(0),
          ssrc_trace_semantic_accepted_bytes_(0),
          ssrc_trace_semantic_queue_pressure_sum_(0.0),
          ssrc_trace_semantic_residency_pressure_sum_(0.0),
          ssrc_trace_semantic_tvc_slack_sum_(0.0),
          last_verification_start_(0), last_drafting_start_(0),
          enable_tracing_(false) {
        
        queue_manager_ = std::make_unique<AsyncQueueManager>();
        
        if (config_.enable_edc) {
            edc_ = std::make_unique<EDC>();
        }
        
        if (config_.enable_tvc) {
            tvc_ = std::make_unique<TVC>(config_.pim_freq_mhz, config_.npu_freq_mhz);
        }
    }
    
    ~AHASDIntegration() {
        if (trace_file_.is_open()) {
            trace_file_.close();
        }
    }
    
    // Enable trace logging
    void enable_trace_logging(const std::string& filename) {
        trace_file_.open(filename);
        if (trace_file_.is_open()) {
            enable_tracing_ = true;
            trace_file_ << "cycle,event,batch_id,length,entropy,decision\n";
        }
    }
    
    // PIM-side: Generate draft
    bool submit_draft_batch(const std::vector<int32_t>& tokens,
                           const std::vector<float>& entropies,
                           uint64_t cycle,
                           bool trace_identity_valid = false,
                           uint32_t trace_request_id = 0,
                           uint32_t trace_previous_length = 0,
                           uint32_t trace_current_length = 0,
                           uint32_t trace_target_length = 0) {
        DraftBatch batch;
        batch.batch_id = current_batch_id_++;
        batch.draft_length = tokens.size();
        batch.token_ids = tokens;
        batch.entropy_values = entropies;
        batch.timestamp = cycle;
        batch.verified = false;
        batch.accepted = false;
        batch.trace_identity_valid = trace_identity_valid;
        batch.trace_request_id = trace_request_id;
        batch.trace_previous_length = trace_previous_length;
        batch.trace_current_length = trace_current_length;
        batch.trace_target_length = trace_target_length;
        
        // Calculate average entropy
        float avg_entropy = 0.0f;
        for (float e : entropies) {
            avg_entropy += e;
        }
        if (!entropies.empty()) {
            avg_entropy /= entropies.size();
        }
        total_draft_entropy_ += avg_entropy;
        
        bool success = queue_manager_->push_draft(batch);
        if (success) {
            total_drafts_generated_++;
            total_draft_tokens_generated_ += batch.draft_length;
            if (batch.trace_identity_valid) {
                ssrc_trace_identity_batches_++;
            }
            account_ssrc_submit(batch, avg_entropy);
            
            if (enable_tracing_) {
                trace_file_ << cycle << ",draft_generated," << batch.batch_id 
                           << "," << batch.draft_length << "," << avg_entropy 
                           << ",NA\n";
            }
        }
        
        return success;
    }

    void submit_proxy_draft(uint64_t cycle) {
        if (!config_.enable_ssrc_proxy) {
            return;
        }

        uint32_t span = std::max(1u, std::min(config_.max_draft_length, 8u));
        uint32_t draft_length = 1 + (current_batch_id_ % span);
        float avg_entropy = 1.5f + static_cast<float>(current_batch_id_ % 5) * 0.7f;

        if (!should_continue_drafting(avg_entropy) &&
            queue_manager_->get_unverified_count() >= config_.min_preverify_length) {
            return;
        }

        std::vector<int32_t> tokens;
        std::vector<float> entropies;
        tokens.reserve(draft_length);
        entropies.reserve(draft_length);
        for (uint32_t i = 0; i < draft_length; i++) {
            tokens.push_back(static_cast<int32_t>(current_batch_id_ * 100 + i));
            entropies.push_back(avg_entropy);
        }

        if (submit_draft_batch(tokens, entropies, cycle)) {
            record_pim_drafting(
                std::max<uint64_t>(1ULL, static_cast<uint64_t>(draft_length) * 8ULL),
                draft_length);
        }
    }

    void submit_proxy_verification(uint64_t cycle) {
        if (!config_.enable_ssrc_proxy) {
            return;
        }

        DraftBatch batch;
        if (!get_next_draft(batch)) {
            return;
        }

        uint32_t rejected = (batch.batch_id % 3 == 0 && batch.draft_length > 1) ? 1 : 0;
        uint32_t accepted_length = batch.draft_length - rejected;
        bool fully_accepted = (accepted_length == batch.draft_length);
        uint64_t verification_cycles = std::max<uint64_t>(
            1ULL, static_cast<uint64_t>(batch.draft_length) * 12ULL);

        start_npu_verification(cycle);
        submit_verification_result(batch.batch_id, accepted_length, fully_accepted,
                                   verification_cycles,
                                   current_kv_length_ + accepted_length);
        finish_npu_verification();
    }

    bool submit_trace_verified_draft(uint32_t draft_length,
                                     uint32_t accepted_length,
                                     uint32_t request_id,
                                     uint32_t previous_length,
                                     uint32_t current_length,
                                     uint32_t target_length,
                                     uint64_t cycle,
                                     float avg_entropy) {
        if (!config_.enable_ssrc_trace || draft_length == 0) {
            return false;
        }

        uint32_t bounded_length =
            std::max(1u, std::min(draft_length, config_.max_draft_length));
        uint32_t accepted = std::min(accepted_length, bounded_length);
        std::vector<int32_t> tokens;
        std::vector<float> entropies;
        tokens.reserve(bounded_length);
        entropies.reserve(bounded_length);
        uint32_t seed = current_batch_id_;
        for (uint32_t i = 0; i < bounded_length; i++) {
            tokens.push_back(static_cast<int32_t>(seed * 1000 + i));
            entropies.push_back(avg_entropy);
        }

        if (!submit_draft_batch(tokens, entropies, cycle, true, request_id,
                                previous_length, current_length,
                                target_length)) {
            return false;
        }

        record_pim_drafting(
            std::max<uint64_t>(1ULL, static_cast<uint64_t>(bounded_length) * 8ULL),
            bounded_length);

        DraftBatch batch;
        if (!get_next_draft(batch)) {
            return false;
        }

        if (batch.trace_identity_valid) {
            ssrc_trace_identity_verified_batches_++;
        }
        bool fully_accepted = (accepted == batch.draft_length);
        uint64_t verification_cycles =
            std::max<uint64_t>(1ULL, static_cast<uint64_t>(batch.draft_length) * 12ULL);
        start_npu_verification(cycle);
        submit_verification_result(batch.batch_id, accepted, fully_accepted,
                                   verification_cycles, current_length);
        finish_npu_verification();
        return true;
    }
    
    // PIM-side: Check if should continue drafting
    bool should_continue_drafting(float avg_entropy) {
        if (!config_.enable_edc || edc_ == nullptr) {
            // Without EDC, always continue up to max length
            return queue_manager_->get_unverified_count() < config_.max_draft_length;
        }
        
        bool edc_decision = edc_->should_continue_drafting(avg_entropy);
        
        // Check TVC for pre-verification opportunity
        if (!edc_decision && config_.enable_tvc && tvc_ != nullptr) {
            uint32_t pending = queue_manager_->get_unverified_count();
            if (pending >= config_.min_preverify_length) {
                auto [should_preverify, length] = tvc_->should_insert_preverification(
                    current_kv_length_, pending);
                
                if (should_preverify) {
                    // Submit pre-verification request
                    PreVerifyRequest req;
                    req.verify_length = length;
                    req.timestamp = queue_manager_->get_pim_cycles();
                    req.urgent = false;
                    queue_manager_->push_preverify_request(req);
                    total_preverifications_++;
                    
                    if (enable_tracing_) {
                        trace_file_ << queue_manager_->get_pim_cycles() 
                                   << ",preverify_inserted,0," << length 
                                   << ",0.0,tvc\n";
                    }
                }
            }
        }
        
        return edc_decision;
    }
    
    // NPU-side: Pop draft for verification
    bool get_next_draft(DraftBatch& batch) {
        return queue_manager_->pop_draft(batch);
    }
    
    // NPU-side: Submit verification feedback
    void submit_verification_result(uint32_t batch_id, uint32_t accepted_length,
                                    bool fully_accepted, uint64_t verification_cycles,
                                    uint32_t kv_length) {
        FeedbackData feedback;
        feedback.batch_id = batch_id;
        feedback.accepted_length = accepted_length;
        feedback.fully_accepted = fully_accepted;
        feedback.verification_cycles = verification_cycles;
        feedback.kv_cache_length = kv_length;
        
        queue_manager_->push_feedback(feedback);
        
        if (fully_accepted || accepted_length > 0) {
            total_drafts_accepted_ += accepted_length;
        }

        account_ssrc_verify(batch_id, accepted_length);
        
        current_kv_length_ = kv_length;
        
        // Update EDC
        if (config_.enable_edc && edc_ != nullptr) {
            edc_->update_on_verification(fully_accepted, accepted_length);
        }
        
        // Update TVC
        if (config_.enable_tvc && tvc_ != nullptr) {
            tvc_->record_npu_verification(verification_cycles, kv_length);
        }
        
        if (enable_tracing_) {
            trace_file_ << queue_manager_->get_npu_cycles() 
                       << ",verification_result," << batch_id << "," 
                       << accepted_length << ",0.0," 
                       << (fully_accepted ? "full" : "partial") << "\n";
        }
    }
    
    // PIM-side: Check for feedback
    bool get_feedback(FeedbackData& feedback) {
        return queue_manager_->pop_feedback(feedback);
    }
    
    // PIM-side: Check for pre-verification request
    bool get_preverify_request(PreVerifyRequest& request) {
        return queue_manager_->pop_preverify_request(request);
    }
    
    // Record PIM drafting time
    void record_pim_drafting(uint64_t cycles, uint32_t draft_length) {
        if (config_.enable_tvc && tvc_ != nullptr) {
            tvc_->record_pim_drafting(cycles, draft_length);
        }
    }
    
    // Record PIM pre-verification time
    void record_pim_preverification(uint64_t cycles, uint32_t draft_length) {
        if (config_.enable_tvc && tvc_ != nullptr) {
            tvc_->record_pim_preverification(cycles, draft_length);
        }
    }
    
    // Start NPU verification task
    void start_npu_verification(uint64_t current_cycle) {
        last_verification_start_ = current_cycle;
        npu_busy_ = true;
        
        if (config_.enable_tvc && tvc_ != nullptr) {
            tvc_->start_npu_task(current_cycle);
        }
    }
    
    // Update NPU progress
    void update_npu_progress(uint64_t current_cycle) {
        if (config_.enable_tvc && tvc_ != nullptr && npu_busy_) {
            tvc_->update_npu_progress(current_cycle);
        }
    }
    
    // Finish NPU verification
    void finish_npu_verification() {
        npu_busy_ = false;
    }
    
    // Cycle updates
    void cycle_npu() {
        queue_manager_->increment_npu_cycle();
        if (!npu_busy_ && queue_manager_->has_pending_drafts()) {
            total_npu_idle_cycles_++;
        }
    }
    
    void cycle_pim() {
        queue_manager_->increment_pim_cycle();
        if (!pim_busy_) {
            total_pim_idle_cycles_++;
        }
    }
    
    // Status queries
    bool has_pending_drafts() const {
        return queue_manager_->has_pending_drafts();
    }
    
    size_t get_pending_draft_count() const {
        return queue_manager_->get_unverified_count();
    }
    
    bool is_npu_busy() const { return npu_busy_; }
    bool is_pim_busy() const { return pim_busy_; }
    
    void set_npu_busy(bool busy) { npu_busy_ = busy; }
    void set_pim_busy(bool busy) { pim_busy_ = busy; }
    
    // Statistics
    double get_acceptance_rate() const {
        if (total_draft_tokens_generated_ == 0) return 0.0;
        return static_cast<double>(total_drafts_accepted_) / total_draft_tokens_generated_;
    }
    
    double get_average_entropy() const {
        if (total_drafts_generated_ == 0) return 0.0;
        return total_draft_entropy_ / total_drafts_generated_;
    }
    
    void print_statistics(uint64_t raw_total_cycles = 0) const {
        spdlog::info("=== AHASD Integration Statistics ===");
        spdlog::info("Total Drafts Generated: {}", total_drafts_generated_);
        spdlog::info("Total Draft Tokens Generated: {}", total_draft_tokens_generated_);
        spdlog::info("Total Drafts Accepted: {} ({:.2f}%)", 
                    total_drafts_accepted_, get_acceptance_rate() * 100.0);
        spdlog::info("Total Pre-verifications: {}", total_preverifications_);
        spdlog::info("Average Draft Entropy: {:.3f}", get_average_entropy());
        spdlog::info("NPU Idle Cycles: {}", total_npu_idle_cycles_);
        spdlog::info("PIM Idle Cycles: {}", total_pim_idle_cycles_);
        
        queue_manager_->print_statistics();
        
        if (config_.enable_edc && edc_ != nullptr) {
            edc_->print_statistics();
        }
        
        if (config_.enable_tvc && tvc_ != nullptr) {
            tvc_->print_statistics();
        }

        if (config_.enable_ssrc || config_.enable_ssrc_proxy ||
            config_.enable_ssrc_trace) {
            uint64_t avoided = ssrc_baseline_materialized_bytes_ >
                ssrc_actual_materialized_bytes_
                    ? (ssrc_baseline_materialized_bytes_ - ssrc_actual_materialized_bytes_)
                    : 0;
            const uint64_t modeled_req_bytes = config_.dram_req_size > 0
                ? config_.dram_req_size
                : 1;
            const uint64_t modeled_latency_cycles = config_.dram_latency > 0
                ? config_.dram_latency
                : 1;
            const uint64_t modeled_request_equiv =
                (avoided + modeled_req_bytes - 1) / modeled_req_bytes;
            const uint64_t modeled_unclamped_avoided_cycles =
                modeled_request_equiv * modeled_latency_cycles;
            const double materialization_avoidance_ratio =
                ssrc_baseline_materialized_bytes_ > 0
                    ? static_cast<double>(avoided) /
                          static_cast<double>(ssrc_baseline_materialized_bytes_)
                    : 0.0;
            const uint64_t modeled_upper_bound_avoided_cycles =
                raw_total_cycles > 0 &&
                        modeled_unclamped_avoided_cycles > raw_total_cycles
                    ? raw_total_cycles
                    : modeled_unclamped_avoided_cycles;
            const uint64_t modeled_upper_bound_adjusted_cycles =
                raw_total_cycles > modeled_upper_bound_avoided_cycles
                    ? raw_total_cycles - modeled_upper_bound_avoided_cycles
                    : 0;
            const double modeled_upper_bound_reduction_ratio =
                raw_total_cycles > 0
                    ? static_cast<double>(modeled_upper_bound_avoided_cycles) /
                          static_cast<double>(raw_total_cycles)
                    : 0.0;
            const double conservative_reduction_ratio =
                std::min(modeled_upper_bound_reduction_ratio,
                         materialization_avoidance_ratio);
            const uint64_t modeled_avoided_cycles = raw_total_cycles > 0
                ? static_cast<uint64_t>(
                      static_cast<long double>(raw_total_cycles) *
                      conservative_reduction_ratio)
                : 0;
            const uint64_t modeled_adjusted_cycles =
                raw_total_cycles > modeled_avoided_cycles
                    ? raw_total_cycles - modeled_avoided_cycles
                    : 0;
            const double modeled_reduction_ratio = raw_total_cycles > 0
                ? static_cast<double>(modeled_avoided_cycles) /
                      static_cast<double>(raw_total_cycles)
                : 0.0;

            spdlog::info("=== SSRC Statistics ===");
            spdlog::info("SSRC Baseline Materialized Bytes: {}", ssrc_baseline_materialized_bytes_);
            spdlog::info("SSRC Actual Materialized Bytes: {}", ssrc_actual_materialized_bytes_);
            spdlog::info("SSRC Avoided Materialization Bytes: {}", avoided);
            spdlog::info("SSRC Materialization Avoidance Ratio: {:.8f}",
                         materialization_avoidance_ratio);
            spdlog::info("SSRC Reclaimed Bytes: {}", ssrc_reclaimed_bytes_);
            spdlog::info("SSRC Resident Current Bytes: {}", ssrc_resident_bytes_);
            spdlog::info("SSRC Resident Peak Bytes: {}", ssrc_peak_resident_bytes_);
            spdlog::info("SSRC Committed Bytes: {}", ssrc_committed_bytes_);
            spdlog::info("SSRC Resident Batches: {}", ssrc_resident_batches_);
            spdlog::info("SSRC Deferred Batches: {}", ssrc_deferred_batches_);
            spdlog::info("SSRC Prefetched Batches: {}", ssrc_prefetched_batches_);
            spdlog::info("SSRC Reclaimed Batches: {}", ssrc_reclaimed_batches_);
            spdlog::info("SSRC Trace Identity Active: {}",
                         ssrc_trace_identity_batches_ > 0 ? 1 : 0);
            spdlog::info("SSRC Trace Identity Batches: {}",
                         ssrc_trace_identity_batches_);
            spdlog::info("SSRC Trace Identity Verified Batches: {}",
                         ssrc_trace_identity_verified_batches_);
            double trace_semantic_avg_queue_pressure =
                ssrc_trace_identity_batches_ > 0
                    ? (ssrc_trace_semantic_queue_pressure_sum_ /
                       static_cast<double>(ssrc_trace_identity_batches_))
                    : 0.0;
            double trace_semantic_avg_residency_pressure =
                ssrc_trace_identity_batches_ > 0
                    ? (ssrc_trace_semantic_residency_pressure_sum_ /
                       static_cast<double>(ssrc_trace_identity_batches_))
                    : 0.0;
            double trace_semantic_avg_tvc_slack =
                ssrc_trace_identity_batches_ > 0
                    ? (ssrc_trace_semantic_tvc_slack_sum_ /
                       static_cast<double>(ssrc_trace_identity_batches_))
                    : 0.0;
            spdlog::info("SSRC Trace Semantic Active: {}",
                         ssrc_trace_identity_batches_ > 0 ? 1 : 0);
            spdlog::info("SSRC Trace Semantic Resident Batches: {}",
                         ssrc_trace_semantic_resident_batches_);
            spdlog::info("SSRC Trace Semantic Deferred Batches: {}",
                         ssrc_trace_semantic_deferred_batches_);
            spdlog::info("SSRC Trace Semantic Prefetched Batches: {}",
                         ssrc_trace_semantic_prefetched_batches_);
            spdlog::info("SSRC Trace Semantic Reclaimed Batches: {}",
                         ssrc_trace_semantic_reclaimed_batches_);
            spdlog::info("SSRC Trace Semantic Accepted Bytes: {}",
                         ssrc_trace_semantic_accepted_bytes_);
            spdlog::info("SSRC Trace Semantic Avg Queue Pressure: {:.8f}",
                         trace_semantic_avg_queue_pressure);
            spdlog::info("SSRC Trace Semantic Avg Residency Pressure: {:.8f}",
                         trace_semantic_avg_residency_pressure);
            spdlog::info("SSRC Trace Semantic Avg TVC Slack Proxy: {:.8f}",
                         trace_semantic_avg_tvc_slack);
            spdlog::info("SSRC Modeled DRAM Request Size Bytes: {}", modeled_req_bytes);
            spdlog::info("SSRC Modeled DRAM Latency Cycles: {}", modeled_latency_cycles);
            spdlog::info("SSRC Modeled DRAM Request Equiv: {}", modeled_request_equiv);
            spdlog::info("SSRC Raw Total Cycles: {}", raw_total_cycles);
            spdlog::info("SSRC Modeled Unclamped Avoided Memory Cycles: {}",
                         modeled_unclamped_avoided_cycles);
            spdlog::info("SSRC Modeled Upper Bound Avoided Memory Cycles: {}",
                         modeled_upper_bound_avoided_cycles);
            spdlog::info("SSRC Modeled Upper Bound Adjusted Cycles: {}",
                         modeled_upper_bound_adjusted_cycles);
            spdlog::info("SSRC Modeled Upper Bound Cycle Reduction Ratio: {:.8f}",
                         modeled_upper_bound_reduction_ratio);
            spdlog::info("SSRC Modeled Avoided Memory Cycles: {}", modeled_avoided_cycles);
            spdlog::info("SSRC Modeled Adjusted Cycles: {}", modeled_adjusted_cycles);
            spdlog::info("SSRC Modeled Cycle Reduction Ratio: {:.8f}", modeled_reduction_ratio);
            spdlog::info("SSRC Metric Quality: modeled_sidecar_materialization_capped_not_raw_cycle_coupling");
        }
    }
    
    // Hardware cost summary for paper
    static void print_hardware_costs() {
        spdlog::info("=== AHASD Hardware Overhead ===");
        
        size_t edc_bits = EDC::get_area_bits();
        size_t tvc_bits = TVC::get_area_bits();
        size_t async_queue_bits = 3 * 1024;  // 3 queues, ~1KB each
        
        double edc_mm2 = edc_bits / (8.0 * 1024 * 1024) * 100;  // Rough estimate
        double tvc_mm2 = tvc_bits / (8.0 * 1024 * 1024) * 100;
        double queue_mm2 = 0.001;  // Minimal SRAM
        double aau_mm2 = 0.45;  // From AAU spec
        
        double total_mm2 = edc_mm2 + tvc_mm2 + queue_mm2 + aau_mm2;
        double lpddr5_die_mm2 = 18.0;  // Typical LPDDR5 die size
        
        spdlog::info("EDC: {:.4f} mm² ({} bits)", edc_mm2, edc_bits);
        spdlog::info("TVC: {:.4f} mm² ({} bits)", tvc_mm2, tvc_bits);
        spdlog::info("Async Queues: {:.4f} mm²", queue_mm2);
        spdlog::info("AAU: {:.2f} mm²", aau_mm2);
        spdlog::info("Total: {:.3f} mm² ({:.2f}% of LPDDR5 die)",
                    total_mm2, (total_mm2 / lpddr5_die_mm2) * 100.0);
    }
    
    // Reset for new inference sequence
    void reset() {
        current_kv_length_ = 0;
        current_batch_id_ = 0;
        npu_busy_ = false;
        pim_busy_ = false;
        ssrc_batches_.clear();
        ssrc_baseline_materialized_bytes_ = 0;
        ssrc_actual_materialized_bytes_ = 0;
        ssrc_reclaimed_bytes_ = 0;
        ssrc_resident_bytes_ = 0;
        ssrc_peak_resident_bytes_ = 0;
        ssrc_committed_bytes_ = 0;
        ssrc_deferred_batches_ = 0;
        ssrc_prefetched_batches_ = 0;
        ssrc_resident_batches_ = 0;
        ssrc_reclaimed_batches_ = 0;
        ssrc_trace_identity_batches_ = 0;
        ssrc_trace_identity_verified_batches_ = 0;
        ssrc_trace_semantic_resident_batches_ = 0;
        ssrc_trace_semantic_deferred_batches_ = 0;
        ssrc_trace_semantic_prefetched_batches_ = 0;
        ssrc_trace_semantic_reclaimed_batches_ = 0;
        ssrc_trace_semantic_accepted_bytes_ = 0;
        ssrc_trace_semantic_queue_pressure_sum_ = 0.0;
        ssrc_trace_semantic_residency_pressure_sum_ = 0.0;
        ssrc_trace_semantic_tvc_slack_sum_ = 0.0;
        
        if (edc_ != nullptr) {
            edc_->reset();
        }
        
        if (tvc_ != nullptr) {
            tvc_->reset();
        }
    }
};

} // namespace AHASD
