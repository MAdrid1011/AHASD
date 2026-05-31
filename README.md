# AHASD: Asynchronous Heterogeneous Architecture for LLM Adaptive Drafting Speculative Decoding

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-NPU%2BPIM-green.svg)]()
[![Hardware](https://img.shields.io/badge/Hardware%20Overhead-%3C3%25-brightgreen.svg)]()

Research implementation of **AHASD: Asynchronous Heterogeneous Architecture for LLM Adaptive Drafting Speculative Decoding on Mobile Devices**.


---

## 🎯 Key Features

- **Task-Level Async Execution**: Decouples DLM (PIM) and TLM (NPU) for better parallelism
- **EDC (Entropy-History-Aware Control)**: Hardware online learning to suppress low-confidence drafts
- **TVC (Time-Aware Pre-Verification)**: Dynamic pre-verification based on runtime modeling
- **AAU (Attention Algorithm Unit)**: In-memory nonlinear operations
- **Sub-μs Task Switching**: Fast drafting/verification switching
- **Small Hardware Cost**: 0.901 mm² total area with 12.10 mW dynamic and 3.838 mW static power

---

## 🏗️ Architecture

AHASD integrates simulator-backed accelerator models with a replayable host control plane:

- **ONNXim**: NPU simulator for TLM verification
- **PIMSimulator**: LPDDR5-PIM for DLM drafting  
- **Control-plane replay**: EDC/TVC and scheduling decisions driven by traced model and workload inputs

```
┌──────────┐       ┌──────────┐       ┌──────────┐
│   NPU    │◄─────►│   Host   │◄─────►│   PIM    │
│  (TLM)   │       │ Control  │       │  (DLM)   │
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
| EDC + TVC + VSKM | 0.000413 mm² | <0.1% |
| AAU + DDBC | 0.900587 mm² | design overhead |
| Queues + Scheduler | included above | design overhead |
| **Total** | **0.901 mm²** | **12.10 mW dyn / 3.838 mW stat** |

---

## 🚀 Quick Start

### Installation

```bash

# Build ONNXim (requires Conan 1.x: pip3 install "conan<2")
cd ONNXim && ./scripts/build_onnxim.sh

# Build PIMSimulator
cd ../../PIMSimulator && scons -j8
```

### Reproduce Paper Data

```bash
python3 scripts/reproduce_paper_data.py \
  --execution-mode fast-replay \
  --output-dir reproducibility/generated \
  --timeout-s 900
```

### Validate Hardware

```bash
python3 scripts/validate_hardware_costs.py
# The canonical hardware table is emitted by scripts/hardware_cost_model.py.
```

---

## 🏛️ Repository Structure

```
AHASD/
├── ONNXim/                     # NPU simulator
│   └── src/async_queue/        # EDC, TVC, queues
├── PIMSimulator/               # PIM simulator
│   └── src/                    # AAU, scheduler
├── reproducibility/            # Public reproduction entrypoint and manifest
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
**Host Control**: replayed EDC/TVC and scheduler decisions from model, workload, and simulator counters

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
