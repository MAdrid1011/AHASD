# AHASD: Asynchronous Heterogeneous Architecture for LLM Speculative Decoding

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-NPU%2BPIM-green.svg)]()
[![Hardware](https://img.shields.io/badge/Hardware%20Overhead-%3C3%25-brightgreen.svg)]()

Research implementation of **AHASD: Asynchronous Heterogeneous Architecture for LLM Speculative Decoding on Mobile Devices**.


---

## 🎯 Key Features

- **Task-Level Async Execution**: Decouples DLM (PIM) and TLM (NPU) for better parallelism
- **EDC (Entropy-History-Aware Control)**: Hardware online learning to suppress low-confidence drafts
- **TVC (Time-Aware Pre-Verification)**: Dynamic pre-verification based on runtime modeling
- **AAU (Attention Algorithm Unit)**: In-memory nonlinear operations
- **Sub-μs Task Switching**: Fast drafting/verification switching
- **Minimal Overhead**: 2.5% of DRAM die area

---

## 🏗️ Architecture

AHASD integrates three platforms:

- **ONNXim**: NPU simulator for TLM verification
- **PIMSimulator**: LPDDR5-PIM for DLM drafting  
- **XiangShan**: RISC-V CPU for control logic (EDC/TVC)

```
┌──────────┐       ┌──────────┐       ┌──────────┐
│   NPU    │◄─────►│   CPU    │◄─────►│   PIM    │
│  (TLM)   │       │ (Control)│       │  (DLM)   │
└──────────┘       └──────────┘       └──────────┘
     ▲                   │                   ▲
     │              ┌────┴────┐              │
     └──────────────┤  Queues ├──────────────┘
                    └─────────┘
```

---

## 📊 Performance

| Baseline | Throughput | Energy Efficiency |
|----------|------------|-------------------|
| vs GPU-only | up to **4.2×** | up to **5.6×** |
| vs SpecPIM | up to **1.5×** | up to **1.24×** |

### Hardware Overhead

| Component | Area | % DRAM |
|-----------|------|--------|
| EDC + TVC | 0.0004 mm² | <0.1% |
| AAU | 0.45 mm² | 2.5% |
| Queues + Scheduler | 0.001 mm² | <0.1% |
| **Total** | **0.45 mm²** | **2.5%** |

---

## 🚀 Quick Start

### Installation

```bash

# Build ONNXim
cd ONNXim && mkdir build && cd build && cmake .. && make -j8

# Build PIMSimulator  
cd ../../PIMSimulator && scons -j8
```

### Run Demo

```bash
python3 scripts/run_single_config.py \
  --model llama2-7b-llama2-13b \
  --algorithm adaedl \
  --enable-edc --enable-tvc --enable-aau \
  --output ./results/demo

# View results
cat results/demo/metrics.txt
```

### Validate Hardware

```bash
python3 scripts/validate_hardware_costs.py
# Expected: ✓ Overhead = 2.5% < 3%
```

---

## 🏛️ Repository Structure

```
AHASD/
├── ONNXim/                     # NPU simulator
│   └── src/async_queue/        # EDC, TVC, queues
├── PIMSimulator/               # PIM simulator
│   └── src/                    # AAU, scheduler
├── XiangShan/                  # RISC-V CPU
│   └── src/main/scala/         # Control modules
├── scripts/                    # Experiments
├── configs/                    # Configurations
├── docs/                       # Documentation
└── results/                    # Outputs
```

---

## 📖 Documentation

- [Quick Start](docs/QuickStart.md) - Get started in 5 minutes
- [Installation](docs/Installation.md) - Detailed setup
- [Configuration](docs/Configuration.md) - Customize experiments
- [Hardware Components](docs/HardwareComponents.md) - EDC, TVC, AAU specs
- [Experiments](docs/Experiments.md) - Reproduce results
- [FAQ](docs/FAQ.md) - Common questions

---

## 🧪 Supported Configurations

### Models
- **Small**: OPT-1.3B → OPT-6.7B
- **Medium**: LLaMA2-7B → LLaMA2-13B
- **Large**: PaLM-8B → PaLM-62B

### Algorithms
- SpecDec++, SVIP, AdaEDL, BanditSpec

### Hardware
**NPU**: 128×128 systolic, 16 TFLOPS @ 1GHz  
**PIM**: 16 ranks LPDDR5, 102.4 GOPS INT8  
**CPU**: XiangShan RISC-V for control

---

## 📄 Citation

Paper under review. Please cite:

```bibtex
@article{ahasd2024,
  title={AHASD: Asynchronous Heterogeneous Architecture for 
         LLM Speculative Decoding on Mobile Devices},
  author={Anonymous},
  journal={Under Review},
  year={2024}
}
```

---

## 🤝 Contributing

We welcome contributions! See [CONTRIBUTING.md](docs/CONTRIBUTING.md).

---

## 🙏 Acknowledgments

Built upon:
- [ONNXim](https://github.com/PSAL-POSTECH/ONNXim) - NPU simulation
- [PIMSimulator](https://github.com/SAITPublic/PIMSimulator) - PIM simulation
- [XiangShan](https://github.com/OpenXiangShan/XiangShan) - RISC-V processor

---

## 📜 License

Apache License 2.0. See [LICENSE](LICENSE) for details.

---

## 📧 Contact

- Issues: [GitHub Issues](https://github.com/yourusername/AHASD/issues)
- Discussions: [GitHub Discussions](https://github.com/yourusername/AHASD/discussions)

---

<p align="center">
  Made for advancing LLM inference on mobile devices
</p>
