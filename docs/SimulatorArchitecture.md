# AHASD Simulator Platform

本文档介绍如何使用 AHASD 模拟器平台来重现论文中的实验结果。

## 架构概述

AHASD 模拟器平台集成了两个开源的周期精确模拟器:

1. **ONNXim** - 用于模拟移动 NPU
2. **PIMSimulator (SAIT)** - 用于模拟 LPDDR5-PIM

我们在这两个模拟器的基础上实现了以下 AHASD 关键组件:

### 核心组件

#### 1. 异步队列系统 (`ONNXim/src/async_queue/AsyncQueue.h`)
- **Unverified Draft Queue**: 存储 PIM 生成的待验证 token 批次
- **Feedback Queue**: 存储 TLM 验证结果
- **Pre-verification Queue**: 标记需要在 PIM 内预验证的草稿

#### 2. EDC 模块 (`ONNXim/src/async_queue/EDC.h`)
**Entropy-History-Aware Drafting Control**
- Local Entropy History Table (LEHT): 8 个条目
- Local Commit Entropy History Table (LCEHT): 8 个条目
- Leading Length Register (LLR): 3-bit 计数器
- Pattern History Table (PHT): 512 个条目，2-bit 饱和计数器

**硬件开销**:
- LEHT: 8 × 3 bits = 24 bits
- LCEHT: 8 × 3 bits = 24 bits
- LLR: 3 bits
- PHT: 512 × 2 bits = 1024 bits
- **总计**: ~1075 bits ≈ 135 bytes

#### 3. TVC 模块 (`ONNXim/src/async_queue/TVC.h`)
**Time-Aware Pre-Verification Control**
- NPU Verification Cycle Table (NVCT): 4 个条目
- PIM Drafting Cycle Table (PDCT): 4 个条目
- PIM Pre-Verification Cycle Table (PVCT): 4 个条目
- NPU Current Execution Cycle Register (NCR): 64 bits

**硬件开销**:
- NVCT: 4 × (64 + 32) bits = 384 bits
- PDCT: 4 × (64 + 32) bits = 384 bits
- PVCT: 4 × (64 + 32) bits = 384 bits
- NCR: 64 bits
- 控制逻辑: ~200 bits
- **总计**: ~1416 bits ≈ 177 bytes

#### 4. AAU 模块 (`PIMSimulator/src/AAU.h`)
**Attention Algorithm Unit**
- 支持的操作: GELU, Softmax, LayerNorm, Attention Score
- 向量宽度: 16 elements
- 流水线深度: 4 stages
- 峰值吞吐: 2.5 GOPS

**硬件开销**:
- GELU 单元: ~0.15 mm²
- Softmax 单元: ~0.12 mm²
- LayerNorm 单元: ~0.10 mm²
- 控制逻辑: ~0.08 mm²
- **总计**: ~0.45 mm²
- **功耗**: ~18.5 mW @ 800MHz, 28nm

#### 5. Gated Task Scheduler (`PIMSimulator/src/GatedTaskScheduler.h`)
**门控任务调度单元**
- 支持 sub-microsecond 任务切换
- Rank-level gating
- 切换延迟: 1 cycle @ 800MHz = 1.25 ns

**硬件开销**:
- 门控控制逻辑: ~0.02 mm²
- 静态功耗: ~0.5 mW

### 硬件总开销

| 模块 | 面积 (mm²) | DRAM Die 百分比 |
|------|-----------|----------------|
| EDC | 0.005 | < 0.10% |
| TVC | 0.003 | < 0.05% |
| Async Queue | 0.001 | < 0.02% |
| AAU | 0.450 | < 2.5% |
| Gated Scheduler | 0.020 | < 0.11% |
| **总计** | **0.479** | **< 3%** |

*注: 假设 LPDDR5-PIM Die 面积为 ~18 mm²*

## 环境配置

### 依赖项

```bash
# C++ 编译器 (支持 C++17)
sudo apt-get install g++ cmake

# Python 依赖
pip3 install numpy matplotlib pandas

# ONNXim 依赖
cd ONNXim
mkdir build && cd build
cmake ..
make -j8

# PIMSimulator 依赖
cd PIMSimulator
scons
```

### 环境变量

```bash
export ONNXIM_HOME=/path/to/AHASD/ONNXim
export PIM_SIM_HOME=/path/to/AHASD/PIMSimulator
export AHASD_RESULTS=/path/to/results
```

## 运行实验

### 1. 完整实验套件

```bash
# 运行所有模型配置和算法的完整评估
./scripts/run_ahasd_simulation.sh
```

这将运行以下配置:
- **模型**: OPT-1.3B/6.7B, LLaMA2-7B/13B, PaLM-8B/62B
- **算法**: SpecDec++, SVIP, AdaEDL, BanditSpec
- **AHASD 配置**:
  - Baseline (GPU only)
  - NPU+PIM (异步但无优化)
  - NPU+PIM+AAU
  - NPU+PIM+AAU+EDC
  - AHASD Full (所有优化)

### 2. 单个配置运行

