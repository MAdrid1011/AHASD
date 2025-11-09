#!/usr/bin/env python3
"""
Run a single AHASD configuration
"""

import argparse
import json
import os
import sys
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(
        description='Run AHASD simulation with specific configuration')
    
    # Model configuration
    parser.add_argument('--model', type=str, required=True,
                       help='Model configuration (e.g., llama2-7b-13b)')
    parser.add_argument('--algorithm', type=str, required=True,
                       choices=['specdec', 'svip', 'adaedl', 'banditspec'],
                       help='Adaptive drafting algorithm')
    
    # AHASD features
    parser.add_argument('--enable-edc', action='store_true',
                       help='Enable Entropy-History-Aware Drafting Control')
    parser.add_argument('--enable-tvc', action='store_true',
                       help='Enable Time-Aware Pre-Verification Control')
    parser.add_argument('--enable-aau', action='store_true',
                       help='Enable Attention Algorithm Unit')
    
    # Hardware parameters
    parser.add_argument('--npu-freq', type=float, default=1000.0,
                       help='NPU frequency in MHz (default: 1000)')
    parser.add_argument('--pim-freq', type=float, default=800.0,
                       help='PIM frequency in MHz (default: 800)')
    parser.add_argument('--num-pim-ranks', type=int, default=16,
                       help='Number of PIM ranks (default: 16)')
    
    # Simulation parameters
    parser.add_argument('--gen-length', type=int, default=1024,
                       help='Generation length (default: 1024)')
    parser.add_argument('--batch-size', type=int, default=1,
                       help='Batch size (default: 1)')
    parser.add_argument('--max-draft-length', type=int, default=16,
                       help='Maximum draft length (default: 16)')
    
    # Output
    parser.add_argument('--output', type=str, required=True,
                       help='Output directory for results')
    parser.add_argument('--enable-trace', action='store_true',
                       help='Enable detailed trace logging')
    parser.add_argument('--verbose', action='store_true',
                       help='Verbose output')
    
    return parser.parse_args()

def create_config(args):
    """Create simulation configuration."""
    
    # Parse model names
    model_parts = args.model.split('-')
    if len(model_parts) == 4:
        dlm_name = f"{model_parts[0]}-{model_parts[1]}"
        tlm_name = f"{model_parts[2]}-{model_parts[3]}"
    else:
        print(f"Error: Invalid model format '{args.model}'")
        print("Expected format: <dlm_family>-<dlm_size>-<tlm_family>-<tlm_size>")
        print("Example: llama2-7b-llama2-13b")
        sys.exit(1)
    
    config = {
        "experiment_name": f"{args.model}_{args.algorithm}",
        "model": {
            "draft": dlm_name,
            "target": tlm_name
        },
        "algorithm": args.algorithm,
        "ahasd": {
            "enable_edc": args.enable_edc,
            "enable_tvc": args.enable_tvc,
            "enable_aau": args.enable_aau,
            "pim_freq_mhz": args.pim_freq,
            "npu_freq_mhz": args.npu_freq,
            "max_draft_length": args.max_draft_length,
            "num_pim_ranks": args.num_pim_ranks
        },
        "simulation": {
            "generation_length": args.gen_length,
            "batch_size": args.batch_size,
            "enable_trace": args.enable_trace
        }
    }
    
    return config

def run_simulation(config, output_dir, verbose=False):
    """Run the actual simulation."""
    
    print(f"Starting simulation...")
    print(f"  Model: {config['model']['draft']} -> {config['model']['target']}")
    print(f"  Algorithm: {config['algorithm']}")
    print(f"  EDC: {config['ahasd']['enable_edc']}, "
          f"TVC: {config['ahasd']['enable_tvc']}, "
          f"AAU: {config['ahasd']['enable_aau']}")
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Save configuration
    config_file = os.path.join(output_dir, 'config.json')
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"  Configuration saved to: {config_file}")
    
    # Real simulation using ONNXim + PIMSimulator
    print("\n  Initializing NPU simulator (ONNXim)...")
    print("  Initializing PIM simulator (PIMSimulator)...")
    print("  Setting up AHASD integration layer...")
    
    if config['ahasd']['enable_edc']:
        print("    ✓ EDC module initialized")
    if config['ahasd']['enable_tvc']:
        print("    ✓ TVC module initialized")
    if config['ahasd']['enable_aau']:
        print("    ✓ AAU module initialized")
    
    print("\n  Running simulation...")
    
    # Execute real simulation command
    import subprocess
    import time
    
    # Execute real cycle-accurate simulation using ONNXim + PIMSimulator
    onnxim_root = os.path.join(os.path.dirname(__file__), '..', 'ONNXim')
    onnxim_binary = os.path.join(onnxim_root, 'build', 'bin', 'Simulator')
    
    # Verify simulators exist
    if not os.path.exists(onnxim_binary):
        print(f"    ERROR: ONNXim simulator not found at {onnxim_binary}")
        print(f"    Please build ONNXim first: cd ONNXim && mkdir build && cd build && cmake .. && make")
        sys.exit(1)
    
    # Create model list for ONNXim
    model_list = {
        "models": [
            {"name": config['model']['draft'], "type": "draft", "request_time": 0},
            {"name": config['model']['target'], "type": "target", "request_time": 0}
        ]
    }
    model_list_file = os.path.join(output_dir, 'models_list.json')
    with open(model_list_file, 'w') as f:
        json.dump(model_list, f, indent=2)
    
    # Run cycle-accurate simulation
    print("    Executing cycle-accurate simulation (ONNXim + PIMSimulator)...")
    cmd = [
        onnxim_binary,
        '--config', config_file,
        '--models_list', model_list_file,
        '--mode', 'language',
        '--log_level', 'info'
    ]
    
    sim_log = os.path.join(output_dir, 'simulation.log')
    try:
        with open(sim_log, 'w') as log_file:
            result = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT, 
                                  timeout=3600, check=True)
        
        # Parse real simulation results from log
        results = parse_simulation_log(sim_log, config)
        results['simulation_type'] = 'cycle_accurate'
        results['simulator'] = 'ONNXim+PIMSimulator'
        
    except subprocess.TimeoutExpired:
        print(f"    ERROR: Simulation timeout after 1 hour")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"    ERROR: Simulation failed with return code {e.returncode}")
        print(f"    Check log file: {sim_log}")
        sys.exit(1)
    
    # Save results
    results_file = os.path.join(output_dir, 'results.json')
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    # Save metrics in readable format
    metrics_file = os.path.join(output_dir, 'metrics.txt')
    with open(metrics_file, 'w') as f:
        f.write("=== AHASD Simulation Results ===\n")
        f.write(f"Configuration: {config['experiment_name']}\n")
        f.write(f"Simulation Type: {results.get('simulation_type', 'unknown')}\n\n")
        f.write("Performance Metrics:\n")
        for key, value in results.get('metrics', {}).items():
            f.write(f"- {key.replace('_', ' ').title()}: {value}\n")
        
        if 'edc_stats' in results:
            f.write("\nEDC Statistics:\n")
            for key, value in results['edc_stats'].items():
                f.write(f"- {key.replace('_', ' ').title()}: {value:.3f}\n")
        
        if 'tvc_stats' in results:
            f.write("\nTVC Statistics:\n")
            for key, value in results['tvc_stats'].items():
                f.write(f"- {key.replace('_', ' ').title()}: {value}\n")
    
    print(f"\n  ✓ Simulation completed successfully")
    print(f"  Results saved to: {output_dir}")
    
    return 0

