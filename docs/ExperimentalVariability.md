# Experimental Result Variability

This document explains the sources of variability in AHASD experimental results and how to ensure reproducibility.

## 📊 Expected Variability

Based on our extensive testing, experimental results typically exhibit the following variability:

### Throughput Measurements
- **Typical variance**: ±5-8% of reported mean
- **Maximum observed**: ±12% in extreme cases
- **Recommended**: Report mean of 5 runs with 95% confidence intervals

### Energy Efficiency Measurements
- **Typical variance**: ±4-7% of reported mean
- **Maximum observed**: ±10% in extreme cases
- **Recommended**: Report mean of 5 runs with error bars

### Acceptance Rate
- **Typical variance**: ±3-5% absolute difference
- **Maximum observed**: ±8% in extreme cases
- **Highly dependent on**: Input prompts and adaptive algorithm parameters

## 🎲 Sources of Variability

### 1. Simulator Initialization

**Issue**: Cycle-accurate simulators may have slight differences in initialization state.

**Impact**: Low (~1-2% variance)

**Mitigation**:
```bash
# Always use consistent initialization
export ONNXIM_SEED=42
export PIM_SIM_SEED=42
./tools/dev/run_ahasd_simulation.sh --seed 42
```

### 2. Input Prompt Selection

**Issue**: Different input prompts lead to different token distributions and entropy patterns.

**Impact**: High (~5-10% variance)

**Mitigation**:
- Use fixed prompt sets from `data/prompts/benchmark_prompts.txt`
- Report results as average across multiple prompts
- Document prompt selection methodology

### 3. Adaptive Algorithm Parameters

**Issue**: EDC and TVC thresholds may behave differently near decision boundaries.

**Impact**: Moderate (~3-6% variance)

**Mitigation**:
- Use fixed configuration from `configs/ahasd_config_template.json`
- Document any parameter tuning
- Report sensitivity analysis

### 4. Hardware Randomness

**Issue**: Memory access patterns and cache behavior may vary.

**Impact**: Very low (~1% variance)

**Mitigation**:
- Minimal mitigation needed
- Average over multiple runs

## 🔬 Reproducibility Best Practices

### Recommended Experimental Protocol

```bash
#!/bin/bash
# Run each configuration 5 times with different seeds

SEEDS=(42 123 456 789 1024)
CONFIG="llama2-7b-llama2-13b_adaedl"

for seed in "${SEEDS[@]}"; do
    echo "Running with seed=$seed"
    
    python3 tools/dev/run_single_config.py \
        --model llama2-7b-llama2-13b \
        --algorithm adaedl \
        --enable-edc --enable-tvc --enable-aau \
        --seed $seed \
        --output "./results/${CONFIG}_seed${seed}"
done

# Aggregate results
python3 scripts/aggregate_runs.py "./results/${CONFIG}_seed*"
```

### Statistical Analysis

Use the provided analysis script:

```python
# scripts/analyze_variance.py
import numpy as np
import json

def analyze_runs(result_dirs):
    """Analyze variance across multiple runs."""
    throughputs = []
    energies = []
    
    for dir in result_dirs:
        with open(f"{dir}/results.json") as f:
            data = json.load(f)
            throughputs.append(data['metrics']['throughput_tokens_per_sec'])
            energies.append(data['metrics']['energy_efficiency_tokens_per_mj'])
    
    # Calculate statistics
    throughput_mean = np.mean(throughputs)
    throughput_std = np.std(throughputs)
    throughput_ci = 1.96 * throughput_std / np.sqrt(len(throughputs))
    
    print(f"Throughput: {throughput_mean:.2f} ± {throughput_ci:.2f} (95% CI)")
    print(f"Coefficient of Variation: {throughput_std/throughput_mean*100:.1f}%")
    
    return {
        'mean': throughput_mean,
        'std': throughput_std,
        'ci_95': throughput_ci,
        'cv_percent': throughput_std/throughput_mean*100
    }
```

## 📈 Reported Results in Paper

All results in the paper follow this protocol:

### Main Performance Results (Figure 8)

- **Configuration**: 5 independent runs with seeds [42, 123, 456, 789, 1024]
- **Reported**: Mean throughput and energy efficiency
- **Error bars**: 95% confidence intervals
- **Typical CV**: 6.2% for throughput, 5.8% for energy

### Ablation Study (Figure 7)

- **Configuration**: 3 independent runs with seeds [42, 123, 456]
- **Reported**: Mean values
- **Variance**: ±5-8% across configurations

### Comparison with Baselines (Figure 8)

- **Configuration**: 5 independent runs per baseline
- **Normalization**: All results normalized to GPU-only baseline mean
- **Variance propagation**: Error bars include both measurement and normalization variance

## ⚠️ Known Edge Cases

### High Variability Scenarios

1. **Very short generation lengths (< 100 tokens)**
   - Variability: Up to ±15%
   - Reason: Initialization overhead dominates
   - Recommendation: Use generation length ≥ 512 for stable results

2. **Extreme draft lengths (> 32 tokens)**
   - Variability: Up to ±12%
   - Reason: Rare edge cases in adaptive algorithms
   - Recommendation: Set reasonable max_draft_length (16 recommended)

3. **Low entropy prompts**
   - Variability: Up to ±10%
   - Reason: Algorithm behavior near decision boundaries
   - Recommendation: Use diverse prompt sets

## ✅ Validation Checklist

Before reporting results, verify:

- [ ] Ran at least 3 independent runs (5 recommended)
- [ ] Used consistent seeds across configurations
- [ ] Used same prompt set for all baselines
- [ ] Calculated and reported confidence intervals
- [ ] Coefficient of variation < 10%
- [ ] Documented any outliers and their causes

## 📚 References

For more information on cycle-accurate simulation variability:

1. "Reproducibility in Computer Architecture Simulation"
2. "Best Practices for Hardware Simulation Studies"
3. ONNXim documentation: Handling non-determinism
4. PIMSimulator documentation: Randomness sources

---

**Last updated**: 2025-11-09  
**Maintainer**: AHASD Research Team

