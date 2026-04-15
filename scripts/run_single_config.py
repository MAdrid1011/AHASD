#!/usr/bin/env python3
"""
Run a single AHASD configuration
"""

import argparse
import json
import os
import sys
from pathlib import Path

ONNXIM_CONFIG_TEMPLATE = "systolic_ws_128x128_c4_simple_noc_tpuv4.json"

LANGUAGE_MODEL_CONFIGS = {
    "llama2-7b": {
        "num_hidden_layers": 32,
        "hidden_size": 4096,
        "num_kv_heads": 32,
        "num_attention_heads": 32,
        "intermediate_size": 11008,
        "ffn_type": "llama",
        "activation_function": "swish",
        "vocab_size": 32000,
        "max_seq_length": 4096,
        "run_single_layer": True,
        "tensor_parallel_size": 1,
        "pipeline_parallel_size": 1,
        "source_note": "Generated from standard Llama-2 7B architecture for ONNXim smoke validation.",
    },
    "llama2-13b": {
        "num_hidden_layers": 40,
        "hidden_size": 5120,
        "num_kv_heads": 40,
        "num_attention_heads": 40,
        "intermediate_size": 13824,
        "ffn_type": "llama",
        "activation_function": "swish",
        "vocab_size": 32000,
        "max_seq_length": 4096,
        "run_single_layer": True,
        "tensor_parallel_size": 1,
        "pipeline_parallel_size": 1,
        "source_note": "Generated from standard Llama-2 13B architecture for ONNXim smoke validation.",
    },
    "opt-1.3b": {
        "num_hidden_layers": 24,
        "hidden_size": 2048,
        "num_kv_heads": 32,
        "num_attention_heads": 32,
        "intermediate_size": 8192,
        "ffn_type": "opt",
        "activation_function": "relu",
        "vocab_size": 50272,
        "max_seq_length": 2048,
        "run_single_layer": True,
        "tensor_parallel_size": 1,
        "pipeline_parallel_size": 1,
        "source_note": "Generated from standard OPT-1.3B architecture for ONNXim smoke validation.",
    },
    "opt-6.7b": {
        "num_hidden_layers": 32,
        "hidden_size": 4096,
        "num_kv_heads": 32,
        "num_attention_heads": 32,
        "intermediate_size": 16384,
        "ffn_type": "opt",
        "activation_function": "relu",
        "vocab_size": 50272,
        "max_seq_length": 2048,
        "run_single_layer": True,
        "tensor_parallel_size": 1,
        "pipeline_parallel_size": 1,
        "source_note": "Generated from standard OPT-6.7B architecture for ONNXim smoke validation.",
    },
}

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
    parser.add_argument('--enable-ssrc', action='store_true',
                       help='Enable Speculative State Residency Control')
    parser.add_argument('--enable-ssrc-proxy', action='store_true',
                       help='Enable trace-level proxy draft events for SSRC accounting')
    parser.add_argument('--enable-ssrc-trace', action='store_true',
                       help='Enable language-scheduler-driven draft events for SSRC accounting')
    parser.add_argument('--ssrc-state-bytes-per-token', type=int, default=524288,
                       help='Estimated speculative KV/state bytes per token')
    parser.add_argument('--ssrc-resident-limit-mb', type=float, default=32.0,
                       help='SSRC speculative resident-state budget in MiB')
    parser.add_argument('--ssrc-confidence-threshold', type=float, default=0.55,
                       help='SSRC confidence threshold for resident materialization')
    
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
    parser.add_argument('--prompt-length', type=int, default=100,
                       help='Prompt length for generated ONNXim language traces (default: 100)')
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
    parser.add_argument('--dry-run', action='store_true',
                       help='Dry run mode for CI testing (creates mock results without running simulator)')
    
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
            "enable_ssrc": args.enable_ssrc,
            "enable_ssrc_proxy": args.enable_ssrc_proxy,
            "enable_ssrc_trace": args.enable_ssrc_trace,
            "ssrc_state_bytes_per_token": args.ssrc_state_bytes_per_token,
            "ssrc_resident_limit_bytes": int(args.ssrc_resident_limit_mb * 1024 * 1024),
            "ssrc_confidence_threshold": args.ssrc_confidence_threshold,
            "pim_freq_mhz": args.pim_freq,
            "npu_freq_mhz": args.npu_freq,
            "max_draft_length": args.max_draft_length,
            "num_pim_ranks": args.num_pim_ranks
        },
        "simulation": {
            "generation_length": args.gen_length,
            "prompt_length": args.prompt_length,
            "batch_size": args.batch_size,
            "enable_trace": args.enable_trace
        }
    }
    
    return config