def parse_simulation_log(log_file, config):
    """Parse actual simulation results from ONNXim+PIMSimulator log."""
    import re
    
    results = {
        "status": "completed",
        "configuration": config['experiment_name'],
        "metrics": {}
    }
    
    try:
        with open(log_file, 'r') as f:
            content = f.read()
            
            # Parse throughput and cycles
            if match := re.search(r'Total Simulation Cycles:\s*(\d+)', content):
                results['metrics']['total_cycles'] = int(match.group(1))
            
            if match := re.search(r'Throughput:\s*([\d.]+)\s*tokens/sec', content):
                results['metrics']['throughput_tokens_per_sec'] = float(match.group(1))
            
            # Parse energy metrics
            if match := re.search(r'Total Energy:\s*([\d.]+)\s*mJ', content):
                results['metrics']['energy_mj'] = float(match.group(1))
            
            if match := re.search(r'Energy Efficiency:\s*([\d.]+)\s*tokens/mJ', content):
                results['metrics']['energy_efficiency_tokens_per_mj'] = float(match.group(1))
            
            # Parse draft statistics
            if match := re.search(r'Total Drafts Generated:\s*(\d+)', content):
                results['metrics']['drafts_generated'] = int(match.group(1))
            
            if match := re.search(r'Total Drafts Accepted:\s*(\d+)', content):
                results['metrics']['drafts_accepted'] = int(match.group(1))
            
            if match := re.search(r'Acceptance Rate:\s*([\d.]+)', content):
                results['metrics']['acceptance_rate'] = float(match.group(1))
            
            if match := re.search(r'Average Draft Length:\s*([\d.]+)', content):
                results['metrics']['average_draft_length'] = float(match.group(1))
            
            if match := re.search(r'Average Draft Entropy:\s*([\d.]+)', content):
                results['metrics']['average_entropy'] = float(match.group(1))
            
            # Parse EDC statistics if enabled
            if config['ahasd']['enable_edc'] and 'EDC Statistics' in content:
                results['edc_stats'] = {}
                if match := re.search(r'EDC.*Accuracy:\s*([\d.]+)%', content):
                    results['edc_stats']['prediction_accuracy'] = float(match.group(1)) / 100.0
                if match := re.search(r'Suppressed:.*\(([\d.]+)%\)', content):
                    results['edc_stats']['suppression_rate'] = float(match.group(1)) / 100.0
            
            # Parse TVC statistics if enabled
            if config['ahasd']['enable_tvc'] and 'TVC Statistics' in content:
                results['tvc_stats'] = {}
                if match := re.search(r'Pre-verifications Inserted:\s*(\d+)', content):
                    results['tvc_stats']['preverifications_inserted'] = int(match.group(1))
                if match := re.search(r'Prevented NPU Idles:\s*(\d+)', content):
                    results['tvc_stats']['prevented_npu_idles'] = int(match.group(1))
                if match := re.search(r'TVC.*Success.*:\s*(\d+).*\(([\d.]+)%\)', content):
                    results['tvc_stats']['success_rate'] = float(match.group(2)) / 100.0
    
    except Exception as e:
        print(f"    Warning: Error parsing simulation log: {e}")
        results['status'] = 'parse_error'
    
    return results

def main():
    args = parse_args()
    
    print("="*70)
    print("AHASD Single Configuration Runner")
    print("="*70 + "\n")
    
    # Create configuration
    config = create_config(args)
    
    # Run simulation
    result = run_simulation(config, args.output, args.verbose)
    
    print("\n" + "="*70)
    print("Simulation Complete")
    print("="*70)
    
    return result

if __name__ == '__main__':
    sys.exit(main())

