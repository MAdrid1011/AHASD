# AHASD Reproducibility Guide

This document provides complete step-by-step instructions to reproduce all experimental results from the paper.

## 📋 Prerequisites

### Hardware Requirements

- **CPU**: 16+ cores (Intel Xeon or AMD EPYC recommended)
- **Memory**: 64GB+ RAM
- **Storage**: 500GB+ available space (for simulator outputs)
- **Optional**: NVIDIA GPU (for GPU baseline comparison)

### Software Requirements

```bash
# Operating System
Ubuntu 20.04 LTS or later

# Build tools
sudo apt-get update
sudo apt-get install -y build-essential cmake ninja-build
sudo apt-get install -y gcc-10 g++-10
sudo apt-get install -y python3 python3-pip

# Python dependencies
pip3 install numpy matplotlib pandas jupyter
pip3 install onnx onnxruntime torch
```

## 🔧 Environment Setup

### Step 1: Clone Repository and Initialize Submodules

```bash
git clone https://github.com/your-org/AHASD.git
cd AHASD

# Initialize simulator submodules
git submodule update --init --recursive
```

### Step 2: Build ONNXim Simulator

```bash
cd ONNXim

# Install Conan package manager
pip3 install conan

# Create build directory
mkdir build && cd build

# Configure CMake (enable AHASD support)
cmake .. -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DENABLE_AHASD=ON \
    -DCMAKE_CXX_COMPILER=g++-10 \
    -DCMAKE_C_COMPILER=gcc-10

# Build (may take 10-20 minutes)
ninja -j$(nproc)

# Verify build
./onnxim_main --version
# Should output: ONNXim v1.0 (AHASD enabled)

cd ../..
```

### Step 3: Build PIMSimulator

```bash
cd PIMSimulator

# Build using SCons
scons -j$(nproc)

# Verify build
./build/pim_simulator --help

cd ..
```

### Step 4: Download Model Weights

```bash
# Create model directory
mkdir -p ONNXim/models/language_models

cd ONNXim/models/language_models

# Download and convert models (requires significant disk space)
# OPT models
python3 ../../scripts/generate_transformer_onnx.py \
    --model facebook/opt-1.3b \
    --output opt-1.3b

python3 ../../scripts/generate_transformer_onnx.py \
    --model facebook/opt-6.7b \
    --output opt-6.7b

# LLaMA2 models
python3 ../../scripts/generate_transformer_onnx.py \
    --model meta-llama/Llama-2-7b-hf \
    --output llama2-7b

python3 ../../scripts/generate_transformer_onnx.py \
    --model meta-llama/Llama-2-13b-hf \
    --output llama2-13b

# PaLM models
python3 ../../scripts/generate_transformer_onnx.py \
    --model google/palm-8b \
    --output palm-8b

python3 ../../scripts/generate_transformer_onnx.py \
    --model google/palm-62b \
    --output palm-62b

cd ../../..
```

## 🧪 Running Experiments

### Quick Test (Single Configuration)

Verify environment setup is correct:

```bash
# Run quick test with single configuration
./tools/dev/run_single_config.py \
    --model llama2-7b:llama2-13b \
    --algorithm adaedl \
    --config ahasd_full \
    --output results/quick_test

# Check results
cat results/quick_test/metrics.txt
```

Expected output should include:
- Throughput: ~40-50 tokens/sec
- Energy Efficiency: ~0.18-0.22 tokens/mJ
- Draft Acceptance Rate: ~70-80%
- EDC Prediction Accuracy: ~80-85%

### Full Experiment Suite

Run all experiments from the paper:

```bash
# Set environment variables
export ONNXIM_HOME=$(pwd)/ONNXim
export PIM_SIM_HOME=$(pwd)/PIMSimulator

# Run full experiments (may take 24-48 hours)
./tools/dev/run_ahasd_simulation.sh

# Results will be saved in results/ahasd_YYYYMMDD_HHMMSS/
```

Experiments include:
- 3 model configurations (Small, Medium, Large)
- 4 adaptive algorithms (SpecDec++, SVIP, AdaEDL, BanditSpec)
- 5 system configurations (ablation study)
- **Total**: 60 experiment configurations

### Parallel Execution (Accelerated)

If you have a multi-core CPU, run experiments in parallel:

```bash
# Modify script to enable parallel execution
vim tools/dev/run_ahasd_simulation.sh
# Change run_simulation function calls to background execution:
# run_simulation ... &

# Or use GNU Parallel
parallel -j 8 ./tools/dev/run_single_config.py ::: \
    llama2-7b:llama2-13b \
    opt-1.3b:opt-6.7b \
    palm-8b:palm-62b
```

## 📊 Results Analysis

### Generate Plots

```bash
# Analyze results and generate paper figures
python3 tools/dev/analyze_ahasd_results.py results/ahasd_*/

# Outputs:
# - plots/throughput_comparison.png  (Figure 7a)
# - plots/energy_efficiency.png      (Figure 7b)
# - plots/ablation_study.png         (Figure 6)
# - plots/summary_table.csv          (Table 3)
```

