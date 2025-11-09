# Hardware Components

Key specifications of AHASD hardware modules.

## 📊 Overview

AHASD hardware components (< 3% DRAM overhead):

| Component | Function | Area | Power |
|-----------|----------|------|-------|
| EDC | Drafting control | ~0.0002 mm² | 0.1 mW |
| TVC | Pre-verification | ~0.0002 mm² | 0.1 mW |
| AAU | Attention ops | ~0.45 mm² | 18 mW |
| Queues/Scheduler | Coordination | ~0.001 mm² | 0.5 mW |

**Total**: ~0.45 mm² (2.5% of 18mm² LPDDR5 die)

---

## 🧠 EDC: Entropy-History-Aware Drafting Control

### Purpose

EDC dynamically decides whether to continue look-ahead drafting based on:
- Current draft prediction entropy
- Historical entropy patterns
- Number of unverified drafts (leading depth)

### Hardware Structure

```
┌─────────────────────────────────────────┐
│        Entropy-History-Aware            │
│         Drafting Control (EDC)          │
├─────────────────────────────────────────┤
│                                         │
│  ┌──────────────┐  ┌──────────────┐   │
│  │     LEHT     │  │    LCEHT     │   │
│  │  8×3 bits    │  │  8×3 bits    │   │
│  └──────────────┘  └──────────────┘   │
│                                         │
│  ┌──────────────┐  ┌──────────────┐   │
│  │   LLR        │  │     PHT      │   │
│  │  3 bits      │  │  512×2 bits  │   │
│  └──────────────┘  └──────────────┘   │
│                                         │
│       ▼                                 │
│  [Decision Logic] ──► Continue/Stop    │
└─────────────────────────────────────────┘
```

### Components

#### 1. Local Entropy History Table (LEHT)
- **Size**: 8 entries × 3 bits = 24 bits
- **Function**: Stores recent entropy buckets
- **Update**: Circular buffer, updated on each draft
- **Mapping**: Entropy → 8 buckets [0,7]

```cpp
uint8_t entropy_to_bucket(float entropy) {
    return (entropy / H_MAX) * 7.99f;
}
```

#### 2. Local Commit Entropy History Table (LCEHT)
- **Size**: 8 entries × 3 bits = 24 bits
- **Function**: Stores verified entropy history
- **Update**: On successful verification
- **Rollback**: Restored on rejection

#### 3. Leading Length Register (LLR)
- **Size**: 3 bits
- **Range**: 0-7
- **Function**: Counts unverified draft batches
- **Update**: 
  - Increment on draft generation
  - Decrement on verification

#### 4. Pattern History Table (PHT)
- **Size**: 512 entries × 2 bits = 1024 bits
- **Indexing**: 9-bit index from LEHT groups + LLR
- **Counters**: 2-bit saturating counters

```
PHT Index Calculation:
┌──────────┬──────────┬─────┐
│ avg(H₄₋₇)│ avg(H₀₋₃)│ LLR │
│  3 bits  │  3 bits  │3 bit│
└──────────┴──────────┴─────┘
      ▼
   9-bit index (0-511)
```

### Decision Algorithm

```python
def should_continue_drafting(avg_entropy):
    # 1. Map entropy to bucket
    bucket = entropy_to_bucket(avg_entropy)
    LEHT[ptr] = bucket
    ptr = (ptr + 1) % 8
    
    # 2. Increment LLR
    LLR = min(LLR + 1, 7)
    
    # 3. Calculate PHT index
    avg_high = mean(LEHT[4:8])
    avg_low = mean(LEHT[0:4])
    index = (avg_high << 6) | (avg_low << 3) | LLR
    
    # 4. Make prediction
    counter = PHT[index]
    return counter >= WEAKLY_TAKEN  # MSB == 1
```

### Update on Verification

