# Model Preparation Guide

Complete guide for downloading, converting, and preparing LLM models for AHASD experiments.

## 📋 Overview

AHASD experiments require the following models:

| Configuration | Draft Model | Target Model | Total Size |
|---------------|-------------|--------------|------------|
| Small | OPT-1.3B | OPT-6.7B | ~15GB |
| Medium | LLaMA2-7B | LLaMA2-13B | ~40GB |
| Large | Qwen3-8B | Qwen3-32B | ~80GB |

**Total storage required**: ~135GB, depending on checkpoint format and ONNX export options.

## 🚀 Quick Start

### Automated Download (Recommended)

```bash
# Download and prepare all models
./scripts/download_models.sh

# This will:
# 1. Download models from HuggingFace
# 2. Convert to ONNX format
# 3. Quantize to INT8
# 4. Validate model integrity
```

### Manual Download

If you prefer manual setup or encounter issues:

```bash
# Install dependencies
pip3 install transformers torch onnx optimum

# Download OPT models
python3 -c "from transformers import AutoModel, AutoTokenizer; \
  AutoModel.from_pretrained('facebook/opt-1.3b').save_pretrained('./ONNXim/models/opt-1.3b'); \
  AutoTokenizer.from_pretrained('facebook/opt-1.3b').save_pretrained('./ONNXim/models/opt-1.3b')"

# Repeat for other models...
```

## 📥 Step-by-Step Instructions

### Step 1: Prerequisites

```bash
# Check Python version (3.8+ required)
python3 --version

# Install required packages
pip3 install -r requirements-models.txt

# For LLaMA2 models, login to HuggingFace
huggingface-cli login
# Enter your HuggingFace token
```

### Step 2: Download Base Models

#### OPT Models (Public)

```python
# scripts/download_opt.py
from transformers import AutoModelForCausalLM, AutoTokenizer

models = [
    ("facebook/opt-1.3b", "./ONNXim/models/opt-1.3b"),
    ("facebook/opt-6.7b", "./ONNXim/models/opt-6.7b"),
]

for model_name, save_path in models:
    print(f"Downloading {model_name}...")
    model = AutoModelForCausalLM.from_pretrained(model_name)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    
    model.save_pretrained(save_path)
    tokenizer.save_pretrained(save_path)
    print(f"✓ Saved to {save_path}")
```

Run:
```bash
python3 scripts/download_opt.py
```

#### LLaMA2 Models (Requires Access)

1. **Request access**: Visit https://huggingface.co/meta-llama
2. **Accept license**: Complete the form (usually approved within hours)
3. **Login**: `huggingface-cli login`
4. **Download**:

```python
# scripts/download_llama2.py
from transformers import AutoModelForCausalLM, AutoTokenizer

models = [
    ("meta-llama/Llama-2-7b-hf", "./ONNXim/models/llama2-7b"),
    ("meta-llama/Llama-2-13b-hf", "./ONNXim/models/llama2-13b"),
]

for model_name, save_path in models:
    print(f"Downloading {model_name}...")
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        token=True  # Use stored HF token
    )
    tokenizer = AutoTokenizer.from_pretrained(model_name, token=True)
    
    model.save_pretrained(save_path)
    tokenizer.save_pretrained(save_path)
    print(f"✓ Saved to {save_path}")
```

Run:
```bash
python3 scripts/download_llama2.py
```

### Step 3: Convert to ONNX

ONNXim requires models in ONNX format for cycle-accurate simulation.

```python
# scripts/convert_to_onnx.py
import torch
from transformers import AutoModelForCausalLM
from torch.onnx import export
import os

def convert_model_to_onnx(model_path, output_path):
    """Convert HuggingFace model to ONNX."""
    print(f"Loading model from {model_path}...")
    model = AutoModelForCausalLM.from_pretrained(model_path)
    model.eval()
    
    # Create dummy inputs
    batch_size = 1
    seq_length = 128
    dummy_input_ids = torch.randint(0, 1000, (batch_size, seq_length))
    dummy_attention_mask = torch.ones(batch_size, seq_length)
    
    print("Exporting to ONNX...")
    export(
        model,
        (dummy_input_ids, dummy_attention_mask),
        output_path,
        input_names=['input_ids', 'attention_mask'],
        output_names=['logits'],
        dynamic_axes={
            'input_ids': {0: 'batch', 1: 'sequence'},
            'attention_mask': {0: 'batch', 1: 'sequence'},
            'logits': {0: 'batch', 1: 'sequence'},
        },
        opset_version=14
    )
    print(f"✓ Exported to {output_path}")

# Convert all models
models = [
    ("./ONNXim/models/opt-1.3b", "./ONNXim/models/opt-1.3b/model.onnx"),
    ("./ONNXim/models/opt-6.7b", "./ONNXim/models/opt-6.7b/model.onnx"),
    ("./ONNXim/models/llama2-7b", "./ONNXim/models/llama2-7b/model.onnx"),
    ("./ONNXim/models/llama2-13b", "./ONNXim/models/llama2-13b/model.onnx"),
]

for model_path, onnx_path in models:
    if os.path.exists(model_path):
        convert_model_to_onnx(model_path, onnx_path)
```

Run:
```bash
python3 scripts/convert_to_onnx.py
```

### Step 4: Quantize to INT8

