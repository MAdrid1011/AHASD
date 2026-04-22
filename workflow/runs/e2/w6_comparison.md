# W6 / W11 synthesis comparison

The DAC baseline column reproduces the submission numbers. The W11 column applies INT8 precision + reduction/control resource sharing to the AAU sub-modules, per AHASDFix.md §W11 goal of ≤ 2% die overhead.

| 模块 | DAC 基线 面积 (mm²) | DAC 基线 功耗 (mW) | W11 优化 面积 (mm²) | W11 优化 功耗 (mW) | Δ 面积 | Δ 功耗 |
|------|:------------------:|:------------------:|:------------------:|:------------------:|:------:|:------:|
| EDC | 0.0001 | 0.153 | 0.0001 | 0.153 | +0.0% | +0.0% |
| TVC | 0.0002 | 0.456 | 0.0002 | 0.456 | +0.0% | +0.0% |
| AsyncQueue | 0.0014 | 0.976 | 0.0014 | 0.976 | +0.0% | +0.0% |
| GTSU | 0.0000 | 0.039 | 0.0000 | 0.039 | +0.0% | +0.0% |
| AAU | 1.2500 | 23.495 | 0.7070 | 13.952 | -43.4% | -40.6% |
| **Total** | **1.2517** | **25.118** | **0.7087** | **15.575** | **-43.4%** | **-38.0%** |

**Die overhead** (LPDDR5 die = 50 mm²): DAC baseline 2.50% → W11 optimised 1.42%.