### Verify Hardware Overhead

```bash
# Verify hardware overhead claims from paper
python3 scripts/validate_hardware_costs.py

# Should output:
# EDC: 0.0002 mm² ✓
# TVC: 0.0002 mm² ✓
# AAU: 0.4500 mm² ✓
# Total: 0.4515 mm² (2.51% of DRAM) ✓
```

## 📈 Expected Results

### Throughput Improvement (vs GPU-only baseline)

| Model Config | SpecDec++ | SVIP | AdaEDL | BanditSpec |
|-------------|-----------|------|--------|------------|
| OPT Small | 3.6× | 3.8× | 4.0× | 4.2× |
| LLaMA2 Medium | 3.0× | 3.3× | 3.5× | 3.7× |
| PaLM Large | 2.6× | 2.9× | 3.1× | 3.3× |

### Energy Efficiency Improvement (vs GPU-only baseline)

| Model Config | SpecDec++ | SVIP | AdaEDL | BanditSpec |
|-------------|-----------|------|--------|------------|
| OPT Small | 4.8× | 5.1× | 5.3× | 5.6× |
| LLaMA2 Medium | 4.1× | 4.4× | 4.7× | 4.9× |
| PaLM Large | 3.5× | 3.8× | 4.1× | 4.3× |

### Ablation Study (LLaMA2-7B, AdaEDL)

| Configuration | Throughput | Energy Efficiency |
|--------------|------------|-------------------|
| Baseline (GPU-only) | 1.0× | 1.0× |
| NPU+PIM | 2.2× | 1.9× |
| +AAU | 2.7× | 2.6× |
| +EDC | 3.4× | 4.5× |
| +TVC (Full) | 3.8× | 5.5× |

**Note**: Actual results may vary by ±10% due to:
- Randomness in model quantization
- Random sampling in adaptive algorithms
- Initialization state of simulators

## 🐛 Troubleshooting

### Issue 1: ONNXim Build Fails

```bash
# Check C++ compiler version
g++ --version  # Should be 10.0 or higher

# Clean and rebuild
cd ONNXim/build
rm -rf *
cmake .. -G Ninja -DCMAKE_BUILD_TYPE=Release -DENABLE_AHASD=ON
ninja -j$(nproc)
```

### Issue 2: Model Download Fails

```bash
# Use proxy (if in China)
export HF_ENDPOINT=https://hf-mirror.com

# Or manually download models
# Visit Hugging Face and manually download, then place in ONNXim/models/language_models/
```

### Issue 3: Simulator Runs Slowly

```bash
# Enable optimizations
export ONNXIM_OPT_LEVEL=3
export OMP_NUM_THREADS=$(nproc)

# Reduce logging output
./onnxim_main --log_level info  # instead of debug or trace
```

### Issue 4: Out of Memory

```bash
# Reduce batch size
vim configs/ahasd_config_template.json
# Change "batch_size": 1 to smaller value

# Or increase swap
sudo fallocate -l 64G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

## 📝 Verification Checklist

After running experiments, verify the following:

- [ ] All 60 configurations completed successfully
- [ ] Each configuration directory contains `metrics.txt` and `results.json`
- [ ] Throughput improvement within expected range (2.6×-4.2×)
- [ ] Energy efficiency improvement within expected range (3.5×-5.6×)
- [ ] Hardware overhead verification passes (< 3% DRAM die)
- [ ] Plots generated successfully and resemble paper figures

## 🆘 Getting Help

If you encounter issues:

1. Check `results/*/simulation.log` for detailed error messages
2. Run diagnostic script: `./tools/dev/test_e2e.sh`
3. Review FAQ: `docs/FAQ.md`
4. Submit Issue: https://github.com/your-org/AHASD/issues

## 📄 Citation

If you use this code, please cite:

```bibtex
@inproceedings{ahasd2024,
  title={AHASD: Asynchronous Heterogeneous Architecture for LLM Speculative Decoding on Mobile Devices},
  author={Your Name et al.},
  booktitle={Conference Name},
  year={2024}
}
```

## 📅 Changelog

- **November 2024**: Initial release
- **November 2024**: Added simulator-backed experiment flow

## 🔒 License

This project is licensed under the Apache 2.0 License - see the LICENSE file for details.

## 🙏 Acknowledgments

- ONNXim team at KAIST
- Samsung PIMSimulator team
- Research supported by [Your funding sources]

## 📧 Contact

For questions or collaboration:
- Email: your-email@university.edu
- GitHub Issues: https://github.com/your-org/AHASD/issues
- Project Website: https://ahasd-project.org

---

**Last Updated**: November 9, 2024  
**Version**: 2.0  
**Maintainers**: AHASD Research Team  
**Estimated Setup Time**: 4-6 hours  
**Estimated Full Reproduction Time**: 24-48 hours
