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
    "palm-8b": {
        "num_hidden_layers": 32,
        "hidden_size": 4096,
        "num_kv_heads": 16,
        "num_attention_heads": 16,
        "intermediate_size": 16384,
        "ffn_type": "palm",
        "activation_function": "swiglu",
        "vocab_size": 256000,
        "max_seq_length": 2048,
        "run_single_layer": True,
        "tensor_parallel_size": 1,
        "pipeline_parallel_size": 1,
        "source_note": "Generated from AHASD template PaLM-like 8B architecture for ONNXim validation.",
    },
    "palm-62b": {
        "num_hidden_layers": 64,
        "hidden_size": 8192,
        "num_kv_heads": 32,
        "num_attention_heads": 32,
        "intermediate_size": 32768,
        "ffn_type": "palm",
        "activation_function": "swiglu",
        "vocab_size": 256000,
        "max_seq_length": 2048,
        "run_single_layer": True,
        "tensor_parallel_size": 1,
        "pipeline_parallel_size": 1,
        "source_note": "Generated from AHASD template PaLM-like 62B architecture for ONNXim validation.",
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
    parser.add_argument('--enable-ahasd', action='store_true',
                       help='Enable AHASD integration without requiring a component flag')
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
            "enable_ahasd": (
                args.enable_ahasd
                or args.enable_edc
                or args.enable_tvc
                or args.enable_aau
                or args.enable_ssrc
                or args.enable_ssrc_proxy
                or args.enable_ssrc_trace
            ),
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
    onnxim_config['enable_ahasd'] = bool(ahasd_config['enable_ahasd'])
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

        if 'request_identity_stats' in results:
            f.write("\nRequest Identity Statistics:\n")
            for key, value in results['request_identity_stats'].items():
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

    def add_metric_note(note):
        results.setdefault('metric_notes', [])
        if note not in results['metric_notes']:
            results['metric_notes'].append(note)

    def record_energy_mj(value_mj, source):
        results['metrics']['energy_mj'] = value_mj
        results.setdefault('metric_quality', {})['energy_metric_source'] = source
    
    try:
        with open(log_file, 'r') as f:
            content = f.read()
            generated_tokens = (
                config['simulation']['generation_length']
                * config['simulation']['batch_size']
            )
            
            # Parse throughput and cycles
            if match := re.search(r'Total Simulation Cycles:\s*(\d+)', content):
                results['metrics']['total_cycles'] = int(match.group(1))

            if match := re.search(r'Simulation Finished at\s*(\d+)\s*cycle\s*([\d.]+)\s*us', content):
                results['metrics']['total_cycles'] = int(match.group(1))
                results['metrics']['simulation_time_us'] = float(match.group(2))
            
            if match := re.search(r'Throughput:\s*([\d.]+)\s*tokens/sec', content):
                results['metrics']['throughput_tokens_per_sec'] = float(match.group(1))
            elif results['metrics'].get('simulation_time_us', 0) > 0:
                results['metrics']['throughput_tokens_per_sec'] = (
                    generated_tokens / (results['metrics']['simulation_time_us'] / 1_000_000.0)
                )
                add_metric_note(
                    "throughput_tokens_per_sec derived from ONNXim simulation time and generated smoke trace length."
                )

            if config['ahasd']['enable_ahasd']:
                quality = results.setdefault('metric_quality', {})
                quality['raw_cycle_scope'] = 'onnxim_core_completion_cycles'
                if match := re.search(r'AHASD Metric Scope:\s*([A-Za-z0-9_\-]+)', content):
                    quality['ahasd_metric_scope'] = match.group(1)
                if match := re.search(r'AHASD Cycle Coupling:\s*([A-Za-z0-9_\-]+)', content):
                    quality['ahasd_cycle_coupling'] = match.group(1)
                    results['metrics']['ahasd_cycle_coupling_active'] = (
                        0 if match.group(1) == 'sidecar_only' else 1
                    )
                    if match.group(1) == 'sidecar_only':
                        add_metric_note(
                            "AHASD stats are sidecar accounting in this build; throughput uses raw ONNXim completion cycles, not adjusted AHASD cycles."
                        )
            
            # Parse energy metrics
            energy_patterns = [
                (r'Total Energy\s*\(mJ\)\s*:\s*([\d.eE+-]+)', 1.0, 'pim_memory_system_total_energy_mj'),
                (r'Total Energy\s*:\s*([\d.eE+-]+)\s*mJ', 1.0, 'simulator_total_energy_mj'),
                (r'Total Energy\s*\(uJ\)\s*:\s*([\d.eE+-]+)', 0.001, 'pim_memory_system_total_energy_uj'),
            ]
            for pattern, scale, source in energy_patterns:
                if match := re.search(pattern, content):
                    record_energy_mj(float(match.group(1)) * scale, source)
                    break
            
            if match := re.search(r'Energy Efficiency:\s*([\d.]+)\s*tokens/mJ', content):
                results['metrics']['energy_efficiency_tokens_per_mj'] = float(match.group(1))
            elif results['metrics'].get('energy_mj', 0) > 0:
                results['metrics']['energy_efficiency_tokens_per_mj'] = (
                    generated_tokens / results['metrics']['energy_mj']
                )
                add_metric_note(
                    "energy_efficiency_tokens_per_mj derived from parsed simulator total energy and generated smoke trace length."
                )

            if match := re.search(r'Total Power\s*\(watts\)\s*:\s*([\d.eE+-]+)', content):
                total_power_w = float(match.group(1))
                results['metrics']['dram_pim_total_power_w'] = total_power_w
                sim_time_us = results['metrics'].get('simulation_time_us')
                if sim_time_us:
                    results['metrics']['estimated_energy_mj_from_power_time'] = (
                        total_power_w * sim_time_us * 1e-3
                    )
                    results.setdefault('metric_quality', {})[
                        'estimated_energy_source'
                    ] = 'Total Power(watts) multiplied by ONNXim simulation_time_us; not used as canonical energy_mj.'
                    add_metric_note(
                        "estimated_energy_mj_from_power_time is diagnostic only and is not used for canonical energy speedups."
                    )

            if 'energy_mj' not in results['metrics']:
                add_metric_note(
                    "No simulator-level Total Energy(mJ/uJ) or Total Energy: ... mJ line was found; canonical energy_mj is missing."
                )
            
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
                    'modeled_dram_request_size_bytes': r'SSRC Modeled DRAM Request Size Bytes:\s*(\d+)',
                    'modeled_dram_latency_cycles': r'SSRC Modeled DRAM Latency Cycles:\s*(\d+)',
                    'modeled_dram_request_equiv': r'SSRC Modeled DRAM Request Equiv:\s*(\d+)',
                    'raw_total_cycles': r'SSRC Raw Total Cycles:\s*(\d+)',
                    'modeled_unclamped_avoided_memory_cycles': r'SSRC Modeled Unclamped Avoided Memory Cycles:\s*(\d+)',
                    'modeled_upper_bound_avoided_memory_cycles': r'SSRC Modeled Upper Bound Avoided Memory Cycles:\s*(\d+)',
                    'modeled_upper_bound_adjusted_cycles': r'SSRC Modeled Upper Bound Adjusted Cycles:\s*(\d+)',
                    'modeled_avoided_memory_cycles': r'SSRC Modeled Avoided Memory Cycles:\s*(\d+)',
                    'modeled_adjusted_cycles': r'SSRC Modeled Adjusted Cycles:\s*(\d+)',
                }
                for key, pattern in ssrc_patterns.items():
                    if match := re.search(pattern, content):
                        results['ssrc_stats'][key] = int(match.group(1))
                        results['metrics'][f'ssrc_{key}'] = int(match.group(1))
                ssrc_ratio_patterns = {
                    'materialization_avoidance_ratio': r'SSRC Materialization Avoidance Ratio:\s*([\d.eE+-]+)',
                    'modeled_upper_bound_cycle_reduction_ratio': r'SSRC Modeled Upper Bound Cycle Reduction Ratio:\s*([\d.eE+-]+)',
                    'modeled_cycle_reduction_ratio': r'SSRC Modeled Cycle Reduction Ratio:\s*([\d.eE+-]+)',
                }
                for key, pattern in ssrc_ratio_patterns.items():
                    if match := re.search(pattern, content):
                        value = float(match.group(1))
                        results['ssrc_stats'][key] = value
                        results['metrics'][f'ssrc_{key}'] = value
                if match := re.search(
                    r'SSRC Metric Quality:\s*([A-Za-z0-9_\-]+)',
                    content,
                ):
                    value = match.group(1)
                    results['ssrc_stats']['metric_quality'] = value
                    results['metrics']['ssrc_metric_quality'] = value
                    results.setdefault('metric_quality', {})['ssrc_metric_quality'] = value
                    add_metric_note(
                        "SSRC modeled cycle metrics are sidecar diagnostics and are not raw ONNXim cycle coupling."
                    )

            request_identity_marker = 'SSRC Request Identity'
            if request_identity_marker in content:
                results['request_identity_stats'] = {}
                request_identity_patterns = {
                    'bridge_active': r'SSRC Request Identity Bridge Active:\s*(\d+)',
                    'tagged_requests': r'SSRC Request Identity Tagged Requests:\s*(\d+)',
                    'tagged_bytes': r'SSRC Request Identity Tagged Bytes:\s*(\d+)',
                    'tagged_read_bytes': r'SSRC Request Identity Tagged Read Bytes:\s*(\d+)',
                    'tagged_write_bytes': r'SSRC Request Identity Tagged Write Bytes:\s*(\d+)',
                }
                for key, pattern in request_identity_patterns.items():
                    if match := re.search(pattern, content):
                        value = int(match.group(1))
                        results['request_identity_stats'][key] = value
                        results['metrics'][f'request_identity_{key}'] = value

                if match := re.search(
                    r'SSRC Request Identity Tagged Class:\s*([A-Za-z0-9_\-]+)',
                    content,
                ):
                    tagged_class = match.group(1)
                    results['request_identity_stats']['tagged_class'] = tagged_class
                    results['metrics']['request_identity_tagged_class'] = tagged_class

                add_metric_note(
                    "request_identity_* metrics are attribution diagnostics derived from SSRC request-tag summary lines."
                )

            trace_semantic_marker = 'SSRC Trace Semantic'
            if trace_semantic_marker in content:
                results['trace_semantic_stats'] = {}
                trace_semantic_patterns = {
                    'active': r'SSRC Trace Semantic Active:\s*(\d+)',
                    'resident_batches': r'SSRC Trace Semantic Resident Batches:\s*(\d+)',
                    'deferred_batches': r'SSRC Trace Semantic Deferred Batches:\s*(\d+)',
                    'prefetched_batches': r'SSRC Trace Semantic Prefetched Batches:\s*(\d+)',
                    'reclaimed_batches': r'SSRC Trace Semantic Reclaimed Batches:\s*(\d+)',
                    'accepted_bytes': r'SSRC Trace Semantic Accepted Bytes:\s*(\d+)',
                }
                for key, pattern in trace_semantic_patterns.items():
                    if match := re.search(pattern, content):
                        value = int(match.group(1))
                        results['trace_semantic_stats'][key] = value
                        results['metrics'][f'trace_semantic_{key}'] = value

                trace_semantic_ratio_patterns = {
                    'avg_queue_pressure': r'SSRC Trace Semantic Avg Queue Pressure:\s*([\d.eE+-]+)',
                    'avg_residency_pressure': r'SSRC Trace Semantic Avg Residency Pressure:\s*([\d.eE+-]+)',
                    'avg_tvc_slack_proxy': r'SSRC Trace Semantic Avg TVC Slack Proxy:\s*([\d.eE+-]+)',
                }
                for key, pattern in trace_semantic_ratio_patterns.items():
                    if match := re.search(pattern, content):
                        value = float(match.group(1))
                        results['trace_semantic_stats'][key] = value
                        results['metrics'][f'trace_semantic_{key}'] = value

                add_metric_note(
                    "trace_semantic_* metrics are decision-aware observability diagnostics derived from trace-valid SSRC batches."
                )
            if 'ssrc_stats' in results and 'request_identity_stats' in results:
                avoided_materialization_bytes = results['ssrc_stats'].get('avoided_materialization_bytes')
                tagged_write_bytes = results['request_identity_stats'].get('tagged_write_bytes')
                if isinstance(avoided_materialization_bytes, int) and isinstance(tagged_write_bytes, int):
                    overlap_upper_bound_bytes = min(
                        avoided_materialization_bytes,
                        tagged_write_bytes,
                    )
                    overlap_stats = {
                        'upper_bound_bytes': overlap_upper_bound_bytes,
                        'coverage_gap_bytes': abs(
                            avoided_materialization_bytes - tagged_write_bytes
                        ),
                        'upper_bound_vs_avoided_ratio': (
                            float(overlap_upper_bound_bytes) / float(avoided_materialization_bytes)
                            if avoided_materialization_bytes > 0
                            else 0.0
                        ),
                        'upper_bound_vs_tagged_write_ratio': (
                            float(overlap_upper_bound_bytes) / float(tagged_write_bytes)
                            if tagged_write_bytes > 0
                            else 0.0
                        ),
                    }
                    results['ssrc_request_overlap_stats'] = overlap_stats
                    for key, value in overlap_stats.items():
                        results['metrics'][f'ssrc_request_overlap_{key}'] = value

                    add_metric_note(
                        "ssrc_request_overlap_* metrics are derived attribution bounds from "
                        "ssrc_avoided_materialization_bytes and request_identity_tagged_write_bytes; "
                        "they are upper-bound overlap diagnostics, not exact per-request intersections."
                    )
    
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
