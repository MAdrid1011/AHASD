#pragma once

#include <vector>
#include <cstdint>
#include <deque>
#include "../Common.h"

// Time-Aware Pre-Verification Control (TVC) Module
// Performs runtime two-sided latency modeling for NPU and PIM
// Decides when to insert small-batch pre-verification

namespace AHASD {

// E1 — sensitivity sweep default. Historical value is 4; parametric
// overrides flow from SimulationConfig via AHASDIntegration.
constexpr uint32_t DEFAULT_CYCLE_TABLE_SIZE = 4;
constexpr uint32_t CYCLE_TABLE_SIZE = DEFAULT_CYCLE_TABLE_SIZE;  // back-compat

struct CycleRecord {
    uint64_t cycles;
    uint32_t length;  // KV cache length or draft length
    
    CycleRecord() : cycles(0), length(0) {}
    CycleRecord(uint64_t c, uint32_t l) : cycles(c), length(l) {}
    
    float get_ratio() const {
        if (length == 0) return 0.0f;
        return static_cast<float>(cycles) / length;
    }
};

class TVC {
private:
    // NPU Verification Cycle Table (NVCT)
    std::deque<CycleRecord> nvct_;
    
    // PIM Drafting Cycle Table (PDCT)
    std::deque<CycleRecord> pdct_;
    
    // PIM Pre-Verification Cycle Table (PVCT)
    std::deque<CycleRecord> pvct_;
    
    // NPU Current Execution Cycle Register (NCR)
    uint64_t ncr_;
    
    // Current NPU task start cycle
    uint64_t npu_task_start_;
    
    // Frequency ratio (PIM freq / NPU freq) for cycle conversion
    float freq_ratio_;

    // E1 — runtime-configurable sliding window depth (NVCT/PDCT/PVCT share).
    uint32_t cycle_table_size_;

    // Statistics
    uint64_t total_preverifications_;
    uint64_t successful_preverifications_;
    uint64_t prevented_npu_idles_;
    uint64_t total_decisions_;

    // Helper: Calculate moving average of cycle ratios
    float calculate_avg_ratio(const std::deque<CycleRecord>& table) const {
        if (table.empty()) return 0.0f;

        float sum = 0.0f;
        for (const auto& record : table) {
            sum += record.get_ratio();
        }
        return sum / table.size();
    }

    // Helper: Add record to cycle table (maintain size limit)
    void add_to_table(std::deque<CycleRecord>& table,
                     uint64_t cycles, uint32_t length) {
        while (table.size() >= cycle_table_size_) {
            table.pop_front();
        }
        table.push_back(CycleRecord(cycles, length));
    }

public:
    TVC(float pim_freq_mhz = 800.0f, float npu_freq_mhz = 1000.0f,
        uint32_t cycle_table_size = DEFAULT_CYCLE_TABLE_SIZE)
        : ncr_(0), npu_task_start_(0),
          cycle_table_size_(std::max<uint32_t>(1u, cycle_table_size)),
          total_preverifications_(0), successful_preverifications_(0),
          prevented_npu_idles_(0), total_decisions_(0) {
        freq_ratio_ = pim_freq_mhz / npu_freq_mhz;
    }

    uint32_t get_cycle_table_size() const { return cycle_table_size_; }
    
    // Record NPU verification completion
    void record_npu_verification(uint64_t cycles, uint32_t kv_cache_length) {
        add_to_table(nvct_, cycles, kv_cache_length);
    }
    
    // Record PIM drafting completion
    void record_pim_drafting(uint64_t cycles, uint32_t draft_length) {
        add_to_table(pdct_, cycles, draft_length);
    }
    
    // Record PIM pre-verification completion
    void record_pim_preverification(uint64_t cycles, uint32_t draft_length) {
        add_to_table(pvct_, cycles, draft_length);
        total_preverifications_++;
    }
    
    // Start NPU verification task
    void start_npu_task(uint64_t current_cycle) {
        npu_task_start_ = current_cycle;
        ncr_ = 0;
    }
    
    // Update current NPU execution progress
    void update_npu_progress(uint64_t current_npu_cycle) {
        ncr_ = current_npu_cycle - npu_task_start_;
    }
    