```bash
# 示例: LLaMA2-7B/13B with AdaEDL
python3 scripts/run_single_config.py \
  --model llama2-7b-13b \
  --algorithm adaedl \
  --enable-edc \
  --enable-tvc \
  --enable-aau \
  --output ./results/llama2_adaedl_full
```

### 3. 消融实验

```bash
# 运行消融实验评估每个组件的贡献
python3 scripts/run_ablation.py \
  --model llama2-7b-13b \
  --algorithm adaedl \
  --output ./results/ablation_study
```

## 结果分析

### 生成对比图表

```bash
# 分析所有结果并生成图表
python3 scripts/analyze_ahasd_results.py ./results/ahasd_20241109_120000
```

这将生成:
- `throughput_comparison.png`: 吞吐量对比
- `energy_efficiency.png`: 能效对比
- `ablation_study.png`: 消融实验结果
- `summary_table.csv`: 汇总表格

### 验证硬件开销

```bash
# 计算并验证硬件开销
python3 scripts/validate_hardware_costs.py
```

输出示例:
```
=== AHASD Hardware Overhead Validation ===
EDC: 0.0050 mm² (1075 bits)
TVC: 0.0030 mm² (1416 bits)
Async Queues: 0.0010 mm²
AAU: 0.4500 mm²
Gated Scheduler: 0.0200 mm²
Total: 0.479 mm² (2.66% of LPDDR5 die)
✓ Hardware overhead < 3% requirement satisfied
```

## 实验配置文件

主配置文件位于 `configs/ahasd_config_template.json`，包含:

### NPU 配置
```json
{
  "npu": {
    "systolic_array": {
      "size": "128x128",
      "frequency_ghz": 1.0,
      "throughput_tflops": 16.0
    },
    "vector_unit": {
      "throughput_tflops": 8.2
    },
    "scratchpad": {
      "capacity_mb": 8
    }
  }
}
```

### PIM 配置
```json
{
  "pim": {
    "type": "LPDDR5-PIM",
    "num_ranks": 16,
    "rank_capacity_gb": 4,
    "frequency_mhz": 800,
    "performance_int8_gops": 102.4,
    "on_chip_bandwidth_gbs": 256,
    "off_chip_bandwidth_gbs": 51.2
  }
}
```

## 关键实现细节

### 1. NPU-PIM 通信

异步队列实现在 `AsyncQueue.h` 中，使用无锁队列结构:

```cpp
// PIM 侧: 生成草稿
DraftBatch batch;
batch.draft_length = tokens.size();
batch.token_ids = tokens;
batch.entropy_values = entropies;
queue_manager->push_draft(batch);

// NPU 侧: 获取并验证
DraftBatch batch;
if (queue_manager->pop_draft(batch)) {
    // 执行验证
    verify_tokens(batch);
}
```

### 2. EDC 决策逻辑

```cpp
// 计算 PHT 索引
uint16_t pht_index = (avg_H_{4-7} << 6) | (avg_H_{0-3} << 3) | LLR;

// 预测是否继续生成
bool should_continue = (pht[pht_index] >= WEAKLY_TAKEN);

// 验证后更新
if (fully_accepted) {
    increment_counter(pht[pht_index]);
} else {
    decrement_counter(pht[pht_index]);
}
```

### 3. TVC 时间建模

```cpp
// 预测 NPU 剩余周期
float npu_ratio = avg(NVCT);
uint64_t predicted_npu_cycles = npu_ratio * kv_length;

// 计算 PIM 可用周期
uint64_t pim_left = predicted_npu_cycles - (current_cycle + one_draft_cycles);

// 决定预验证长度
uint32_t preverify_length = pim_left / preverify_ratio;
```

## 预期结果

根据论文，AHASD 应该实现:

| 指标 | vs GPU-only | vs SpecPIM |
|------|------------|------------|
| 吞吐量 | 最高 4.6× | 最高 1.5× |
| 能效 | 最高 6.1× | 最高 1.24× |

### 各组件贡献 (消融实验)

| 配置 | 吞吐量增益 | 能效增益 |
|------|-----------|---------|
| NPU+PIM | 2.2× | 1.9× |
| +AAU | 2.7× | 2.6× |
| +EDC | 3.4× | 4.5× |
| +TVC (Full) | 3.8× | 5.5× |

## 故障排查

### 常见问题

1. **编译错误**: 确保使用 C++17 或更高版本
2. **内存不足**: 减小批次大小或模型规模
3. **结果不匹配**: 检查随机种子设置

### 调试选项

```bash
# 启用详细日志
export AHASD_DEBUG=1

# 启用跟踪
export AHASD_ENABLE_TRACE=1

# 设置日志级别
export AHASD_LOG_LEVEL=DEBUG
```

## 引用

如果使用此模拟器平台，请引用:

```bibtex
@inproceedings{ahasd2024,
  title={AHASD: Asynchronous Heterogeneous Architecture for LLM Speculative Decoding on Mobile Devices},
  author={},
  booktitle={},
  year={2024}
}
```

## 联系方式

如有问题，请联系: [作者邮箱]

## 许可证

- ONNXim: [原始许可证]
- PIMSimulator: Samsung Electronics License
- AHASD 扩展: [您的许可证]

