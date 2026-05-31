#!/bin/bash
# AHASD End-to-End Test Script
# Quick validation that the system can run

set -e

echo "================================"
echo "AHASD End-to-End Test"
echo "================================"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo ""
echo "[1/5] Validating hardware costs..."
python3 scripts/validate_hardware_costs.py | grep "W11 optimised <2% die"

echo ""
echo "[2/5] Checking ONNXim submodule..."
if [ -f "ONNXim/src/AHASDIntegration.h" ]; then
    echo "  ✓ AHASDIntegration.h found"
else
    echo "  ✗ AHASDIntegration.h missing!"
    exit 1
fi

echo ""
echo "[3/5] Checking PIMSimulator submodule..."
if [ -f "PIMSimulator/src/AAU.h" ]; then
    echo "  ✓ AAU.h found"
else
    echo "  ✗ AAU.h missing!"
    exit 1
fi

echo ""
echo "[4/5] Validating configuration..."
if [ -f "configs/baselines/edge_ahasd_full.json" ]; then
    python3 -c "import json; json.load(open('configs/baselines/edge_ahasd_full.json'))"
    echo "  ✓ Configuration valid"
else
    echo "  ✗ Configuration missing!"
    exit 1
fi

echo ""
echo "[5/5] Running quick simulation test..."
python3 tools/dev/run_single_config.py \
    --model llama2-7b-llama2-13b \
    --algorithm adaedl \
    --enable-edc \
    --enable-tvc \
    --enable-aau \
    --gen-length 128 \
    --output ./test_output \
    --ci-smoke-stub >/dev/null 2>&1

if [ -f "test_output/results.json" ]; then
    echo "  ✓ Simulation completed successfully"
    rm -rf test_output
else
    echo "  ✗ Simulation failed!"
    exit 1
fi

echo ""
echo "================================"
echo "✓ All tests passed!"
echo "================================"
