# Frequently Asked Questions (FAQ)

Common questions and troubleshooting for AHASD.

## 📚 General Questions

### Q: What is AHASD?

**A**: AHASD (Asynchronous Heterogeneous Architecture for LLM Speculative Decoding) is a hardware-software co-design for efficient LLM inference on mobile devices. It combines:
- Task-level asynchronous execution (NPU + PIM)
- Intelligent drafting control (EDC)
- Dynamic pre-verification (TVC)
- In-memory attention operations (AAU)

### Q: What performance improvements can I expect?

**A**: Based on paper results:
- **vs GPU-only**: up to 4.6× throughput, 6.1× energy efficiency
- **vs SpecPIM**: up to 1.5× throughput, 1.24× energy efficiency

Actual results depend on model size, algorithm, and hardware configuration.

### Q: Is this production-ready hardware?

**A**: No. This is a research simulator for architecture evaluation. Not intended for production use.

### Q: Can I use this for my research?

**A**: Yes! The code is open-source. Please cite our work if you use it (paper under review).

---

## 🛠️ Installation & Setup

### Q: What are the minimum system requirements?

**A**: 
- OS: Linux (Ubuntu 20.04+) or macOS 10.15+
- CPU: 4 cores
- RAM: 8 GB
- Disk: 10 GB
- Compiler: GCC 7+ or Clang 10+ (C++17 support)

See [Installation Guide](Installation.md) for details.

### Q: Can I run this on Windows?

**A**: Not natively. Use WSL2 (Windows Subsystem for Linux) or Docker.

```bash
# Install WSL2
wsl --install -d Ubuntu-22.04

# Inside WSL
git clone https://github.com/yourusername/AHASD.git
# Follow Linux installation steps
```

### Q: Build fails with "C++17 not supported"

**A**: Update your compiler:

```bash
# Check current version
g++ --version

# Ubuntu: Install newer GCC
sudo apt-get install g++-11
export CXX=g++-11

# macOS: Update Xcode
xcode-select --install
```

### Q: "Module 'matplotlib' not found"

**A**: Install Python dependencies:

```bash
pip3 install numpy matplotlib pandas

# Or use requirements.txt
pip3 install -r requirements.txt
```

---

## 🚀 Running Experiments

### Q: How long does a simulation take?

**A**: 
- **Quick demo** (mock mode): ~1-2 minutes
- **Cycle-accurate** (real simulation): 30 min - several hours
- Depends on: model size, generation length, hardware

### Q: Can I speed up simulations?

**A**: Yes:
1. Use smaller models (OPT-1.3B vs PaLM-62B)
2. Reduce generation length (`--gen-length 512`)
3. Run in parallel on multiple cores
4. Use mock mode for testing

### Q: What does "mock simulation" mean?

**A**: For quick testing, we provide pre-computed approximate results instead of full cycle-accurate simulation. Useful for validating setup and scripts.

### Q: How do I run real (cycle-accurate) simulations?

**A**: Real simulators require:
1. Building ONNXim and PIMSimulator binaries
2. Model weight files
3. Proper environment setup
4. Longer runtime

See [Experiments Guide](Experiments.md) for details.

---

## ⚙️ Configuration

### Q: Which configuration should I use?

**A**: Start with the template:
```bash
cp configs/ahasd_config_template.json configs/my_exp.json
```

