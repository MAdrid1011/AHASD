# Configuration Guide

Learn how to customize AHASD experiments through configuration files.

## 📄 Configuration File Structure

AHASD uses JSON configuration files. The template is located at:
```
configs/ahasd_config_template.json
```

## 🎛️ Main Configuration Sections

### 1. Model Configuration

```json
{
  "models": {
    "small": {
      "draft": {
        "name": "OPT-1.3B",
        "hidden_size": 2048,
        "num_layers": 24,
        "quantization": "INT8"
      },
      "target": {
        "name": "OPT-6.7B",
        "hidden_size": 4096,
        "num_layers": 32,
        "quantization": "INT8"
      }
    }
  }
}
```

**Parameters**:
- `name`: Model identifier
- `hidden_size`: Hidden dimension size
- `num_layers`: Number of transformer layers
- `num_heads`: Number of attention heads
- `vocab_size`: Vocabulary size
- `quantization`: Data type (`FP32`, `FP16`, `INT8`)

### 2. Algorithm Configuration

```json
{
  "adaptive_algorithms": {
    "adaedl": {
      "name": "AdaEDL",
      "max_draft_length": 16,
      "adaptation_rate": 0.1,
      "history_length": 8
    }
  }
}
```

**Available Algorithms**:

| Algorithm | Key | Description | Parameters |
|-----------|-----|-------------|------------|
| SpecDec++ | `specdec` | Entropy-based | `entropy_threshold` |
| SVIP | `svip` | Incremental parsing | `verification_threshold` |
| AdaEDL | `adaedl` | Adaptive length | `adaptation_rate` |
| BanditSpec | `banditspec` | Multi-armed bandit | `exploration_rate` |

### 3. AHASD Components

```json
{
  "ahasd_configuration": {
    "enable_edc": true,
    "enable_tvc": true,
    "enable_aau": true,
    "enable_gated_scheduler": true,
    
    "edc_parameters": {
      "leht_size": 8,
      "pht_size": 512,
      "h_max": 10.0
    },
    
    "tvc_parameters": {
      "cycle_table_size": 4,
      "min_preverify_length": 2
    },
    
    "aau_parameters": {
      "vector_width": 16,
      "throughput_gops": 2.5
    }
  }
}
```

#### EDC Parameters

| Parameter | Description | Default | Range |
|-----------|-------------|---------|-------|
| `leht_size` | Entropy history table size | 8 | 4-16 |
| `pht_size` | Pattern history table size | 512 | 256-2048 |
| `pht_counter_bits` | Bits per counter | 2 | 1-3 |
| `h_max` | Maximum entropy value | 10.0 | 5.0-15.0 |

#### TVC Parameters

| Parameter | Description | Default | Range |
|-----------|-------------|---------|-------|
| `cycle_table_size` | Moving average window | 4 | 2-8 |
| `min_preverify_length` | Min tokens for pre-verify | 2 | 1-4 |
| `max_preverify_length` | Max tokens for pre-verify | 8 | 4-16 |

#### AAU Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `vector_width` | Processing width | 16 |
| `pipeline_stages` | Pipeline depth | 4 |
| `throughput_gops` | Peak throughput | 2.5 |
| `latency_cycles` | Base latency | 8 |

### 4. Hardware Configuration

#### NPU Settings

```json
{
  "hardware_configuration": {
    "npu": {
      "systolic_array": {
        "size": "128x128",
        "frequency_ghz": 1.0,
        "throughput_tflops": 16.0
      },
      "scratchpad": {
        "capacity_mb": 8
      }
    }
  }
}
```

**Adjustable Parameters**:
- `size`: Systolic array dimensions (`64x64`, `128x128`, `256x256`)
- `frequency_ghz`: Operating frequency (0.5-2.0 GHz)
- `throughput_tflops`: Peak throughput
- `capacity_mb`: Scratchpad size (2-16 MB)

#### PIM Settings

```json
{
  "pim": {
    "num_ranks": 16,
    "frequency_mhz": 800,
    "performance_int8_gops": 102.4,
    "on_chip_bandwidth_gbs": 256
  }
}
```

**Adjustable Parameters**:
- `num_ranks`: Number of PIM ranks (8-32)
- `frequency_mhz`: Operating frequency (400-1600 MHz)
- `rank_capacity_gb`: Capacity per rank (2-8 GB)
- `on_chip_bandwidth_gbs`: Internal bandwidth (128-512 GB/s)

### 5. Simulation Parameters

```json
{
  "simulation_parameters": {
    "generation_length": 1024,
    "batch_size": 1,
    "warmup_tokens": 128,
    "enable_trace": true,
    "random_seed": 42
  }
}
```

| Parameter | Description | Default | Impact |
|-----------|-------------|---------|--------|
| `generation_length` | Total tokens to generate | 1024 | Simulation time |
| `batch_size` | Batch size | 1 | Memory usage |
| `warmup_tokens` | Warmup period | 128 | Statistics accuracy |
| `enable_trace` | Detailed logging | false | Storage/speed |
| `random_seed` | Random seed | 42 | Reproducibility |

## 🔧 Command-Line Configuration

Override configuration from command line:

```bash
python3 scripts/run_single_config.py \
  --model llama2-7b-llama2-13b \
  --algorithm adaedl \
  --enable-edc \
  --enable-tvc \
  --enable-aau \
  --npu-freq 1200.0 \
  --pim-freq 900.0 \
  --max-draft-length 20 \
  --gen-length 2048 \
  --output ./results/custom
```

### Available CLI Options

```
Model & Algorithm:
  --model MODEL              Model configuration (required)
  --algorithm {specdec,svip,adaedl,banditspec}

AHASD Features:
  --enable-edc              Enable EDC
  --enable-tvc              Enable TVC  
  --enable-aau              Enable AAU

Hardware:
  --npu-freq FREQ           NPU frequency in MHz (default: 1000)
  --pim-freq FREQ           PIM frequency in MHz (default: 800)
  --num-pim-ranks N         Number of PIM ranks (default: 16)

Simulation:
  --gen-length N            Generation length (default: 1024)
  --batch-size N            Batch size (default: 1)
  --max-draft-length N      Max draft length (default: 16)
  --enable-trace            Enable detailed trace
  --verbose                 Verbose output

Output:
  --output DIR              Output directory (required)
```

## 📝 Configuration Examples

### Example 1: High-Performance Setup

Maximize throughput with larger hardware:

```json
{
  "hardware_configuration": {
    "npu": {
      "systolic_array": {"size": "256x256"},
      "frequency_ghz": 1.5,
      "scratchpad": {"capacity_mb": 16}
    },
    "pim": {
      "num_ranks": 32,
      "frequency_mhz": 1200,
      "on_chip_bandwidth_gbs": 512
    }
  }
}
```

### Example 2: Power-Efficient Setup

Minimize energy consumption:

```json
{
  "hardware_configuration": {
    "npu": {
      "frequency_ghz": 0.8,
      "num_chips": 1
    },
    "pim": {
      "frequency_mhz": 600,
      "num_ranks": 8
    }
  },
  "simulation_parameters": {
    "generation_length": 512
  }
}
```

### Example 3: Ablation Study

Test EDC only:

```json
{
  "ahasd_configuration": {
    "enable_edc": true,
    "enable_tvc": false,
    "enable_aau": false
  }
}
```

### Example 4: Conservative Pre-verification

Reduce pre-verification frequency:

```json
{
  "ahasd_configuration": {
    "tvc_parameters": {
      "min_preverify_length": 4,
      "conservative_mode": true
    }
  }
}
```

## 🎯 Configuration Best Practices

### 1. Start with Template

Always begin with the provided template:

```bash
cp configs/ahasd_config_template.json configs/my_experiment.json
# Edit my_experiment.json
```

### 2. Validate Configuration

```bash
python3 scripts/validate_config.py configs/my_experiment.json
```

### 3. Use Descriptive Names

```json
{
  "experiment_name": "llama2_adaedl_full_ahasd_1000mhz"
}
```

### 4. Document Changes

Add comments (in separate `.md` file):

```markdown
## Custom Configuration: High-Frequency PIM

Changes from default:
- PIM frequency: 800 → 1200 MHz
- Reason: Test scalability with faster memory
- Expected: 1.3× throughput increase
```

### 5. Version Control

```bash
git add configs/my_experiment.json
git commit -m "Add high-frequency PIM configuration"
```

## 🔍 Configuration Validation

### Check Syntax

```bash
# Validate JSON syntax
python3 -m json.tool configs/my_experiment.json

# Should print formatted JSON if valid
```

### Check Consistency

```bash
# Run validation script
python3 scripts/validate_config.py configs/my_experiment.json

# Checks:
# - Required fields present
# - Value ranges valid
# - Hardware compatibility
# - Parameter consistency
```

## 🐛 Common Configuration Errors

### Error 1: Invalid JSON

```
json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes
```

**Fix**: Check for:
- Missing commas
- Trailing commas
- Single quotes instead of double quotes
- Comments (not allowed in JSON)

### Error 2: Incompatible Parameters

```
ValueError: TVC requires EDC to be enabled
```

**Fix**: Enable dependencies:
```json
{
  "enable_edc": true,
  "enable_tvc": true
}
```

### Error 3: Hardware Constraints

```
Warning: NPU frequency exceeds maximum (1.5 GHz > 2.0 GHz)
```

**Fix**: Adjust to within valid range.

## 📊 Performance Tuning

### For Maximum Throughput

1. Increase NPU frequency
2. Increase PIM ranks
3. Enable all AHASD components
4. Increase max draft length

### For Minimum Energy

1. Decrease frequencies
2. Reduce PIM ranks
3. Use conservative pre-verification
4. Shorter generation length

### For Best Accuracy

1. Enable EDC with larger PHT
2. Use longer warmup period
3. Multiple random seeds
4. Longer generation length

## 📚 Advanced Topics

- **[Hyperparameter Tuning](AdvancedConfiguration.md)**
- **[Multi-Configuration Experiments](Experiments.md)**
- **[Custom Algorithms](CustomAlgorithms.md)**

---

**Need Help?** See [FAQ](FAQ.md) or open an [issue](https://github.com/yourusername/AHASD/issues).

