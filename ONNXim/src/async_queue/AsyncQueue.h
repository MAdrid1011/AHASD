#pragma once

#include <queue>
#include <mutex>
#include <condition_variable>
#include <memory>
#include "../Common.h"

// Asynchronous Queue for cross-device communication between NPU and PIM
// Supports three types: Unverified Draft Queue, Feedback Queue, Pre-verification Queue

namespace AHASD {

enum class QueueType {
    UNVERIFIED_DRAFT,    // Stores token batches from PIM awaiting NPU verification
    FEEDBACK,            // Stores TLM verification results 
    PRE_VERIFICATION     // Marks drafts requiring pre-verification within PIM
};

struct DraftBatch {
    uint32_t batch_id;
    uint32_t draft_length;
    std::vector<int32_t> token_ids;
    std::vector<float> entropy_values;  // For EDC calculation
    uint64_t timestamp;
    bool verified;
    bool accepted;
    bool trace_identity_valid;
    uint32_t trace_request_id;
    uint32_t trace_previous_length;
    uint32_t trace_current_length;
    uint32_t trace_target_length;
    
    DraftBatch() : batch_id(0), draft_length(0), timestamp(0), 
                   verified(false), accepted(false),
                   trace_identity_valid(false), trace_request_id(0),
                   trace_previous_length(0), trace_current_length(0),
                   trace_target_length(0) {}
};

struct FeedbackData {
    uint32_t batch_id;
    uint32_t accepted_length;  // Number of tokens accepted
    bool fully_accepted;
    uint64_t verification_cycles;
    uint64_t kv_cache_length;
    
    FeedbackData() : batch_id(0), accepted_length(0), 
                     fully_accepted(false), verification_cycles(0), 
                     kv_cache_length(0) {}
};

struct PreVerifyRequest {
    uint32_t batch_id;
    uint32_t verify_length;  // Small batch length for pre-verification
    uint64_t timestamp;
    bool urgent;
    
    PreVerifyRequest() : batch_id(0), verify_length(0), 
                        timestamp(0), urgent(false) {}
};

template<typename T>
class AsyncQueue {
private:
    std::queue<T> queue_;
    mutable std::mutex mutex_;
    std::condition_variable cond_var_;
    size_t max_size_;
    QueueType type_;
    
    // Statistics
    uint64_t total_pushes_;
    uint64_t total_pops_;
    uint64_t total_wait_cycles_;

public:
    AsyncQueue(QueueType type, size_t max_size = 128) 
        : type_(type), max_size_(max_size), 
          total_pushes_(0), total_pops_(0), total_wait_cycles_(0) {}
    
    bool push(const T& item) {
        std::unique_lock<std::mutex> lock(mutex_);
        if (queue_.size() >= max_size_) {
            return false;  // Queue full
        }
        queue_.push(item);
        total_pushes_++;
        cond_var_.notify_one();
        return true;
    }
    
    bool try_pop(T& item) {
        std::unique_lock<std::mutex> lock(mutex_);
        if (queue_.empty()) {
            return false;
        }
        item = queue_.front();
        queue_.pop();
        total_pops_++;
        return true;
    }
    
    T pop_blocking() {
        std::unique_lock<std::mutex> lock(mutex_);
        cond_var_.wait(lock, [this]{ return !queue_.empty(); });
        T item = queue_.front();
        queue_.pop();
        total_pops_++;
        return item;
    }
    
    bool empty() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return queue_.empty();
    }
    
    size_t size() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return queue_.size();
    }
    
    void clear() {
        std::lock_guard<std::mutex> lock(mutex_);
        std::queue<T> empty;
        std::swap(queue_, empty);
    }
    
    // Statistics
    uint64_t get_total_pushes() const { return total_pushes_; }
    uint64_t get_total_pops() const { return total_pops_; }
    double get_average_occupancy() const {
        if (total_pushes_ == 0) return 0.0;
        return static_cast<double>(queue_.size()) / max_size_;
    }
};

// Queue manager for coordinating all three async queues
class AsyncQueueManager {
private:
    std::unique_ptr<AsyncQueue<DraftBatch>> unverified_queue_;
    std::unique_ptr<AsyncQueue<FeedbackData>> feedback_queue_;
    std::unique_ptr<AsyncQueue<PreVerifyRequest>> preverify_queue_;
    
    // Cross-device synchronization
    uint64_t npu_cycle_count_;
    uint64_t pim_cycle_count_;
    
public:
    AsyncQueueManager() 
        : npu_cycle_count_(0), pim_cycle_count_(0) {
        unverified_queue_ = std::make_unique<AsyncQueue<DraftBatch>>(
            QueueType::UNVERIFIED_DRAFT, 64);
        feedback_queue_ = std::make_unique<AsyncQueue<FeedbackData>>(
            QueueType::FEEDBACK, 32);
        preverify_queue_ = std::make_unique<AsyncQueue<PreVerifyRequest>>(
            QueueType::PRE_VERIFICATION, 16);
    }
    
    // Interface for PIM side (draft generation)
    bool push_draft(const DraftBatch& batch) {
        return unverified_queue_->push(batch);
    }
    
    bool pop_feedback(FeedbackData& data) {
        return feedback_queue_->try_pop(data);
    }
    
    bool pop_preverify_request(PreVerifyRequest& req) {
        return preverify_queue_->try_pop(req);
    }
    
    // Interface for NPU side (verification)
    bool pop_draft(DraftBatch& batch) {
        return unverified_queue_->try_pop(batch);
    }
    
    bool push_feedback(const FeedbackData& data) {
        return feedback_queue_->push(data);
    }
    
    bool push_preverify_request(const PreVerifyRequest& req) {
        return preverify_queue_->push(req);
    }
    
    // Queue status
    size_t get_unverified_count() const {
        return unverified_queue_->size();
    }
    
    size_t get_feedback_count() const {
        return feedback_queue_->size();
    }
    
    size_t get_preverify_count() const {
        return preverify_queue_->size();
    }
    
    bool has_pending_drafts() const {
        return !unverified_queue_->empty();
    }
    
    // Cycle tracking
    void increment_npu_cycle() { npu_cycle_count_++; }
    void increment_pim_cycle() { pim_cycle_count_++; }
    uint64_t get_npu_cycles() const { return npu_cycle_count_; }
    uint64_t get_pim_cycles() const { return pim_cycle_count_; }
    
    // Statistics
    void print_statistics() const {
        spdlog::info("=== AsyncQueue Statistics ===");
        spdlog::info("Unverified Draft Queue: {} pushes, {} pops, {} pending",
                    unverified_queue_->get_total_pushes(),
                    unverified_queue_->get_total_pops(),
                    unverified_queue_->size());
        spdlog::info("Feedback Queue: {} pushes, {} pops, {} pending",
                    feedback_queue_->get_total_pushes(),
                    feedback_queue_->get_total_pops(),
                    feedback_queue_->size());
        spdlog::info("Pre-verification Queue: {} pushes, {} pops, {} pending",
                    preverify_queue_->get_total_pushes(),
                    preverify_queue_->get_total_pops(),
                    preverify_queue_->size());
        spdlog::info("NPU Cycles: {}, PIM Cycles: {}", 
                    npu_cycle_count_, pim_cycle_count_);
    }
};

} // namespace AHASD