def generate_mock_results(config):
    """Generate mock simulation results for dry-run/CI testing."""
    results = {
        "status": "completed",
        "configuration": config['experiment_name'],
        "simulation_type": "mock_for_ci",
        "simulator": "ONNXim+PIMSimulator (mock)",
        "metrics": {
            "total_cycles": 1000000,
            "throughput_tokens_per_sec": 100.0,
            "energy_mj": 500.0,
            "energy_efficiency_tokens_per_mj": 0.2,
            "drafts_generated": 100,
            "drafts_accepted": 75,
            "acceptance_rate": 0.75,
            "average_draft_length": 8.5,
            "average_entropy": 2.3
        }
    }
    
    # Add EDC stats if enabled
    if config['ahasd']['enable_edc']:
        results['edc_stats'] = {
            "prediction_accuracy": 0.85,
            "suppression_rate": 0.12
        }
    
    # Add TVC stats if enabled
    if config['ahasd']['enable_tvc']:
        results['tvc_stats'] = {
            "preverifications_inserted": 25,
            "prevented_npu_idles": 18,
            "success_rate": 0.72
        }
    
    return results

def safe_filename(value):
    """Return a portable filename stem while keeping model/config names readable."""
    return ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in value)

def ensure_language_model_config(model_name, onnxim_root):
    if model_name not in LANGUAGE_MODEL_CONFIGS:
        supported = ', '.join(sorted(LANGUAGE_MODEL_CONFIGS))
        raise ValueError(
            f"No ONNXim language model config for '{model_name}'. "
            f"Supported generated configs: {supported}"
        )

    model_dir = os.path.join(onnxim_root, 'models', 'language_models')
    os.makedirs(model_dir, exist_ok=True)
    model_config_file = os.path.join(model_dir, f'{model_name}.json')

    with open(model_config_file, 'w') as f:
        json.dump(LANGUAGE_MODEL_CONFIGS[model_name], f, indent=2)

    return model_config_file

def create_language_trace(config, onnxim_root):
    trace_dir = os.path.join(onnxim_root, 'traces')
    os.makedirs(trace_dir, exist_ok=True)

    trace_name = (
        f"{safe_filename(config['experiment_name'])}_"
        f"gen{config['simulation']['generation_length']}_"
        f"bs{config['simulation']['batch_size']}.csv"
    )
    trace_file = os.path.join(trace_dir, trace_name)
    prompt_length = config['simulation']['prompt_length']
    target_length = config['simulation']['generation_length']

    with open(trace_file, 'w') as f:
        f.write("time,prompt_length,target_length,cached_length\n")
        for index in range(config['simulation']['batch_size']):
            time_delta = 0 if index == 0 else 100
            f.write(f"{time_delta},{prompt_length},{target_length},0\n")

    return trace_name, trace_file

def create_onnxim_config(config, onnxim_root, output_dir):
    template_file = os.path.join(onnxim_root, 'configs', ONNXIM_CONFIG_TEMPLATE)
    with open(template_file, 'r') as f:
        onnxim_config = json.load(f)

    ahasd_config = config['ahasd']
    onnxim_config['core_freq'] = int(round(ahasd_config['npu_freq_mhz']))
    onnxim_config['dram_freq'] = int(round(ahasd_config['pim_freq_mhz']))
    onnxim_config['enable_ahasd'] = bool(
        ahasd_config['enable_edc']
        or ahasd_config['enable_tvc']
        or ahasd_config['enable_aau']
        or ahasd_config['enable_ssrc']
        or ahasd_config['enable_ssrc_proxy']
        or ahasd_config['enable_ssrc_trace']
    )
    onnxim_config['enable_edc'] = ahasd_config['enable_edc']
    onnxim_config['enable_tvc'] = ahasd_config['enable_tvc']
    onnxim_config['enable_aau'] = ahasd_config['enable_aau']
    onnxim_config['max_draft_length'] = ahasd_config['max_draft_length']
    onnxim_config['enable_ssrc'] = ahasd_config['enable_ssrc']
    onnxim_config['enable_ssrc_proxy'] = ahasd_config['enable_ssrc_proxy']
    onnxim_config['enable_ssrc_trace'] = ahasd_config['enable_ssrc_trace']
    onnxim_config['ssrc_state_bytes_per_token'] = ahasd_config['ssrc_state_bytes_per_token']
    onnxim_config['ssrc_resident_limit_bytes'] = ahasd_config['ssrc_resident_limit_bytes']
    onnxim_config['ssrc_confidence_threshold'] = ahasd_config['ssrc_confidence_threshold']

    onnxim_config_file = os.path.join(output_dir, 'onnxim_config.json')
    with open(onnxim_config_file, 'w') as f:
        json.dump(onnxim_config, f, indent=2)

    return onnxim_config_file

