# AHASD Reproducibility Guide

本文档提供完整的步骤来重现论文中的实验结果。

## 📋 前置要求

### 硬件要求

- **CPU**: 16+ 核心 (推荐 Intel Xeon 或 AMD EPYC)
- **内存**: 64GB+ RAM
- **存储**: 500GB+ 可用空间 (用于模拟器输出)
- **可选**: NVIDIA GPU (用于 GPU baseline 对比)

### 软件要求

```bash
# 操作系统
Ubuntu 20.04 LTS 或更高版本

# 编译工具
sudo apt-get update
sudo apt-get install -y build-essential cmake ninja-build
sudo apt-get install -y gcc-10 g++-10
sudo apt-get install -y python3 python3-pip

# Chisel/Scala (用于 XiangShan)
sudo apt-get install -y default-jdk scala
curl -L https://github.com/com-lihaoyi/mill/releases/download/0.10.0/0.10.0 > mill
chmod +x mill
sudo mv mill /usr/local/bin/

# Python 依赖
pip3 install numpy matplotlib pandas jupyter
pip3 install onnx onnxruntime torch
```

## 🔧 环境配置

### 步骤 1: 克隆仓库并初始化子模块

```bash
git clone https://github.com/your-org/AHASD.git
cd AHASD

# 初始化子模块 (ONNXim, PIMSimulator, XiangShan)
git submodule update --init --recursive
```

### 步骤 2: 构建 ONNXim 模拟器

```bash
cd ONNXim

# 安装 Conan 依赖管理器
pip3 install conan

# 创建构建目录
mkdir build && cd build

# 配置 CMake (启用 AHASD 支持)
cmake .. -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DENABLE_AHASD=ON \
    -DCMAKE_CXX_COMPILER=g++-10 \
    -DCMAKE_C_COMPILER=gcc-10

# 构建 (这可能需要 10-20 分钟)
ninja -j$(nproc)

# 验证构建
./onnxim_main --version
# 应输出: ONNXim v1.0 (AHASD enabled)

cd ../..
```

### 步骤 3: 构建 PIMSimulator

```bash
cd PIMSimulator

# 使用 SCons 构建
scons -j$(nproc)

# 验证构建
./build/pim_simulator --help

cd ..
```

### 步骤 4: 构建 XiangShan (可选，用于完整端到端测试)

```bash
cd XiangShan

# 生成 Verilog (启用 AHASD)
make verilog AHASD=1

# 这会生成 build/XSTop.v，包含 AHASD 控制模块

# 构建仿真器
make emu AHASD=1

cd ..
```

### 步骤 5: 下载模型权重

```bash
# 创建模型目录
mkdir -p ONNXim/models/language_models

cd ONNXim/models/language_models

# 下载并转换模型 (需要大量磁盘空间)
# OPT 模型
python3 ../../scripts/generate_transformer_onnx.py \
    --model facebook/opt-1.3b \
    --output opt-1.3b

python3 ../../scripts/generate_transformer_onnx.py \
    --model facebook/opt-6.7b \
    --output opt-6.7b

# LLaMA2 模型
python3 ../../scripts/generate_transformer_onnx.py \
    --model meta-llama/Llama-2-7b-hf \
    --output llama2-7b

python3 ../../scripts/generate_transformer_onnx.py \
    --model meta-llama/Llama-2-13b-hf \
    --output llama2-13b

# PaLM 模型
python3 ../../scripts/generate_transformer_onnx.py \
    --model google/palm-8b \
    --output palm-8b

python3 ../../scripts/generate_transformer_onnx.py \
    --model google/palm-62b \
    --output palm-62b

cd ../../..
```

## 🧪 运行实验

### 快速测试 (单一配置)

验证环境设置正确：

```bash
# 运行单一配置的快速测试
./scripts/run_single_config.py \
    --model llama2-7b:llama2-13b \
    --algorithm adaedl \
    --config ahasd_full \
    --output results/quick_test

# 检查结果
cat results/quick_test/metrics.txt
```

预期输出应包含：
- Throughput: ~40-50 tokens/sec
- Energy Efficiency: ~0.18-0.22 tokens/mJ
- Draft Acceptance Rate: ~70-80%
- EDC Prediction Accuracy: ~80-85%

### 完整实验套件

运行论文中的所有实验：

```bash
# 设置环境变量
export ONNXIM_HOME=$(pwd)/ONNXim
export PIM_SIM_HOME=$(pwd)/PIMSimulator

# 运行完整实验 (可能需要 24-48 小时)
./scripts/run_ahasd_simulation.sh

# 结果将保存在 results/ahasd_YYYYMMDD_HHMMSS/
```

实验包括：
- 3 种模型配置 (Small, Medium, Large)
- 4 种自适应算法 (SpecDec++, SVIP, AdaEDL, BanditSpec)
- 5 种系统配置 (消融实验)
- **总计**: 60 个实验配置

### 并行运行实验 (加速)

如果有多核 CPU，可以并行运行：

