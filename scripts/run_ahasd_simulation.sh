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
    
    echo "  DLM: $DLM"
    echo "  TLM: $TLM"
    echo "  Algorithm: $algorithm"
    echo "  EDC: $enable_edc, TVC: $enable_tvc, AAU: $enable_aau"
    
    # Generate configuration file for actual simulation
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
    
    # Run actual ONNXim simulator with AHASD
    echo "  Running ONNXim+PIMSimulator..."
    
    # Build ONNXim model list for this configuration
    MODEL_LIST_FILE="$OUT_DIR/models_list.json"
    cat > "$MODEL_LIST_FILE" <<MODELS_EOF
{
  "models": [
    {
      "name": "${DLM}",
      "type": "draft",
      "request_time": 0
    },
    {
      "name": "${TLM}",
      "type": "target",
      "request_time": 0
    }
  ]
}
MODELS_EOF
    
    # Run the actual simulator
    cd $ONNXIM_HOME
    ./build/onnxim_main \
        --config "$OUT_DIR/config.json" \
        --models_list "$MODEL_LIST_FILE" \
        --mode language \
        --log_level info \
        > "$OUT_DIR/simulation.log" 2>&1
    
    SIM_STATUS=$?
    cd - > /dev/null
    
    if [ $SIM_STATUS -eq 0 ]; then
        echo "  ✓ Simulation completed successfully"
        # Extract metrics from simulation output
        extract_simulation_metrics "$OUT_DIR"
    else
        echo "  ✗ Simulation failed (see $OUT_DIR/simulation.log)"
        return 1
    fi
}

# Function to extract metrics from actual simulation output
extract_simulation_metrics() {
    local out_dir=$1
    
    # Parse simulation log to extract metrics
    # Look for AHASD statistics section in the log
    if [ -f "$out_dir/simulation.log" ]; then
        # Extract key metrics from ONNXim output
        grep -A 50 "AHASD Statistics" "$out_dir/simulation.log" > "$out_dir/metrics.txt"
        
        # Also check for PIM statistics
        grep -A 20 "PIM Statistics" "$out_dir/simulation.log" >> "$out_dir/metrics.txt"
        
        # If metrics file is empty, simulation may not have AHASD output
        if [ ! -s "$out_dir/metrics.txt" ]; then
            echo "Warning: No AHASD statistics found in simulation output"
            echo "=== Simulation Log ===" > "$out_dir/metrics.txt"
            tail -n 100 "$out_dir/simulation.log" >> "$out_dir/metrics.txt"
        fi
    else
        echo "Error: Simulation log not found at $out_dir/simulation.log"
    fi
    
    # Generate results JSON for easier analysis
    python3 <<PYTHON_EOF
import json
import re

# Parse metrics from log
metrics = {}
try:
    with open("$out_dir/metrics.txt", 'r') as f:
        content = f.read()
        # Extract numeric values using regex
        # This is a template - adjust based on actual ONNXim output format
        metrics['status'] = 'completed'
except:
    metrics['status'] = 'failed'

with open("$out_dir/results.json", 'w') as f:
    json.dump(metrics, f, indent=2)
PYTHON_EOF
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

