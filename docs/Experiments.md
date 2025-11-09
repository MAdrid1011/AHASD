# Experiments Guide

Reproduce key results from AHASD.

## 📋 Overview

This guide shows how to reproduce the main experimental results:

1. **Main Results**: Throughput and energy efficiency vs baselines
2. **Ablation Study**: Contribution of each component
3. **Scalability Analysis**: Performance across model sizes
4. **Algorithm Comparison**: Different adaptive drafting strategies

---

## 🎯 Main Results

### Experiment 1: vs GPU-only Baseline

Compare AHASD with sequential execution on GPU.

```bash
# Run full evaluation suite
./scripts/run_ahasd_simulation.sh

# This runs:
# - 3 model sizes (Small/Medium/Large)
# - 4 algorithms (SpecDec++/SVIP/AdaEDL/BanditSpec)
# - 5 configurations (Baseline/NPU+PIM/+AAU/+EDC/Full)
# = 60 total configurations
```

**Expected Runtime**: 30-60 minutes (mock mode)

**Results Location**: `results/ahasd_TIMESTAMP/`

### Experiment 2: vs SpecPIM Baseline

Compare with state-of-the-art operator-level parallelism.

```bash
# Run comparison with SpecPIM baseline
for model in opt-1.3b-opt-6.7b llama2-7b-llama2-13b palm-8b-palm-62b; do
  for algo in specdec svip adaedl banditspec; do
    # SpecPIM (operator-level sync)
    python3 scripts/run_single_config.py \
      --model $model \
      --algorithm $algo \
      --output ./results/specpim_${model}_${algo}
    
    # AHASD (task-level async)
    python3 scripts/run_single_config.py \
      --model $model \
      --algorithm $algo \
      --enable-edc --enable-tvc --enable-aau \
      --output ./results/ahasd_${model}_${algo}
  done
done
```

### Expected Results

| Baseline | Throughput | Energy Efficiency |
|----------|------------|-------------------|
| vs GPU-only | 2.8-4.6× | 3.5-6.1× |
| vs SpecPIM | 1.2-1.5× | 1.15-1.24× |

---

## 🔬 Ablation Study

Evaluate contribution of each AHASD component.

### Experiment 3: Component Ablation

```bash
# Model: LLaMA2-7B → LLaMA2-13B
# Algorithm: AdaEDL

# 1. Baseline (GPU-only)
python3 scripts/run_single_config.py \
  --model llama2-7b-llama2-13b \
  --algorithm adaedl \
  --output ./results/ablation/baseline

# 2. NPU+PIM (task-level async only)
python3 scripts/run_single_config.py \
  --model llama2-7b-llama2-13b \
  --algorithm adaedl \
  --output ./results/ablation/npu_pim

# 3. NPU+PIM+AAU
python3 scripts/run_single_config.py \
  --model llama2-7b-llama2-13b \
  --algorithm adaedl \
  --enable-aau \
  --output ./results/ablation/npu_pim_aau

# 4. NPU+PIM+AAU+EDC
python3 scripts/run_single_config.py \
  --model llama2-7b-llama2-13b \
  --algorithm adaedl \
  --enable-aau --enable-edc \
  --output ./results/ablation/npu_pim_aau_edc

# 5. AHASD Full (all components)
python3 scripts/run_single_config.py \
  --model llama2-7b-llama2-13b \
  --algorithm adaedl \
  --enable-edc --enable-tvc --enable-aau \
  --output ./results/ablation/ahasd_full
```

### Expected Ablation Results

| Configuration | Throughput Gain | Energy Efficiency Gain |
|---------------|-----------------|------------------------|
| Baseline | 1.0× | 1.0× |
| NPU+PIM | 2.2× | 1.9× |
| +AAU | 2.7× | 2.6× |
| +EDC | 3.4× | 4.5× |
| +TVC (Full) | 3.8× | 5.5× |

### Analyze Ablation Results

```bash
python3 scripts/analyze_ahasd_results.py ./results/ablation/

# Generates:
# results/ablation/plots/ablation_study.png
# results/ablation/plots/summary_table.csv
```

---

## 📊 Scalability Analysis

Test performance across different model sizes.

### Experiment 4: Model Size Scaling