For common use cases, see [Configuration Guide](Configuration.md#configuration-examples).

### Q: How do I enable/disable AHASD components?

**A**: Via command line:

```bash
# Baseline (no AHASD)
python3 scripts/run_single_config.py --model ... --algorithm ...

# With EDC only
python3 scripts/run_single_config.py --model ... --algorithm ... --enable-edc

# Full AHASD
python3 scripts/run_single_config.py --model ... --algorithm ... \
  --enable-edc --enable-tvc --enable-aau
```

Or in config JSON:
```json
{
  "ahasd_configuration": {
    "enable_edc": true,
    "enable_tvc": true,
    "enable_aau": true
  }
}
```

### Q: What's the difference between algorithms?

**A**: Adaptive drafting algorithms:

| Algorithm | Strategy | Best For |
|-----------|----------|----------|
| SpecDec++ | Entropy threshold | Stable workloads |
| SVIP | Incremental parsing | Long sequences |
| AdaEDL | Adaptive learning | Variable context |
| BanditSpec | Multi-armed bandit | Exploration |

Try multiple and compare results.

---

## 📊 Results & Analysis

### Q: Where are my results saved?

**A**: In the `--output` directory you specified:

```
results/my_experiment/
├── config.json       # Configuration snapshot
├── results.json      # JSON format results
├── metrics.txt       # Human-readable metrics
└── trace.csv        # Detailed trace (if enabled)
```

### Q: How do I interpret the metrics?

**A**: Key metrics in `metrics.txt`:

- **Throughput**: Tokens generated per second (higher is better)
- **Energy**: Total energy consumed in mJ (lower is better)
- **Energy Efficiency**: Tokens per mJ (higher is better)
- **Acceptance Rate**: % of drafts accepted (higher is better)
- **Average Draft Length**: Tokens per draft batch

### Q: How do I generate plots?

**A**: Use the analysis script:

```bash
python3 scripts/analyze_ahasd_results.py ./results/

# Outputs:
# results/plots/throughput_comparison.png
# results/plots/energy_efficiency.png
# results/plots/ablation_study.png
# results/plots/summary_table.csv
```

### Q: My results don't match the paper

**A**: Possible reasons:
1. Using mock simulation (not cycle-accurate)
2. Different random seed
3. Different hardware configuration
4. Need longer warmup period

For paper-matching results, use exact configs from paper.

---

## 🔬 Hardware Validation

### Q: How were hardware costs calculated?

**A**: Using:
- **CACTI** for SRAM/register area
- **Yosys + OpenROAD** for logic synthesis
- **28nm** process technology
- Conservative estimates

Run validation:
```bash
python3 scripts/validate_hardware_costs.py
```

### Q: Can I use a different process node?

**A**: Yes, but need to adjust area estimates. The validation script currently supports 28nm. For other nodes, scale area by:
- 14nm: area × 0.25
- 7nm: area × 0.0625
- 5nm: area × 0.031

### Q: What about power consumption?

**A**: Power model includes:
- Static leakage power
- Dynamic switching power
- Frequency-dependent scaling

Total AHASD overhead: ~19.7 mW @ 800MHz

See [Hardware Components](HardwareComponents.md) for details.

---

## 🐛 Troubleshooting

### Q: "Permission denied" error

**A**: Make scripts executable:

```bash
chmod +x scripts/*.sh scripts/*.py
```

### Q: "No such file or directory" for submodules

**A**: Initialize submodules:

```bash
git submodule update --init --recursive
```

### Q: Simulation crashes or hangs

**A**: Check:
1. Enough RAM (8GB minimum)
2. Valid configuration (run validation script)
3. Correct paths in environment variables
4. Log files for error messages

### Q: Results seem incorrect

**A**: Verify:
1. Configuration matches experiment goals
2. Using appropriate model sizes
3. Warmup period is sufficient
4. Random seed is fixed for reproducibility

### Q: Out of memory error

**A**: Solutions:
1. Reduce batch size: `--batch-size 1`
2. Use smaller models
3. Reduce generation length
4. Close other applications
5. Add swap space

---

## 📖 Understanding Components

### Q: What does EDC do?

**A**: Entropy-History-Aware Drafting Control (EDC) uses hardware-based online learning to predict whether drafts will be accepted based on:
- Current prediction entropy
- Historical entropy patterns  
- Number of pending drafts

This suppresses low-quality look-ahead drafting.

### Q: What does TVC do?

**A**: Time-Aware Pre-Verification Control (TVC) models execution time of NPU and PIM to decide when to insert small-batch pre-verification without causing NPU idle.

### Q: What does AAU do?

**A**: Attention Algorithm Unit (AAU) executes nonlinear operators (GELU, Softmax, LayerNorm) directly in PIM memory, reducing data movement overhead.

### Q: Why is task-level async better than operator-level?

**A**: 
- **Operator-level** (SpecPIM): Synchronizes at each operator, causing idle time with variable draft lengths
- **Task-level** (AHASD): DLM and TLM run independently, better parallelism and adaptation to dynamic draft lengths

---

## 🎯 Advanced Usage

### Q: Can I add new algorithms?

**A**: Yes! See [Custom Algorithms](CustomAlgorithms.md) for guide.

### Q: Can I modify hardware parameters?

**A**: Yes, through config files:
```json
{
  "hardware_configuration": {
    "npu": {"frequency_ghz": 1.2},
    "pim": {"num_ranks": 24}
  }
}
```

### Q: Can I use custom models?

**A**: Yes, but need to:
1. Export model to ONNX format
2. Add model config to JSON
3. Place weights in `models/` directory

### Q: Can I run on real hardware?

**A**: The simulator is software-based. For real hardware:
1. FPGA prototyping (future work)
2. ASIC tape-out (requires foundry access)
3. Contact authors for collaboration

---

## 📞 Getting More Help

### Still have questions?

1. **Check documentation**:
   - [Quick Start](QuickStart.md)
   - [Installation](Installation.md)
   - [Configuration](Configuration.md)
   - [Hardware Components](HardwareComponents.md)

2. **Search GitHub Issues**: [Issues](https://github.com/yourusername/AHASD/issues)

3. **Open a new issue**: Provide:
   - Error messages
   - Configuration used
   - System information
   - Steps to reproduce

4. **Email**: your.email@university.edu

---

## 📝 Contributing

### Q: Can I contribute to AHASD?

**A**: Absolutely! We welcome:
- Bug fixes
- New features
- Documentation improvements
- Performance optimizations

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Q: How do I report bugs?

**A**: Open a GitHub issue with:
1. Description of the bug
2. Steps to reproduce
3. Expected vs actual behavior
4. System information
5. Relevant log files

---

## 📚 Academic Usage

### Q: How do I cite this work?

**A**:
```bibtex
@inproceedings{ahasd2024,
  title={AHASD: Asynchronous Heterogeneous Architecture for 
         LLM Speculative Decoding on Mobile Devices},
  author={Your Name and Others},
  booktitle={Conference Name},
  year={2024}
}
```

### Q: Can I use this for my thesis/dissertation?

**A**: Yes! Please cite appropriately and acknowledge the original authors.

### Q: Can I build upon this work?

**A**: Yes! This is open-source research software. We encourage:
- Extensions and improvements
- Integration with other systems
- Novel applications
- Comparative studies

Please cite our work if you use or build upon it.

---

**Last Updated**: November 2024  
**Version**: 1.0