AHASD uses INT8 quantization for mobile deployment.

```python
# scripts/quantize_models.py
from optimum.onnxruntime import ORTQuantizer
from optimum.onnxruntime.configuration import AutoQuantizationConfig
import os

def quantize_model(onnx_path):
    """Quantize ONNX model to INT8."""
    print(f"Quantizing {onnx_path}...")
    
    quantizer = ORTQuantizer.from_pretrained(os.path.dirname(onnx_path))
    qconfig = AutoQuantizationConfig.arm64(is_static=False)
    
    quantizer.quantize(
        save_dir=os.path.dirname(onnx_path),
        quantization_config=qconfig,
    )
    print(f"✓ Quantized model saved")

# Quantize all models
onnx_models = [
    "./ONNXim/models/opt-1.3b/model.onnx",
    "./ONNXim/models/opt-6.7b/model.onnx",
    "./ONNXim/models/llama2-7b/model.onnx",
    "./ONNXim/models/llama2-13b/model.onnx",
]

for onnx_path in onnx_models:
    if os.path.exists(onnx_path):
        quantize_model(onnx_path)
```

Run:
```bash
python3 scripts/quantize_models.py
```

### Step 5: Verify Models

```python
# scripts/verify_models.py
import onnxruntime as ort
import numpy as np
import os

def verify_model(onnx_path):
    """Verify ONNX model can be loaded and executed."""
    print(f"Verifying {onnx_path}...")
    
    # Load model
    session = ort.InferenceSession(onnx_path)
    
    # Check inputs/outputs
    print(f"  Inputs: {[i.name for i in session.get_inputs()]}")
    print(f"  Outputs: {[o.name for o in session.get_outputs()]}")
    
    # Test inference
    dummy_input = np.random.randint(0, 1000, (1, 128), dtype=np.int64)
    dummy_attention = np.ones((1, 128), dtype=np.int64)
    
    outputs = session.run(
        None,
        {'input_ids': dummy_input, 'attention_mask': dummy_attention}
    )
    
    print(f"  ✓ Output shape: {outputs[0].shape}")
    print(f"  ✓ Model verified successfully")
    return True

# Verify all models
for model_dir in ["opt-1.3b", "opt-6.7b", "llama2-7b", "llama2-13b"]:
    onnx_path = f"./ONNXim/models/{model_dir}/model.onnx"
    if os.path.exists(onnx_path):
        verify_model(onnx_path)
    else:
        print(f"⚠ Model not found: {onnx_path}")
```

Run:
```bash
python3 scripts/verify_models.py
```

## 🗂️ Expected Directory Structure

After completing all steps:

```
ONNXim/models/
├── opt-1.3b/
│   ├── config.json
│   ├── tokenizer_config.json
│   ├── model.onnx                    # Converted ONNX
│   ├── model_quantized.onnx         # Quantized INT8
│   └── pytorch_model.bin            # Original weights
├── opt-6.7b/
│   └── (same structure)
├── llama2-7b/
│   └── (same structure)
└── llama2-13b/
    └── (same structure)
```

## ⚡ Quick Verification

```bash
# Check all models are present
ls -lh ONNXim/models/*/model_quantized.onnx

# Should output:
# opt-1.3b/model_quantized.onnx     (335M)
# opt-6.7b/model_quantized.onnx     (1.7G)
# llama2-7b/model_quantized.onnx    (3.5G)
# llama2-13b/model_quantized.onnx   (6.5G)
```

## 🔧 Troubleshooting

### Issue: "Permission denied" for LLaMA2

**Solution**: 
1. Visit https://huggingface.co/meta-llama
2. Request access (fill out form)
3. Wait for approval email
4. Run `huggingface-cli login` again

### Issue: Out of memory during conversion

**Solution**:
```python
# Use CPU offloading
model = AutoModelForCausalLM.from_pretrained(
    model_path,
    device_map='auto',
    torch_dtype=torch.float16,
    low_cpu_mem_usage=True
)
```

### Issue: ONNX export fails

**Solution**:
```bash
# Upgrade ONNX tools
pip3 install --upgrade torch onnx onnxruntime optimum

# Try with simpler export
python3 -m transformers.onnx --model=facebook/opt-1.3b onnx_output/
```

### Issue: Quantization produces incorrect results

**Solution**:
- Use static quantization with calibration dataset
- Verify output matches pre-quantization (tolerance < 1%)
- Check INT8 support on target hardware

## 📊 Model Sizes

| Model | FP32 | FP16 | INT8 (Quantized) |
|-------|------|------|------------------|
| OPT-1.3B | 5.2GB | 2.6GB | 1.3GB |
| OPT-6.7B | 26GB | 13GB | 6.7GB |
| LLaMA2-7B | 28GB | 14GB | 7GB |
| LLaMA2-13B | 52GB | 26GB | 13GB |

## 🎯 Next Steps

After preparing models:

1. **Test single model**:
```bash
python3 tools/dev/run_single_config.py \
  --model opt-1.3b-opt-6.7b \
  --algorithm specdec
```

2. **Run full experiments**:
```bash
./tools/dev/run_ahasd_simulation.sh
```

3. **Analyze results**:
```bash
python3 tools/dev/analyze_ahasd_results.py ./results/
```

---

**Need help?** Check [FAQ](FAQ.md) or file an issue on GitHub.