```bash
# Small Models
python3 scripts/run_single_config.py \
  --model opt-1.3b-opt-6.7b \
  --algorithm adaedl \
  --enable-edc --enable-tvc --enable-aau \
  --output ./results/scaling/small

# Medium Models
python3 scripts/run_single_config.py \
  --model llama2-7b-llama2-13b \
  --algorithm adaedl \
  --enable-edc --enable-tvc --enable-aau \
  --output ./results/scaling/medium

# Large Models
python3 scripts/run_single_config.py \
  --model palm-8b-palm-62b \
  --algorithm adaedl \
  --enable-edc --enable-tvc --enable-aau \
  --output ./results/scaling/large
```

### Expected Scaling Results

| Model Size | Throughput (tok/s) | Energy Eff. (tok/mJ) |
|------------|-------------------|----------------------|
| Small (1.3B→6.7B) | 78.5 | 0.324 |
| Medium (7B→13B) | 45.2 | 0.193 |
| Large (8B→62B) | 12.8 | 0.098 |

---

## 🧪 Algorithm Comparison

Compare different adaptive drafting algorithms.

### Experiment 5: Algorithm Evaluation

```bash
# Test all algorithms with LLaMA2-7B/13B
for algo in specdec svip adaedl banditspec; do
  python3 scripts/run_single_config.py \
    --model llama2-7b-llama2-13b \
    --algorithm $algo \
    --enable-edc --enable-tvc --enable-aau \
    --output ./results/algorithms/ahasd_$algo
done
```

### Expected Algorithm Results

| Algorithm | Avg. Draft Length | Acceptance Rate | Throughput |
|-----------|------------------|-----------------|------------|
| SpecDec++ | 4.8 | 68.5% | 42.3 tok/s |
| SVIP | 5.5 | 72.1% | 46.8 tok/s |
| AdaEDL | 5.2 | 74.9% | 45.2 tok/s |
| BanditSpec | 6.1 | 66.3% | 44.1 tok/s |

---

## 🔍 Detailed Analysis Experiments

### Experiment 6: EDC Effectiveness

Study EDC prediction accuracy and draft suppression.

```bash
# Vary EDC parameters
for pht_size in 256 512 1024; do
  python3 scripts/run_single_config.py \
    --model llama2-7b-llama2-13b \
    --algorithm adaedl \
    --enable-edc --enable-tvc --enable-aau \
    --config-override "edc_parameters.pht_size=$pht_size" \
    --output ./results/edc_study/pht_$pht_size
done
```

**Metrics to Analyze**:
- Prediction accuracy
- Suppression rate
- False positive/negative rates

### Experiment 7: TVC Timing Analysis

Study pre-verification insertion decisions.

```bash
# Vary TVC parameters
for min_preverify in 1 2 4; do
  python3 scripts/run_single_config.py \
    --model llama2-7b-llama2-13b \
    --algorithm adaedl \
    --enable-edc --enable-tvc --enable-aau \
    --config-override "tvc_parameters.min_preverify_length=$min_preverify" \
    --output ./results/tvc_study/min_preverify_$min_preverify
done
```

**Metrics to Analyze**:
- Pre-verification count
- NPU idle prevention rate
- Timing prediction accuracy

### Experiment 8: Hardware Frequency Sweep

Test performance at different frequencies.

```bash
# Sweep NPU frequencies
for npu_freq in 800 1000 1200 1400; do
  python3 scripts/run_single_config.py \
    --model llama2-7b-llama2-13b \
    --algorithm adaedl \
    --enable-edc --enable-tvc --enable-aau \
    --npu-freq $npu_freq \
    --output ./results/freq_sweep/npu_${npu_freq}mhz
done

# Sweep PIM frequencies
for pim_freq in 600 800 1000 1200; do
  python3 scripts/run_single_config.py \
    --model llama2-7b-llama2-13b \
    --algorithm adaedl \
    --enable-edc --enable-tvc --enable-aau \
    --pim-freq $pim_freq \
    --output ./results/freq_sweep/pim_${pim_freq}mhz
done
```

---

## 📈 Generate Paper Figures

### Figure 5: Throughput Comparison