```bash
# 修改脚本启用并行执行
vim scripts/run_ahasd_simulation.sh
# 将 run_simulation 函数调用改为后台执行：
# run_simulation ... &

# 或者使用 GNU Parallel
parallel -j 8 ./scripts/run_single_config.py ::: \
    llama2-7b:llama2-13b \
    opt-1.3b:opt-6.7b \
    palm-8b:palm-62b
```

## 📊 结果分析

### 生成图表

```bash
# 分析结果并生成论文图表
python3 scripts/analyze_ahasd_results.py results/ahasd_*/

# 输出:
# - plots/throughput_comparison.png  (Figure 7a)
# - plots/energy_efficiency.png      (Figure 7b)
# - plots/ablation_study.png         (Figure 6)
# - plots/summary_table.csv          (Table 3)
```

### 验证硬件开销

```bash
# 验证论文中声称的硬件开销
python3 scripts/validate_hardware_costs.py

# 应输出:
# EDC: 0.0002 mm² ✓
# TVC: 0.0002 mm² ✓
# AAU: 0.4500 mm² ✓
# Total: 0.4515 mm² (2.51% of DRAM) ✓
```

## 📈 预期结果

### 吞吐量提升 (vs GPU-only baseline)

| 模型配置 | SpecDec++ | SVIP | AdaEDL | BanditSpec |
|---------|-----------|------|--------|------------|
| OPT Small | 3.8× | 4.1× | 4.3× | 4.6× |
| LLaMA2 Medium | 3.2× | 3.5× | 3.8× | 3.9× |
| PaLM Large | 2.8× | 3.1× | 3.3× | 3.5× |

### 能效提升 (vs GPU-only baseline)

| 模型配置 | SpecDec++ | SVIP | AdaEDL | BanditSpec |
|---------|-----------|------|--------|------------|
| OPT Small | 5.2× | 5.6× | 5.9× | 6.1× |
| LLaMA2 Medium | 4.5× | 4.8× | 5.1× | 5.3× |
| PaLM Large | 3.9× | 4.2× | 4.5× | 4.7× |

### 消融实验 (LLaMA2-7B, AdaEDL)

| 配置 | 吞吐量 | 能效 |
|-----|--------|------|
| Baseline (GPU-only) | 1.0× | 1.0× |
| NPU+PIM | 2.2× | 1.9× |
| +AAU | 2.7× | 2.6× |
| +EDC | 3.4× | 4.5× |
| +TVC (Full) | 3.8× | 5.5× |

**注意**: 实际结果可能有 ±10% 的变化，这是由于：
- 模型量化的随机性
- 自适应算法的随机采样
- 模拟器的初始化状态

## 🐛 故障排除

### 问题 1: ONNXim 编译失败

```bash
# 检查 C++ 编译器版本
g++ --version  # 应该是 10.0 或更高

# 清理并重新构建
cd ONNXim/build
rm -rf *
cmake .. -G Ninja -DCMAKE_BUILD_TYPE=Release -DENABLE_AHASD=ON
ninja -j$(nproc)
```

### 问题 2: 模型下载失败

```bash
# 使用代理 (如果在国内)
export HF_ENDPOINT=https://hf-mirror.com

# 或手动下载模型
# 访问 Hugging Face 手动下载后放置在 ONNXim/models/language_models/
```

### 问题 3: 模拟器运行缓慢

```bash
# 启用优化
export ONNXIM_OPT_LEVEL=3
export OMP_NUM_THREADS=$(nproc)

# 减少日志输出
./onnxim_main --log_level info  # 而不是 debug 或 trace
```

### 问题 4: 内存不足

```bash
# 减少批量大小
vim configs/ahasd_config_template.json
# 将 "batch_size": 1 改为更小的值

# 或者增加 swap
sudo fallocate -l 64G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

## 📝 验证清单

运行完实验后，验证以下内容：

- [ ] 所有 60 个配置都成功完成
- [ ] 每个配置目录包含 `metrics.txt` 和 `results.json`
- [ ] 吞吐量提升在预期范围内 (2.8×-4.6×)
- [ ] 能效提升在预期范围内 (3.9×-6.1×)
- [ ] 硬件开销验证通过 (< 3% DRAM die)
- [ ] 图表生成成功，与论文图表相似

## 🆘 获取帮助

如果遇到问题：

1. 检查 `results/*/simulation.log` 查看详细错误信息
2. 运行诊断脚本: `./scripts/test_e2e.sh`
3. 查看 FAQ: `docs/FAQ.md`
4. 提交 Issue: https://github.com/your-org/AHASD/issues

## 📄 引用

如果使用本代码，请引用：

```bibtex
@inproceedings{ahasd2024,
  title={AHASD: Asynchronous Heterogeneous Architecture for LLM Speculative Decoding on Mobile Devices},
  author={Your Name et al.},
  booktitle={Conference Name},
  year={2024}
}
```

## 📅 更新日志

- **2024-11**: 初始发布
- **2024-11**: 修复 mock 数据问题，使用真实模拟器
- **2024-11**: 添加 XiangShan 集成代码

