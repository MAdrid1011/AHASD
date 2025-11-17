# Quick Start Guide

Get started with AHASD simulator in 5 minutes.

## 📦 Installation

### 1. Clone the Repository

```bash
cd AHASD
```

### 2. Install Dependencies

```bash
# System dependencies
sudo apt-get update
sudo apt-get install -y g++ cmake scons python3 python3-pip

# Python packages
pip3 install numpy matplotlib pandas
```

### 3. Build Simulators

```bash
# Build simulators
cd ONNXim && mkdir build && cd build
cmake .. && make -j8

cd ../../PIMSimulator
scons -j8

cd ..

# XiangShan build (optional, for control logic verification)
# cd XiangShan && make
```

## 🚀 Run Your First Experiment

### Option 1: Quick Demo

Run a pre-configured demo with LLaMA2-7B/13B:

```bash
python3 scripts/run_single_config.py \
  --model llama2-7b-llama2-13b \
  --algorithm adaedl \
  --enable-edc \
  --enable-tvc \
  --enable-aau \
  --output ./results/quickstart_demo
```

**Expected Runtime**: ~2 minutes (mock simulation)

### Option 2: Validate Hardware Costs

Verify the hardware overhead claims from the paper:

```bash
python3 scripts/validate_hardware_costs.py
```

**Expected Output**:
```
======================================================================
AHASD HARDWARE COST VALIDATION
Process: 28nm | Tool: CACTI + Yosys + OpenROAD
======================================================================

...

Validation:
  AHASD Overhead:    2.51%
  Paper Claim:       < 3%
  ✓ Claim VALIDATED (overhead = 2.51% < 3%)
```

## 📊 View Results

### Check Metrics

```bash
cat results/quickstart_demo/metrics.txt
```

Sample output:
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
```

### View Configuration

```bash
cat results/quickstart_demo/config.json
```

## 🎯 Common Use Cases

### 1. Ablation Study

Test individual components:

```bash
# Baseline (no AHASD)
python3 scripts/run_single_config.py \
  --model llama2-7b-llama2-13b \
  --algorithm adaedl \
  --output ./results/baseline

# With EDC only
python3 scripts/run_single_config.py \
  --model llama2-7b-llama2-13b \
  --algorithm adaedl \
  --enable-edc \
  --output ./results/with_edc

# With EDC + TVC
python3 scripts/run_single_config.py \
  --model llama2-7b-llama2-13b \
  --algorithm adaedl \
  --enable-edc \
  --enable-tvc \
  --output ./results/with_edc_tvc

# Full AHASD
python3 scripts/run_single_config.py \
  --model llama2-7b-llama2-13b \
  --algorithm adaedl \
  --enable-edc \
  --enable-tvc \
  --enable-aau \
  --output ./results/full_ahasd
```

### 2. Compare Algorithms

Test different adaptive drafting algorithms:

```bash
for algo in specdec svip adaedl banditspec; do
  python3 scripts/run_single_config.py \
    --model llama2-7b-llama2-13b \
    --algorithm $algo \
    --enable-edc --enable-tvc --enable-aau \
    --output ./results/algo_$algo
done
```

### 3. Multi-Model Evaluation

```bash
# Small model
python3 scripts/run_single_config.py \
  --model opt-1.3b-opt-6.7b \
  --algorithm adaedl \
  --enable-edc --enable-tvc --enable-aau \
  --output ./results/small

# Medium model  
python3 scripts/run_single_config.py \
  --model llama2-7b-llama2-13b \
  --algorithm adaedl \
  --enable-edc --enable-tvc --enable-aau \
  --output ./results/medium

# Large model
python3 scripts/run_single_config.py \
  --model palm-8b-palm-62b \
  --algorithm adaedl \
  --enable-edc --enable-tvc --enable-aau \
  --output ./results/large
```

## 📈 Analyze Results

After running experiments, generate plots and tables:

```bash
# Analyze all results in the results directory
python3 scripts/analyze_ahasd_results.py ./results/

# Outputs will be in ./results/plots/
ls results/plots/
# throughput_comparison.png
# energy_efficiency.png
# ablation_study.png
# summary_table.csv
```

## 🐛 Troubleshooting

### Build Errors

**Problem**: `cmake: command not found`
```bash
sudo apt-get install cmake
```

**Problem**: `g++: error: unrecognized command line option '-std=c++17'`
```bash
# Update g++ to version 7 or higher
sudo apt-get install g++-9
export CXX=g++-9
```

### Runtime Errors

**Problem**: `ModuleNotFoundError: No module named 'matplotlib'`
```bash
pip3 install matplotlib numpy pandas
```

**Problem**: `Permission denied: ./scripts/run_ahasd_simulation.sh`
```bash
chmod +x scripts/*.sh scripts/*.py
```

### Simulation Issues

**Problem**: Simulation takes too long
- This is a cycle-accurate simulator; for quick testing, use mock mode
- Reduce `--gen-length` parameter
- Use smaller models

**Problem**: Out of memory
- Reduce batch size: `--batch-size 1`
- Use smaller models
- Close other applications

## 📚 Next Steps

- **[Configuration Guide](Configuration.md)**: Customize experiments
- **[Hardware Components](HardwareComponents.md)**: Learn about EDC, TVC, AAU
- **[Experiments](Experiments.md)**: Reproduce all paper results
- **[FAQ](FAQ.md)**: More troubleshooting tips

## 💡 Tips

1. **Start Small**: Begin with small models and short generation lengths
2. **Use Mock Mode**: For quick testing, the simulator uses mock execution
3. **Check Logs**: Enable verbose logging with `--verbose` flag
4. **Parallel Runs**: Run multiple configurations in parallel to save time
5. **Save Configs**: Keep successful configurations for future reference

## 🎓 Learning Path

1. ✅ **Quick Start** (You are here!)
2. 📖 [Installation Guide](Installation.md) - Detailed setup
3. ⚙️ [Configuration Guide](Configuration.md) - Customize settings
4. 🏗️ [Simulator Architecture](SimulatorArchitecture.md) - Understand internals
5. 🔬 [Experiments](Experiments.md) - Reproduce paper results

---

**Need Help?** Open an issue on [GitHub](https://github.com/yourusername/AHASD/issues) or check the [FAQ](FAQ.md).