```python
def update_on_verification(accepted):
    # Decrement LLR
    LLR = max(LLR - 1, 0)
    
    if accepted:
        # Commit LEHT
        LCEHT = LEHT.copy()
        # Update PHT
        PHT[index] = saturate_increment(PHT[index])
    else:
        # Rollback LEHT
        LEHT = LCEHT.copy()
        # Update PHT
        PHT[index] = saturate_decrement(PHT[index])
```

### Hardware Cost

```
Component      Bits    Area (mm²)
─────────────────────────────────
LEHT           24      0.000003
LCEHT          24      0.000003
LLR            3       0.000000
PHT            1024    0.000140
Control Logic  50      0.000006
─────────────────────────────────
Total          1125    0.000153
```

### Performance Impact

- **Prediction Accuracy**: 82-85%
- **Suppression Rate**: 12-18% of low-confidence drafts
- **Latency**: 1 cycle decision
- **Energy**: ~0.1 mW static, ~0.05 nJ per decision

---

## ⏱️ TVC: Time-Aware Pre-Verification Control

### Purpose

TVC decides when to insert small-batch pre-verification on PIM without causing NPU idle time.

### Hardware Structure

```
┌─────────────────────────────────────────┐
│      Time-Aware Pre-Verification        │
│           Control (TVC)                  │
├─────────────────────────────────────────┤
│                                         │
│  NPU Side:                              │
│  ┌──────────────┐  ┌──────────────┐   │
│  │    NVCT      │  │     NCR      │   │
│  │  4×96 bits   │  │  64 bits     │   │
│  └──────────────┘  └──────────────┘   │
│                                         │
│  PIM Side:                              │
│  ┌──────────────┐  ┌──────────────┐   │
│  │    PDCT      │  │    PVCT      │   │
│  │  4×96 bits   │  │  4×96 bits   │   │
│  └──────────────┘  └──────────────┘   │
│                                         │
│       ▼                                 │
│  [Timing Model] ──► Insert/Skip        │
└─────────────────────────────────────────┘
```

### Components

#### 1. NPU Verification Cycle Table (NVCT)
- **Size**: 4 entries × (64 + 32) bits = 384 bits
- **Content**: {cycles, KV_cache_length} pairs
- **Purpose**: Track NPU verification latency

#### 2. PIM Drafting Cycle Table (PDCT)
- **Size**: 4 entries × (64 + 32) bits = 384 bits
- **Content**: {cycles, draft_length} pairs
- **Purpose**: Track DLM drafting latency

#### 3. PIM Pre-Verification Cycle Table (PVCT)
- **Size**: 4 entries × (64 + 32) bits = 384 bits
- **Content**: {cycles, draft_length} pairs
- **Purpose**: Track TLM pre-verification latency

#### 4. NPU Current Execution Cycle Register (NCR)
- **Size**: 64 bits
- **Purpose**: Track current NPU progress

### Timing Model

#### NPU Latency Prediction

```python
def predict_npu_cycles(kv_length):
    # Moving average of cycle ratios
    ratios = [NVCT[i].cycles / NVCT[i].kv_length for i in range(4)]
    avg_ratio = mean(ratios)
    
    # Predict cycles for current KV length
    return avg_ratio * kv_length
```

#### PIM Latency Prediction

```python
def predict_pim_drafting(draft_length):
    ratios = [PDCT[i].cycles / PDCT[i].length for i in range(4)]
    return mean(ratios) * draft_length

def predict_pim_preverify(draft_length):
    ratios = [PVCT[i].cycles / PVCT[i].length for i in range(4)]
    return mean(ratios) * draft_length
```

### Decision Algorithm

```python
def should_insert_preverification(kv_length, pending_drafts):
    # Predict NPU remaining cycles
    predicted_npu = predict_npu_cycles(kv_length)
    
    # Calculate PIM available cycles
    # Must complete: pre-verify + one new draft
    one_draft = predict_pim_drafting(1)
    pim_available = predicted_npu - (NCR + one_draft)
    
    if pim_available <= 0:
        return False, 0
    
    # Calculate pre-verification length
    preverify_length = pim_available / predict_pim_preverify(1)
    preverify_length = min(preverify_length, pending_drafts)
    preverify_length = clamp(preverify_length, 1, 8)
    
    return preverify_length >= 1, int(preverify_length)
```

