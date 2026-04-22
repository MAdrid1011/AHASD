#pragma once

#include <vector>
#include <cstdint>
#include <cmath>
#include <algorithm>
#include "../Common.h"

// Entropy-History-Aware Drafting Control (EDC) Module
// Combines historical prediction entropy with leading draft batches
// to perform hardware-level online learning

namespace AHASD {

// E1 — sensitivity sweep defaults. These values match the DAC design
// point; parametric overrides flow from SimulationConfig via
// AHASDIntegration. Keeping them as the historical constants means
// zero-config instantiation reproduces the DAC behaviour bit-for-bit.
constexpr uint32_t DEFAULT_LEHT_SIZE = 8;   // Local Entropy History Table
constexpr uint32_t DEFAULT_PHT_SIZE  = 512; // Pattern History Table (2^9)
constexpr uint32_t PHT_COUNTER_BITS  = 2;   // 2-bit saturating counter
constexpr float    DEFAULT_H_MAX     = 10.0f;
constexpr uint32_t DEFAULT_LLR_BITS  = 3;

// Back-compat aliases (referenced in older call sites / tests).
constexpr uint32_t LEHT_SIZE         = DEFAULT_LEHT_SIZE;
constexpr uint32_t PHT_SIZE          = DEFAULT_PHT_SIZE;
constexpr float    H_MAX             = DEFAULT_H_MAX;

// 2-bit saturating counter states
enum class CounterState : uint8_t {
    STRONGLY_NOT_TAKEN = 0,
    WEAKLY_NOT_TAKEN = 1,
    WEAKLY_TAKEN = 2,
    STRONGLY_TAKEN = 3
};

class EDC {
private:
    // Local Entropy History Table (LEHT) - stores recent entropy buckets
    std::vector<uint8_t> leht_;

    // Local Commit Entropy History Table (LCEHT) - stores verified entropy
    std::vector<uint8_t> lceht_;

    // Leading Length Register (LLR) - n-bit counter (default 3)
    uint8_t llr_;

    // Pattern History Table (PHT) - sized from LEHT/LLR
    std::vector<CounterState> pht_;

    // Statistics
    uint64_t total_predictions_;
    uint64_t correct_predictions_;
    uint64_t suppressed_drafts_;
    uint64_t total_drafts_;

    // Configuration (E1 — runtime-configurable)
    float h_max_;
    uint32_t leht_size_;
    uint32_t llr_bits_;
    uint8_t  llr_max_;          // (1 << llr_bits_) - 1
    uint32_t pht_size_;         // cached, power-of-two
    uint32_t pht_index_mask_;   // pht_size_ - 1
    uint32_t leht_group_bits_;  // bits per LEHT-avg field in PHT index
    uint32_t leht_ptr_;         // Circular buffer pointer

    // Helper: derive PHT sizing from LEHT/LLR. PHT index historically =
    // {avg(H_{4-7})[2:0], avg(H_{0-3})[2:0], LLR[2:0]} = 9 bits -> 512.
    // Generalisation: keep 3-bit entropy bucket encoding (entropy_to_bucket
    // always yields [0,7]), so each LEHT-avg contributes 3 bits regardless
    // of history length; LLR contributes llr_bits_. Cap at 16 bits (64 KiB)
    // to avoid pathological configs.
    static uint32_t compute_pht_size(uint32_t llr_bits) {
        uint32_t bits = 3u + 3u + llr_bits;  // two LEHT-avgs + LLR
        bits = std::min<uint32_t>(bits, 16u);
        return 1u << bits;
    }

    // Helper functions
    uint8_t entropy_to_bucket(float entropy) const {
        // Map entropy to one of 8 buckets [0,7]
        if (entropy < 0.0f) entropy = 0.0f;
        if (entropy > h_max_) entropy = h_max_;
        return static_cast<uint8_t>((entropy / h_max_) * 7.99f);
    }

    uint16_t calculate_pht_index() const {
        // Calculate PHT index from LEHT groups and LLR
        // Input_PHT = {avg(upper half), avg(lower half), LLR}
        if (leht_size_ == 0) return 0;
        uint32_t half = std::max<uint32_t>(1u, leht_size_ / 2u);

        // Lower half
        uint32_t sum_low = 0;
        for (uint32_t i = 0; i < half && i < leht_size_; i++) {
            sum_low += leht_[i];
        }
        uint8_t avg_low = static_cast<uint8_t>(sum_low / half);  // 3 bits

        // Upper half (may be shorter for odd leht_size_)
        uint32_t upper_count = leht_size_ > half ? (leht_size_ - half) : 0;
        uint32_t sum_high = 0;
        for (uint32_t i = half; i < leht_size_; i++) {
            sum_high += leht_[i];
        }
        uint8_t avg_high = upper_count
            ? static_cast<uint8_t>(sum_high / upper_count)
            : 0;

        // Concatenate: {avg_high[2:0], avg_low[2:0], llr[llr_bits_-1:0]}
        uint32_t index = (static_cast<uint32_t>(avg_high) << (3u + llr_bits_))
                       | (static_cast<uint32_t>(avg_low)  << llr_bits_)
                       | static_cast<uint32_t>(llr_ & llr_max_);
        return static_cast<uint16_t>(index & pht_index_mask_);
    }