```bash
# Run all baselines and AHASD
./scripts/run_ahasd_simulation.sh

# Generate plot
python3 scripts/analyze_ahasd_results.py ./results/ahasd_*/

# Output: results/plots/throughput_comparison.png
```

### Figure 6: Energy Efficiency

```bash
# Same data as Figure 5
python3 scripts/plot_energy_efficiency.py ./results/ahasd_*/

# Output: results/plots/energy_efficiency.png
```

### Figure 7: Ablation Study

```bash
# Run ablation experiments (Experiment 3)
# Then generate plot
python3 scripts/plot_ablation.py ./results/ablation/

# Output: results/plots/ablation_study.png
```

### Table 3: Hardware Overhead

```bash
# Validate hardware costs
python3 scripts/validate_hardware_costs.py > results/hardware_costs.txt

# Automatically formatted for paper
```

---

## 🎨 Custom Experiments

### Template for Custom Experiments

```bash
#!/bin/bash
# custom_experiment.sh

# Define experiment parameters
MODEL="llama2-7b-llama2-13b"
ALGORITHM="adaedl"
OUTPUT_BASE="./results/custom_exp"

# Run experiments
for param in value1 value2 value3; do
  python3 scripts/run_single_config.py \
    --model $MODEL \
    --algorithm $ALGORITHM \
    --enable-edc --enable-tvc --enable-aau \
    --custom-param $param \
    --output $OUTPUT_BASE/param_$param
done

# Analyze results
python3 scripts/analyze_ahasd_results.py $OUTPUT_BASE/

echo "Experiment complete! Results in $OUTPUT_BASE/plots/"
```

---

## 📊 Results Format

### Metrics File (`metrics.txt`)

```
=== AHASD Simulation Results ===
Configuration: llama2_7b_13b_adaedl

Performance Metrics:
- Total Cycles: 15234567
- Throughput: 45.2 tokens/sec
- Energy: 234.5 mJ
- Energy Efficiency: 0.193 tokens/mJ

Draft Statistics:
- Total Drafts Generated: 2048
- Total Drafts Accepted: 1534 (74.9%)
- Average Draft Length: 5.2
- Average Entropy: 2.34

EDC Statistics:
- Prediction Accuracy: 82.3%
- Suppression Rate: 15.6%

TVC Statistics:
- Pre-verifications Inserted: 156
- Prevented NPU Idles: 142
- Success Rate: 91.0%
```

### CSV Export

```bash
# Export to CSV for Excel/plotting
python3 scripts/export_results.py ./results/ahasd_*/ \
  --output results_summary.csv
```

---

## ✅ Validation Checklist

Before claiming reproduction:

- [ ] Hardware costs validated (`validate_hardware_costs.py`)
- [ ] Baseline experiments complete
- [ ] Ablation study complete
- [ ] Multiple random seeds tested
- [ ] Results within expected ranges
- [ ] Figures generated successfully
- [ ] Statistical significance verified

---

## 🐛 Troubleshooting

### Inconsistent Results

**Problem**: Results vary between runs

**Solution**:
```bash
# Fix random seed
--random-seed 42

# Longer warmup
--warmup-tokens 256

# Average over multiple runs
for seed in 42 43 44 45 46; do
  python3 scripts/run_single_config.py ... --random-seed $seed
done
python3 scripts/average_results.py ./results/*/
```

### Out of Memory

**Problem**: Simulation crashes with OOM

**Solution**:
```bash
# Reduce generation length
--gen-length 512

# Use smaller batch size
--batch-size 1

# Close other applications
# Add swap space if needed
```

### Slow Simulation

**Problem**: Takes too long

**Solution**:
1. Use mock mode for testing
2. Run parallel experiments
3. Reduce model size
4. Shorter generation length

---

## 📞 Getting Help

- **Issues with results**: Check [FAQ](FAQ.md#results--analysis)
- **Configuration problems**: See [Configuration Guide](Configuration.md)
- **Technical questions**: Open [GitHub Issue](https://github.com/yourusername/AHASD/issues)

---

## 📚 Next Steps

After running experiments:
1. Analyze results with provided scripts
2. Generate paper figures
3. Compare with baselines
4. Explore custom configurations

See [Analysis Guide](Analysis.md) for detailed analysis techniques.