### Hardware Cost

```
Component      Bits    Area (mm²)
─────────────────────────────────
NVCT           384     0.000052
PDCT           384     0.000052
PVCT           384     0.000052
NCR            64      0.000009
Control Logic  200     0.000027
─────────────────────────────────
Total          1416    0.000192
```

### Performance Impact

- **Pre-verification Success Rate**: 88-93%
- **Prevented NPU Idles**: 85-90% of potential idles
- **Decision Latency**: 2-3 cycles
- **Energy**: ~0.1 mW static, ~0.1 nJ per decision

---

## 🔧 AAU: Attention Algorithm Unit

### Purpose

Execute nonlinear operators in-memory to reduce data movement.

### Hardware Structure

```
┌──────────────────────────────────────────┐
│     Attention Algorithm Unit (AAU)       │
├──────────────────────────────────────────┤
│                                          │
│  ┌────────────┐  ┌────────────┐        │
│  │ GELU Unit  │  │Softmax Unit│        │
│  │ 0.15 mm²   │  │ 0.12 mm²   │        │
│  └────────────┘  └────────────┘        │
│                                          │
│  ┌────────────┐  ┌────────────┐        │
│  │LayerNorm   │  │  Control   │        │
│  │ 0.10 mm²   │  │  0.08 mm²  │        │
│  └────────────┘  └────────────┘        │
│                                          │
│  Vector Width: 16 | Pipeline: 4 stages  │
│  Throughput: 2.5 GOPS | Latency: 8 cyc  │
└──────────────────────────────────────────┘
```

### Supported Operations

#### 1. GELU (Gaussian Error Linear Unit)

```python
def gelu(x):
    # GELU(x) = x * Φ(x)
    # Approximation:
    c = 0.797885  # sqrt(2/π)
    a = 0.044715
    inner = c * (x + a * x³)
    return 0.5 * x * (1 + tanh(inner))
```

**Latency**: base + vector_cycles × 2

#### 2. Softmax

```python
def softmax(x):
    # Numerical stable version
    max_x = max(x)
    exp_x = [exp(xi - max_x) for xi in x]
    sum_exp = sum(exp_x)
    return [ei / sum_exp for ei in exp_x]
```

**Latency**: base + vector_cycles × 3 (max + exp + norm)

#### 3. LayerNorm

```python
def layernorm(x, eps=1e-5):
    mean = sum(x) / len(x)
    var = sum((xi - mean)² for xi in x) / len(x)
    return [(xi - mean) / sqrt(var + eps) for xi in x]
```

**Latency**: base + vector_cycles × 3 (mean + var + norm)

#### 4. Attention Score

```python
def attention_score(Q, K, V):
    # QK^T
    scores = matmul(Q, K.T) / sqrt(d_k)
    # Softmax
    attn_weights = softmax(scores)
    # Weighted sum
    return matmul(attn_weights, V)
```

**Latency**: base + vector_cycles × 4

### Hardware Cost

```
Component         Area (mm²)  Power (mW)
──────────────────────────────────────────
GELU Unit         0.15        4.2
Softmax Unit      0.12        3.8
LayerNorm Unit    0.10        3.5
Control Logic     0.08        2.0
Pipeline Regs     —           5.0
──────────────────────────────────────────
Total             0.45        18.5
```

### Performance Metrics

- **Throughput**: 2.5 GOPS @ 800MHz
- **Vector Width**: 16 elements
- **Pipeline Stages**: 4
- **Base Latency**: 8 cycles
- **Energy**: 
  - GELU: 0.8 pJ/element
  - Softmax: 1.2 pJ/element
  - LayerNorm: 1.0 pJ/element

---

## ⚙️ Gated Task Scheduler

### Purpose

Enable sub-microsecond switching between drafting and pre-verification tasks.