    void update_counter(CounterState& counter, bool taken) {
        uint8_t val = static_cast<uint8_t>(counter);
        if (taken && val < 3) {
            counter = static_cast<CounterState>(val + 1);
        } else if (!taken && val > 0) {
            counter = static_cast<CounterState>(val - 1);
        }
    }

public:
    EDC(float h_max = DEFAULT_H_MAX,
        uint32_t leht_size = DEFAULT_LEHT_SIZE,
        uint32_t llr_bits  = DEFAULT_LLR_BITS)
        : llr_(0),
          total_predictions_(0), correct_predictions_(0),
          suppressed_drafts_(0), total_drafts_(0),
          h_max_(h_max),
          leht_size_(std::max<uint32_t>(1u, leht_size)),
          llr_bits_(std::clamp<uint32_t>(llr_bits, 1u, 8u)),
          llr_max_(static_cast<uint8_t>((1u << std::clamp<uint32_t>(llr_bits, 1u, 8u)) - 1u)),
          pht_size_(compute_pht_size(std::clamp<uint32_t>(llr_bits, 1u, 8u))),
          pht_index_mask_(pht_size_ - 1u),
          leht_group_bits_(3u),
          leht_ptr_(0) {
        leht_.resize(leht_size_, 0);
        lceht_.resize(leht_size_, 0);
        pht_.resize(pht_size_, CounterState::WEAKLY_TAKEN);
    }

    // Called after each draft batch generation
    bool should_continue_drafting(float avg_entropy) {
        total_drafts_++;

        uint8_t bucket = entropy_to_bucket(avg_entropy);
        leht_[leht_ptr_] = bucket;
        leht_ptr_ = (leht_ptr_ + 1) % leht_size_;

        // Increment LLR (saturates at llr_max_)
        if (llr_ < llr_max_) {
            llr_++;
        }

        uint16_t pht_index = calculate_pht_index();
        CounterState prediction = pht_[pht_index];

        total_predictions_++;

        // MSB of counter determines prediction
        bool should_continue = (static_cast<uint8_t>(prediction) >= 2);

        if (!should_continue) {
            suppressed_drafts_++;
        }

        return should_continue;
    }

    // Called after NPU verification completes
    void update_on_verification(bool fully_accepted, uint32_t accepted_count) {
        if (llr_ > 0) {
            llr_--;
        }

        if (fully_accepted) {
            lceht_ = leht_;
            correct_predictions_++;
        } else {
            leht_ = lceht_;
        }

        uint16_t pht_index = calculate_pht_index();
        update_counter(pht_[pht_index], fully_accepted);
    }

    // Reset state (for new inference sequence)
    void reset() {
        std::fill(leht_.begin(), leht_.end(), 0);
        std::fill(lceht_.begin(), lceht_.end(), 0);
        llr_ = 0;
        leht_ptr_ = 0;
    }

    // Getters for current state
    uint8_t get_llr() const { return llr_; }

    const std::vector<uint8_t>& get_leht() const { return leht_; }

    float    get_h_max() const { return h_max_; }
    uint32_t get_leht_size() const { return leht_size_; }
    uint32_t get_llr_bits() const { return llr_bits_; }
    uint32_t get_pht_size() const { return pht_size_; }

    // Statistics
    double get_prediction_accuracy() const {
        if (total_predictions_ == 0) return 0.0;
        return static_cast<double>(correct_predictions_) / total_predictions_;
    }

    double get_suppression_rate() const {
        if (total_drafts_ == 0) return 0.0;
        return static_cast<double>(suppressed_drafts_) / total_drafts_;
    }

    void print_statistics() const {
        spdlog::info("=== EDC Statistics ===");
        spdlog::info("Config: H_max={:.2f} LEHT_size={} LLR_bits={} PHT_size={}",
                     h_max_, leht_size_, llr_bits_, pht_size_);
        spdlog::info("Total Predictions: {}, Accuracy: {:.2f}%",
                    total_predictions_, get_prediction_accuracy() * 100.0);
        spdlog::info("Total Drafts: {}, Suppressed: {} ({:.2f}%)",
                    total_drafts_, suppressed_drafts_,
                    get_suppression_rate() * 100.0);
        spdlog::info("Current LLR: {}", llr_);
    }

    // Hardware cost estimation (for paper)
    static constexpr size_t get_area_bits() {
        // Reported at the DAC design point (LEHT=8, LLR=3b, PHT=512) so
        // Section 5.4 numbers remain stable regardless of sweep configs.
        return 24 + 24 + 3 + 1024;
    }
};

} // namespace AHASD

