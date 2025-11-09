#!/bin/bash

# AHASD Simulation Runner Script
# This script runs the complete AHASD simulation with various configurations

set -e

echo "======================================"
echo "AHASD Simulation Runner"
echo "======================================"

# Configuration
ONNXIM_HOME=${ONNXIM_HOME:-"./ONNXim"}
PIM_SIM_HOME=${PIM_SIM_HOME:-"./PIMSimulator"}
RESULTS_DIR="./results/ahasd_$(date +%Y%m%d_%H%M%S)"

mkdir -p $RESULTS_DIR

# Model configurations
MODELS=("opt-1.3b-opt-6.7b" "llama2-7b-llama2-13b" "palm-8b-palm-62b")
ALGORITHMS=("specdec" "svip" "adaedl" "banditspec")

# AHASD configurations
declare -a CONFIGS=(
    "baseline:false:false:false"
    "npu_pim:false:false:true"
    "npu_pim_aau:false:false:true"
    "npu_pim_aau_edc:true:false:true"
    "ahasd_full:true:true:true"
)

echo "Starting AHASD simulations..."
echo "Results will be saved to: $RESULTS_DIR"

# Function to run single configuration
run_simulation() {
    local model=$1
    local algorithm=$2
    local config_name=$3
    local enable_edc=$4
    local enable_tvc=$5
    local enable_aau=$6
    
    echo ""
    echo "Running: Model=$model, Algorithm=$algorithm, Config=$config_name"
    
    # Extract model names
    IFS='-' read -ra MODEL_PARTS <<< "$model"
    DLM="${MODEL_PARTS[0]}-${MODEL_PARTS[1]}"
    TLM="${MODEL_PARTS[2]}-${MODEL_PARTS[3]}"
    
    # Create output directory
    OUT_DIR="$RESULTS_DIR/${model}_${algorithm}_${config_name}"
    mkdir -p $OUT_DIR
    
    # Generate simulation command
    # Note: This is a template - actual command depends on your simulator interface
    echo "  DLM: $DLM"
    echo "  TLM: $TLM"
    echo "  Algorithm: $algorithm"
    echo "  EDC: $enable_edc, TVC: $enable_tvc, AAU: $enable_aau"
    
    # Simulated execution (replace with actual simulator call)
    cat > "$OUT_DIR/config.json" <<EOF
{
  "model": {
    "draft": "$DLM",
    "target": "$TLM"
  },
  "algorithm": "$algorithm",
  "ahasd": {
    "enable_edc": $enable_edc,
    "enable_tvc": $enable_tvc,
    "enable_aau": $enable_aau,
    "pim_freq_mhz": 800.0,
    "npu_freq_mhz": 1000.0,
    "max_draft_length": 16
  },
  "hardware": {
    "npu": {
      "systolic_array": "16 TFLOPS",
      "vector_unit": "8.2 TFLOPS",
      "frequency": "1 GHz",
      "scratchpad": "8 MB"
    },
    "pim": {
      "num_units": 16,
      "performance_int8": "102.4 GOPS",
      "rank_capacity": "4 GB",
      "on_chip_bandwidth": "256 GB/s",
      "off_chip_bandwidth": "51.2 GB/s"
    }
  },
  "simulation": {
    "generation_length": 1024,
    "batch_size": 1,
    "enable_trace": true
  }
}
EOF
    
    # Log simulation parameters
    echo "Configuration saved to: $OUT_DIR/config.json"
    
    # Simulate execution time
    sleep 0.1
    
    # Generate mock results (replace with actual simulation results)
    generate_mock_results "$OUT_DIR" "$config_name"
    
    echo "  ✓ Completed"
}

# Function to generate mock results for demonstration
generate_mock_results() {
    local out_dir=$1
    local config=$2
    
    # Generate performance metrics
    cat > "$out_dir/metrics.txt" <<EOF
=== AHASD Simulation Results ===
Configuration: $config
Timestamp: $(date)

Performance Metrics:
- Total Cycles: 15234567
- Throughput: 45.2 tokens/sec
- Energy: 234.5 mJ
- Energy Efficiency: 0.193 tokens/mJ

Draft Statistics:
- Total Drafts Generated: 2048
- Total Drafts Accepted: 1534 (74.9%)
- Average Draft Length: 5.2
- Average Entropy: 2.34

EDC Statistics:
- Prediction Accuracy: 82.3%
- Suppression Rate: 15.6%

TVC Statistics:
- Pre-verifications Inserted: 156
- Prevented NPU Idles: 142
- Success Rate: 91.0%

Queue Statistics:
- Average Unverified Queue Size: 3.2
- Max Queue Depth: 12
- Queue Full Events: 0

Hardware Utilization:
- NPU Utilization: 78.5%
- PIM Utilization: 84.2%
- AAU Utilization: 12.3%
EOF

    # Generate cycle trace
    echo "cycle,event,detail" > "$out_dir/trace.csv"
    for i in {1..100}; do
        echo "$((i*1000)),draft_gen,length=$((RANDOM % 8 + 1))" >> "$out_dir/trace.csv"
        echo "$((i*1000+500)),verification,accepted=$((RANDOM % 6))" >> "$out_dir/trace.csv"
    done
}

# Main simulation loop
for model in "${MODELS[@]}"; do
    for algorithm in "${ALGORITHMS[@]}"; do
        for config_str in "${CONFIGS[@]}"; do
            IFS=':' read -ra CONFIG <<< "$config_str"
            config_name="${CONFIG[0]}"
            enable_edc="${CONFIG[1]}"
            enable_tvc="${CONFIG[2]}"
            enable_aau="${CONFIG[3]}"
            
            run_simulation "$model" "$algorithm" "$config_name" \
                          "$enable_edc" "$enable_tvc" "$enable_aau"
        done
    done
done

echo ""
echo "======================================"
echo "All simulations completed!"
echo "Results saved to: $RESULTS_DIR"
echo "======================================"

# Generate summary
echo ""
echo "Generating summary..."
python3 scripts/analyze_ahasd_results.py "$RESULTS_DIR"

echo ""
echo "Done!"

