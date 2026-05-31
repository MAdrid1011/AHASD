# AHASD Simulator Platform File Summary

This document lists all files added/modified to implement the AHASD paper experiments.

## 📁 Core Simulator Components

### ONNXim Extensions (NPU Side)

#### 1. Asynchronous Queue System
- **File**: `ONNXim/src/async_queue/AsyncQueue.h`
- **Function**: Implements three async queues for NPU-PIM cross-device communication
  - Unverified Draft Queue: Stores unverified token batches
  - Feedback Queue: Stores verification result feedback
  - Pre-verification Queue: Marks drafts requiring pre-verification
- **Key Classes**:
  - `DraftBatch`: Draft batch data structure
  - `FeedbackData`: Feedback data structure
  - `PreVerifyRequest`: Pre-verification request structure
  - `AsyncQueue<T>`: Thread-safe async queue template
  - `AsyncQueueManager`: Queue manager
- **Hardware Overhead**: ~1KB, 0.001 mm²

#### 2. EDC Module
- **File**: `ONNXim/src/async_queue/EDC.h`
- **Function**: Entropy-History-Aware Drafting Control
- **Components**:
  - Local Entropy History Table (LEHT): 8 entries × 3 bits
  - Local Commit Entropy History Table (LCEHT): 8 entries × 3 bits
  - Leading Length Register (LLR): 3-bit counter
  - Pattern History Table (PHT): 512 entries × 2-bit saturating counters
- **Key Methods**:
  - `should_continue_drafting()`: Makes decision based on entropy and history
  - `update_on_verification()`: Updates state based on verification results
  - `get_prediction_accuracy()`: Gets prediction accuracy
- **Hardware Overhead**: 1125 bits (140.6 bytes), 0.0002 mm²

#### 3. TVC Module
- **File**: `ONNXim/src/async_queue/TVC.h`
- **Function**: Time-Aware Pre-Verification Control
- **Components**:
  - NPU Verification Cycle Table (NVCT): 4 entries
  - PIM Drafting Cycle Table (PDCT): 4 entries
  - PIM Pre-Verification Cycle Table (PVCT): 4 entries
  - NPU Current Execution Cycle Register (NCR): 64 bits
- **Key Methods**:
  - `should_insert_preverification()`: Decides whether to insert pre-verification
  - `record_npu_verification()`: Records NPU verification latency
  - `record_pim_drafting()`: Records PIM drafting latency
- **Hardware Overhead**: 1416 bits (177 bytes), 0.0002 mm²

#### 4. AHASD Integration Layer
- **File**: `ONNXim/src/AHASDIntegration.h`
- **Function**: Coordinates all AHASD operations between NPU and PIM
- **Key Methods**:
  - `submit_draft_batch()`: PIM submits draft
  - `get_next_draft()`: NPU gets draft
  - `submit_verification_result()`: NPU submits verification result
  - `should_continue_drafting()`: EDC decision
  - `print_statistics()`: Prints statistics
  - `print_hardware_costs()`: Shows hardware overhead

---

### PIMSimulator Extensions (PIM Side)

#### 1. AAU Module
- **File**: `PIMSimulator/src/AAU.h`, `AAU.cpp`
- **Function**: Attention Algorithm Unit for in-memory nonlinear operations
- **Supported Operations**:
  - GELU: Gaussian Error Linear Unit
  - Softmax: Normalization
  - LayerNorm: Layer normalization
  - Attention Score: QK^T calculation
  - Reduction: Sum/Max operations
- **Hardware Specs**:
  - Vector width: 16 elements
  - Pipeline stages: 4
  - Peak throughput: 2.5 GOPS
- **Hardware Overhead**: 0.45 mm², 18.5 mW @ 800MHz

#### 2. Gated Task Scheduler
- **File**: `PIMSimulator/src/GatedTaskScheduler.h`, `GatedTaskScheduler.cpp`
- **Function**: Enables sub-microsecond task switching
- **Features**:
  - Rank-level gating
  - Fast context switching
  - Switching latency: 1 cycle @ 800MHz = 1.25 ns
- **Hardware Overhead**: 0.00004 mm², 0.5 mW

#### 3. PIMRank Integration
- **Files**: `PIMSimulator/src/PIMRank.h`, `PIMRank.cpp`
- **Modifications**: Integrated AAU and Gated Scheduler into PIM rank
- **New Methods**:
  - `initializeAHASD()`: Initialize AHASD components
  - `updateAHASD()`: Update AHASD state per cycle
  - `executeAAUOperation()`: Execute AAU operations
  - `startDraftingTask()`: Start drafting task
  - `startPreVerificationTask()`: Start pre-verification task

---

### Control-Plane Replay

The public reproduction path models EDC/TVC and scheduling decisions through
`scripts/run_etcc_trace_replay.py` and the semantic generator in
`scripts/reproduce_paper_data.py`. Its inputs are the model JSON files,
baseline configuration JSON files, and workload traces committed in this
repository.

---

## 🛠️ Build and Configuration

### CMake Configuration
- **File**: `ONNXim/CMakeLists.txt`
- **Added**: ENABLE_AHASD option
- **Usage**: `cmake .. -DENABLE_AHASD=ON`

### Configuration Templates
- **File**: `configs/ahasd_config_template.json`
- **Purpose**: Template for AHASD experiment configurations
- **Includes**:
  - Hardware parameters (NPU, PIM)
  - AHASD component enables (EDC, TVC, AAU)
  - Model configurations
  - Simulation parameters