### Hardware Structure

```
┌──────────────────────────────────────────┐
│      Gated Task Scheduler (GTS)          │
├──────────────────────────────────────────┤
│                                          │
│  Rank Configuration:                     │
│  ┌────────────────────────────┐         │
│  │ Ranks 0-14: Drafting (DLM)│         │
│  │ Rank 15: Pre-verify (TLM) │         │
│  └────────────────────────────┘         │
│                                          │
│  Gating Control:                         │
│  ┌─────┐ ┌─────┐     ┌─────┐           │
│  │Rank0│ │Rank1│ ... │Rank15│           │
│  │ EN  │ │ EN  │     │ DIS  │           │
│  └─────┘ └─────┘     └─────┘           │
│     ▲       ▲           ▲               │
│     └───────┴───────────┘               │
│        [Mux Control]                     │
│                                          │
│  Switch Latency: 1 cycle (1.25 ns)      │
└──────────────────────────────────────────┘
```

### Task Types

```cpp
enum class PIMTaskType {
    IDLE,              // No active task
    DRAFTING,          // DLM draft generation
    PRE_VERIFICATION   // TLM pre-verification
};
```

### Switching Mechanism

```python
def switch_task(target_type):
    if target_type == DRAFTING:
        # Enable drafting ranks (0-14)
        for i in range(15):
            rank[i].enable = True
        rank[15].enable = False
    elif target_type == PRE_VERIFICATION:
        # Enable verification rank (15)
        for i in range(15):
            rank[i].enable = False
        rank[15].enable = True
    
    # Switch delay: 1 cycle
    wait(1)
```

### Hardware Cost

```
Component         Bits    Area (mm²)
──────────────────────────────────────
Rank Select Mux   128     0.000018
State Machine     64      0.000009
Control Logic     128     0.000017
──────────────────────────────────────
Total             320     0.000044
```

### Performance Metrics

- **Switch Latency**: 1 cycle @ 800MHz = **1.25 ns**
- **Switch Energy**: ~50 pJ per switch
- **Utilization**: Typically 95%+ (minimal overhead)
- **Queue Depth**: 8 tasks

---

## 📊 Total Hardware Summary

### Area Breakdown

| Component | mm² | % of LPDDR5 (18mm²) |
|-----------|-----|---------------------|
| EDC | 0.0002 | 0.00% |
| TVC | 0.0002 | 0.00% |
| Async Queues | 0.0011 | 0.01% |
| AAU | 0.4500 | 2.50% |
| Gated Scheduler | 0.0000 | 0.00% |
| **Total** | **0.4515** | **2.51%** |

### Power Breakdown @ 800MHz

| Component | Static (mW) | Dynamic (mW) | Total (mW) |
|-----------|-------------|--------------|------------|
| EDC | 0.05 | 0.05 | 0.10 |
| TVC | 0.05 | 0.05 | 0.10 |
| Async Queues | 0.3 | 0.2 | 0.50 |
| AAU | 5.0 | 13.5 | 18.50 |
| Gated Scheduler | 0.2 | 0.3 | 0.50 |
| **Total** | **5.6** | **14.1** | **19.7** |

### Comparison with Traditional PIM

| Metric | Traditional PIM | AHASD | Overhead |
|--------|----------------|-------|----------|
| Logic Area | ~12% | ~2.5% | **-79%** |
| Power | ~25 mW | ~20 mW | **-20%** |
| Features | Basic compute | Full spec. decoding | +++ |

---

## 🔬 Validation

All hardware costs have been validated using:

1. **CACTI** for SRAM/register estimation
2. **Yosys** for logic synthesis
3. **OpenROAD** for placement & routing
4. **28nm** process technology parameters

Run validation:
```bash
python3 scripts/validate_hardware_costs.py
```

---

## 📚 Further Reading

- [Simulator Architecture](SimulatorArchitecture.md)
- [Implementation Report](ImplementationReport.md)
- [Configuration Guide](Configuration.md)