    // Core decision logic: should we insert pre-verification?
    // Returns: <should_preverify, preverify_length>
    std::pair<bool, uint32_t> should_insert_preverification(
        uint32_t current_kv_length,
        uint32_t pending_draft_count) {
        
        total_decisions_++;
        
        // No pre-verification needed if insufficient data or no pending drafts
        if (nvct_.empty() || pdct_.empty() || pvct_.empty() || 
            pending_draft_count == 0) {
            return {false, 0};
        }
        
        // Predict NPU remaining cycles (converted to PIM equivalent)
        float npu_ratio = calculate_avg_ratio(nvct_);
        uint64_t predicted_npu_cycles = static_cast<uint64_t>(
            npu_ratio * current_kv_length * freq_ratio_);
        
        // Calculate PIM cycles available for pre-verification
        // C_PIM-Left = C_NPU_i - (C_now + C_PIM-Draft_1)
        float draft_ratio = calculate_avg_ratio(pdct_);
        uint64_t one_draft_cycles = static_cast<uint64_t>(draft_ratio * 1);
        
        if (predicted_npu_cycles <= (ncr_ + one_draft_cycles)) {
            return {false, 0};  // Not enough time
        }
        
        uint64_t pim_left_cycles = predicted_npu_cycles - (ncr_ + one_draft_cycles);
        
        // Calculate how many tokens can be pre-verified
        float preverify_ratio = calculate_avg_ratio(pvct_);
        if (preverify_ratio < 1e-6) {
            preverify_ratio = draft_ratio * 0.8f;  // Estimate if no data
        }
        
        uint32_t preverify_length = static_cast<uint32_t>(
            pim_left_cycles / preverify_ratio);
        
        // Clamp to reasonable range and pending drafts
        preverify_length = std::min(preverify_length, pending_draft_count);
        preverify_length = std::max(1u, std::min(preverify_length, 8u));
        
        if (preverify_length >= 1) {
            successful_preverifications_++;
            return {true, preverify_length};
        }
        
        return {false, 0};
    }
    
    // Alternative conservative decision (used in paper)
    bool conservative_preverify_decision(
        uint32_t predicted_npu_remaining_cycles,
        uint32_t min_preverify_length = 2) {
        
        if (pdct_.empty() || pvct_.empty()) return false;
        
        float draft_ratio = calculate_avg_ratio(pdct_);
        float preverify_ratio = calculate_avg_ratio(pvct_);
        
        uint64_t one_draft_cycles = static_cast<uint64_t>(draft_ratio);
        uint64_t preverify_cycles = static_cast<uint64_t>(
            preverify_ratio * min_preverify_length);
        
        // Ensure NPU won't be idle
        return (preverify_cycles + one_draft_cycles) < predicted_npu_remaining_cycles;
    }
    
    // Mark successful prevention of NPU idle
    void record_prevented_idle() {
        prevented_npu_idles_++;
    }
    
    // Reset for new inference
    void reset() {
        nvct_.clear();
        pdct_.clear();
        pvct_.clear();
        ncr_ = 0;
        npu_task_start_ = 0;
    }
    
    // Statistics
    double get_preverify_success_rate() const {
        if (total_preverifications_ == 0) return 0.0;
        return static_cast<double>(successful_preverifications_) / 
               total_preverifications_;
    }
    
    void print_statistics() const {
        spdlog::info("=== TVC Statistics ===");
        spdlog::info("Total Decisions: {}, Pre-verifications Inserted: {}",
                    total_decisions_, total_preverifications_);
        spdlog::info("Successful Pre-verifications: {} ({:.2f}%)",
                    successful_preverifications_,
                    get_preverify_success_rate() * 100.0);
        spdlog::info("Prevented NPU Idles: {}", prevented_npu_idles_);
        
        // Print cycle table states
        if (!nvct_.empty()) {
            spdlog::info("NVCT avg ratio: {:.2f} cycles/kv_length", 
                        calculate_avg_ratio(nvct_));
        }
        if (!pdct_.empty()) {
            spdlog::info("PDCT avg ratio: {:.2f} cycles/draft_length",
                        calculate_avg_ratio(pdct_));
        }
        if (!pvct_.empty()) {
            spdlog::info("PVCT avg ratio: {:.2f} cycles/draft_length",
                        calculate_avg_ratio(pvct_));
        }
    }
    
    // Hardware cost estimation (for paper)
    static constexpr size_t get_area_bits() {
        // NVCT: 4 entries × (64 + 32 bits) = 384 bits
        // PDCT: 4 entries × (64 + 32 bits) = 384 bits
        // PVCT: 4 entries × (64 + 32 bits) = 384 bits
        // NCR: 64 bits
        // Control logic: ~200 bits
        // Total: ~1416 bits ≈ 177 bytes
        return 384 * 3 + 64 + 200;
    }
};

} // namespace AHASD