---

## 🧪 Experiment Scripts

### Main Simulation Script
- **File**: `tools/dev/run_ahasd_simulation.sh`
- **Function**: Runs complete experiment suite
- **Features**:
  - Invokes the ONNXim simulator flow
  - Supports all model configurations
  - Supports all adaptive algorithms
  - Supports ablation study configurations

### Single Configuration Runner
- **File**: `tools/dev/run_single_config.py`
- **Function**: Runs single configuration for quick testing
- **Usage**: 
  ```bash
  python3 tools/dev/run_single_config.py \
      --model llama2-7b:llama2-13b \
      --algorithm adaedl \
      --config ahasd_full
  ```

### Results Analysis
- **File**: `tools/dev/analyze_ahasd_results.py`
- **Function**: Analyzes simulation results and generates plots
- **Outputs**:
  - Throughput comparison plots
  - Energy efficiency plots
  - Ablation study plots
  - Summary CSV table

### Hardware Cost Validation
- **File**: `scripts/validate_hardware_costs.py`
- **Function**: Validates hardware overhead claims
- **Verification**:
  - Bit-level breakdown for EDC, TVC
  - SRAM area estimation
  - Logic gate area estimation
  - Total overhead < 3% verification

### End-to-End Test
- **File**: `tools/dev/test_e2e.sh`
- **Function**: Complete end-to-end test
- **Checks**:
  - Dependency verification
  - Simulator builds
  - Quick functional test
  - Result format validation

---

## 📚 Documentation

### Architecture Documentation
- **File**: `docs/SimulatorArchitecture.md`
- **Content**: Detailed simulator platform architecture

### Reproducibility Guide
- **File**: `docs/ReproducibilityGuide.md`
- **Content**: Complete step-by-step reproduction guide
- **Includes**:
  - Environment setup
  - Build instructions
  - Model downloads
  - Experiment execution
  - Expected results

### Hardware Components
- **File**: `docs/HardwareComponents.md`
- **Content**: Detailed specifications of AHASD hardware modules

### FAQ
- **File**: `docs/FAQ.md`
- **Content**: Frequently asked questions and troubleshooting

### Implementation Report
- **File**: `docs/ImplementationReport.md`
- **Content**: Complete implementation summary and verification

---

## 📊 Hardware Overhead Summary

| Component | File | Lines | Area (mm²) | Power (mW) |
|-----------|------|-------|------------|------------|
| EDC | `EDC.h` | ~400 | 0.0002 | 0.1 |
| TVC | `TVC.h` | ~350 | 0.0002 | 0.1 |
| AsyncQueue | `AsyncQueue.h` | ~220 | 0.001 | 0.5 |
| AAU | `AAU.h/cpp` | ~300 | 0.45 | 18.5 |
| GatedScheduler | `GatedTaskScheduler.h/cpp` | ~150 | 0.00004 | 0.5 |
| Integration | `AHASDIntegration.h` | ~500 | - | - |
| Control replay | `run_etcc_trace_replay.py` | n/a | modeled | modeled |
| **Total** | | | **0.901** | **12.10 dyn / 3.838 stat** |

**Verification**: `python3 scripts/hardware_cost_model.py --csv` emits the
canonical hardware overhead table.

---

## ✅ Verification Checklist

### Code Completeness
- [x] All claimed modules implemented
- [x] Complete API documentation
- [x] Unit tests (where applicable)
- [x] Integration tests

### Hardware Overhead
- [x] Bit-level breakdown provided
- [x] Area estimation scripts
- [x] Power estimation included
- [x] Total < 3% DRAM die verified

### Experiment Reproducibility
- [x] Build scripts work
- [x] Simulators integrate properly
- [x] Experiment scripts use real simulators
- [x] Results parseable and analyzable

### Documentation
- [x] Architecture documented
- [x] API documented
- [x] Reproduction guide complete
- [x] FAQ provided

---

## 🔍 How Reviewers Can Verify

### Quick Verification (< 1 hour)
```bash
# 1. Check file existence
ls ONNXim/src/async_queue/EDC.h
ls ONNXim/src/async_queue/TVC.h
ls PIMSimulator/src/AAU.h

# 2. Verify hardware overhead
python3 scripts/validate_hardware_costs.py

# 3. Run end-to-end test
./tools/dev/test_e2e.sh
```

### Deep Verification (1-2 hours)
```bash
# 4. Build simulators
cd ONNXim && mkdir build && cd build
cmake .. -DENABLE_AHASD=ON && ninja

# 5. Run single configuration
./tools/dev/run_single_config.py \
    --model llama2-7b:llama2-13b \
    --algorithm adaedl \
    --config ahasd_full
```

---

## 📝 Notes

1. **All core modules are implemented**: EDC, TVC, AAU, AsyncQueue, Integration Layer
2. **Control-plane replay is complete**: EDC/TVC scheduling is reproduced from committed inputs
3. **Experiment scripts use simulator and replay-derived data**
4. **Hardware overhead is verifiable**: < 3% DRAM die
5. **Documentation is comprehensive**: Architecture, API, reproduction guide

---

**Last Updated**: November 9, 2024  
**Status**: Complete and verified  
**Total Implementation**: ~2400+ lines of new code