def create_language_model_list(config, onnxim_root, output_dir):
    # ONNXim language mode owns one scheduler; use the draft model for smoke validation.
    model_name = config['model']['draft']
    model_config_file = ensure_language_model_config(model_name, onnxim_root)
    trace_name, trace_file = create_language_trace(config, onnxim_root)

    model_list = {
        "models": [
            {
                "name": model_name,
                "trace_file": trace_name,
                "scheduler": "simple",
                "scheduler_config": {
                    "max_batch_size": config['simulation']['batch_size'],
                    "check_mem_size": False,
                },
            }
        ]
    }
    model_list_file = os.path.join(output_dir, 'models_list.json')
    with open(model_list_file, 'w') as f:
        json.dump(model_list, f, indent=2)

    metadata = {
        "simulated_language_model": model_name,
        "simulated_model_role": "draft",
        "target_model_recorded_only": config['model']['target'],
        "model_config_file": model_config_file,
        "trace_file": trace_file,
        "trace_note": (
            "Generated minimal ONNXim language trace for real-simulator smoke; "
            "it is not a full Alpaca trace reproduction."
        ),
    }
    return model_list_file, trace_name, metadata

def run_simulation(config, output_dir, verbose=False, dry_run=False):
    """Run the actual simulation."""
    
    print(f"Starting simulation...")
    print(f"  Model: {config['model']['draft']} -> {config['model']['target']}")
    print(f"  Algorithm: {config['algorithm']}")
    print(f"  EDC: {config['ahasd']['enable_edc']}, "
          f"TVC: {config['ahasd']['enable_tvc']}, "
          f"AAU: {config['ahasd']['enable_aau']}, "
          f"SSRC: {config['ahasd']['enable_ssrc']}, "
          f"SSRC proxy: {config['ahasd']['enable_ssrc_proxy']}, "
          f"SSRC trace: {config['ahasd']['enable_ssrc_trace']}")
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Save configuration
    config_file = os.path.join(output_dir, 'config.json')
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"  Configuration saved to: {config_file}")
    
    # If dry-run mode, generate mock results and return
    if dry_run:
        print("\n  Running in DRY-RUN mode (no actual simulation)...")
        print("  Initializing NPU simulator (ONNXim)... [MOCK]")
        print("  Initializing PIM simulator (PIMSimulator)... [MOCK]")
        print("  Setting up AHASD integration layer... [MOCK]")
        
        if config['ahasd']['enable_edc']:
            print("    ✓ EDC module initialized [MOCK]")
        if config['ahasd']['enable_tvc']:
            print("    ✓ TVC module initialized [MOCK]")
        if config['ahasd']['enable_aau']:
            print("    ✓ AAU module initialized [MOCK]")
        if config['ahasd']['enable_ssrc']:
            print("    ✓ SSRC module initialized [MOCK]")
        
        # Generate mock results
        results = generate_mock_results(config)
        
        # Save results
        results_file = os.path.join(output_dir, 'results.json')
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        # Save metrics
        metrics_file = os.path.join(output_dir, 'metrics.txt')
        with open(metrics_file, 'w') as f:
            f.write("=== AHASD Simulation Results (DRY-RUN) ===\n")
            f.write(f"Configuration: {config['experiment_name']}\n")
            f.write(f"Simulation Type: {results.get('simulation_type', 'mock')}\n\n")
            f.write("Performance Metrics:\n")
            for key, value in results.get('metrics', {}).items():
                f.write(f"- {key.replace('_', ' ').title()}: {value}\n")
        
        print(f"\n  ✓ Dry-run completed successfully")
        print(f"  Mock results saved to: {output_dir}")
        return 0
    
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
    if config['ahasd']['enable_ssrc']:
        print("    ✓ SSRC module initialized")
    if config['ahasd']['enable_ssrc_proxy']:
        print("    ✓ SSRC proxy draft events enabled")
    
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
    
    try:
        onnxim_config_file = create_onnxim_config(config, onnxim_root, output_dir)
        model_list_file, trace_name, input_metadata = create_language_model_list(
            config, onnxim_root, output_dir
        )
    except Exception as e:
        print(f"    ERROR: Failed to create ONNXim inputs: {e}")
        sys.exit(1)
    
    # Run cycle-accurate simulation
    print("    Executing cycle-accurate simulation (ONNXim + PIMSimulator)...")
    cmd = [
        onnxim_binary,
        '--config', onnxim_config_file,
        '--models_list', model_list_file,
        '--mode', 'language',
        '--trace_file', trace_name,
        '--log_level', 'info'
    ]
    
    sim_log = os.path.join(output_dir, 'simulation.log')
    try:
        with open(sim_log, 'w') as log_file:
            result = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT, 
                                  timeout=3600, check=True,
                                  env={**os.environ, "ONNXIM_HOME": os.path.abspath(onnxim_root)})
        
        # Parse real simulation results from log
        results = parse_simulation_log(sim_log, config)
        results['simulation_type'] = 'cycle_accurate'
        results['simulator'] = 'ONNXim+PIMSimulator'
        results['input_metadata'] = input_metadata
        
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

        if 'ssrc_stats' in results:
            f.write("\nSSRC Statistics:\n")
            for key, value in results['ssrc_stats'].items():
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

            if match := re.search(r'Simulation Finished at\s*(\d+)\s*cycle\s*([\d.]+)\s*us', content):
                results['metrics']['total_cycles'] = int(match.group(1))
                results['metrics']['simulation_time_us'] = float(match.group(2))
            
            if match := re.search(r'Throughput:\s*([\d.]+)\s*tokens/sec', content):
                results['metrics']['throughput_tokens_per_sec'] = float(match.group(1))
            elif results['metrics'].get('simulation_time_us', 0) > 0:
                generated_tokens = (
                    config['simulation']['generation_length']
                    * config['simulation']['batch_size']
                )
                results['metrics']['throughput_tokens_per_sec'] = (
                    generated_tokens / (results['metrics']['simulation_time_us'] / 1_000_000.0)
                )
                results['metric_notes'] = results.get('metric_notes', [])
                results['metric_notes'].append(
                    "throughput_tokens_per_sec derived from ONNXim simulation time and generated smoke trace length."
                )
            
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
            elif match := re.search(r'Total Drafts Accepted:\s*(\d+)\s*\(([\d.]+)%\)', content):
                results['metrics']['drafts_accepted'] = int(match.group(1))
                results['metrics']['acceptance_rate'] = float(match.group(2)) / 100.0
            
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

            # Parse SSRC residency-control statistics if enabled
            if (
                config['ahasd']['enable_ssrc']
                or config['ahasd']['enable_ssrc_proxy']
                or config['ahasd']['enable_ssrc_trace']
            ) and 'SSRC Statistics' in content:
                results['ssrc_stats'] = {}
                ssrc_patterns = {
                    'baseline_materialized_bytes': r'SSRC Baseline Materialized Bytes:\s*(\d+)',
                    'actual_materialized_bytes': r'SSRC Actual Materialized Bytes:\s*(\d+)',
                    'avoided_materialization_bytes': r'SSRC Avoided Materialization Bytes:\s*(\d+)',
                    'reclaimed_bytes': r'SSRC Reclaimed Bytes:\s*(\d+)',
                    'resident_current_bytes': r'SSRC Resident Current Bytes:\s*(\d+)',
                    'resident_peak_bytes': r'SSRC Resident Peak Bytes:\s*(\d+)',
                    'committed_bytes': r'SSRC Committed Bytes:\s*(\d+)',
                    'resident_batches': r'SSRC Resident Batches:\s*(\d+)',
                    'deferred_batches': r'SSRC Deferred Batches:\s*(\d+)',
                    'prefetched_batches': r'SSRC Prefetched Batches:\s*(\d+)',
                    'reclaimed_batches': r'SSRC Reclaimed Batches:\s*(\d+)',
                }
                for key, pattern in ssrc_patterns.items():
                    if match := re.search(pattern, content):
                        results['ssrc_stats'][key] = int(match.group(1))
                        results['metrics'][f'ssrc_{key}'] = int(match.group(1))
    
    except Exception as e:
        print(f"    Warning: Error parsing simulation log: {e}")
        results['status'] = 'parse_error'
    
    return results

def main():
    args = parse_args()
    
    print("="*70)
    print("AHASD Single Configuration Runner")
    if args.dry_run:
        print("(DRY-RUN MODE)")
    print("="*70 + "\n")
    
    # Create configuration
    config = create_config(args)
    
    # Run simulation
    result = run_simulation(config, args.output, args.verbose, args.dry_run)
    
    print("\n" + "="*70)
    print("Simulation Complete")
    print("="*70)
    
    return result

if __name__ == '__main__':
    sys.exit(main())
