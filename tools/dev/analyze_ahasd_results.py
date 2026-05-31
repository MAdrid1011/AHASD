#!/usr/bin/env python3
"""
AHASD Results Analysis Script
Analyzes simulation results and generates comparison plots
"""

import json
import os
import sys
import glob
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
from typing import Dict, List

def parse_metrics_file(filepath: str) -> Dict:
    """Parse metrics.txt file and extract key-value pairs."""
    metrics = {}
    
    with open(filepath, 'r') as f:
        lines = f.readlines()
        
    for line in lines:
        line = line.strip()
        if ':' in line and not line.startswith('==='):
            parts = line.split(':', 1)
            if len(parts) == 2:
                key = parts[0].strip('- ').strip()
                value_str = parts[1].strip()
                
                # Extract numeric value
                value_parts = value_str.split()
                if value_parts:
                    try:
                        # Try to extract number (handles percentage and units)
                        value_clean = value_parts[0].replace('(', '').replace('%', '').replace(',', '')
                        if value_clean.replace('.', '').replace('-', '').isdigit():
                            metrics[key] = float(value_clean)
                    except:
                        metrics[key] = value_str
    
    return metrics

def load_all_results(results_dir: str) -> Dict:
    """Load all simulation results from directory."""
    results = {}
    
    # Find all metrics files
    metrics_files = glob.glob(os.path.join(results_dir, '**/metrics.txt'), recursive=True)
    
    for metrics_file in metrics_files:
        # Extract configuration from path
        rel_path = os.path.relpath(metrics_file, results_dir)
        config_name = os.path.dirname(rel_path)
        
        if config_name:
            metrics = parse_metrics_file(metrics_file)
            results[config_name] = metrics
            
            # Also load config.json if available
            config_json = os.path.join(os.path.dirname(metrics_file), 'config.json')
            if os.path.exists(config_json):
                with open(config_json, 'r') as f:
                    config_data = json.load(f)
                    results[config_name]['config'] = config_data
    
    return results

def generate_throughput_comparison(results: Dict, output_dir: str):
    """Generate throughput comparison plot."""
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # Group by model and algorithm
    models = set()
    configs = set()
    
    for key in results.keys():
        parts = key.split('_')
        if len(parts) >= 3:
            model = parts[0]
            config = '_'.join(parts[2:])
            models.add(model)
            configs.add(config)
    
    models = sorted(list(models))
    configs = sorted(list(configs))
    
    # Extract throughput data
    throughput_data = {config: [] for config in configs}
    
    for model in models:
        for config in configs:
            # Find matching result
            matching_keys = [k for k in results.keys() 
                           if k.startswith(model) and k.endswith(config)]
            
            if matching_keys:
                key = matching_keys[0]
                throughput = results[key].get('Throughput', 0.0)
                if isinstance(throughput, str):
                    throughput = float(throughput.split()[0])
                throughput_data[config].append(throughput)
            else:
                throughput_data[config].append(0.0)
    
    # Plot grouped bar chart
    x = np.arange(len(models))
    width = 0.15
    multiplier = 0
    
    for config, throughputs in throughput_data.items():
        offset = width * multiplier
        ax.bar(x + offset, throughputs, width, label=config)
        multiplier += 1
    
    ax.set_xlabel('Model Configuration')
    ax.set_ylabel('Throughput (tokens/sec)')
    ax.set_title('AHASD Throughput Comparison')
    ax.set_xticks(x + width * (len(configs) - 1) / 2)
    ax.set_xticklabels(models, rotation=45, ha='right')
    ax.legend(loc='upper left', bbox_to_anchor=(1, 1))
    ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'throughput_comparison.png'), dpi=300)
    print(f"  Saved: throughput_comparison.png")
    plt.close()

def generate_energy_efficiency_plot(results: Dict, output_dir: str):
    """Generate energy efficiency comparison plot."""
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Extract configurations
    baseline_configs = [k for k in results.keys() if 'baseline' in k]
    ahasd_configs = [k for k in results.keys() if 'ahasd_full' in k]
    
    ee_baseline = []
    ee_ahasd = []
    labels = []
    
    for base_key in baseline_configs:
        # Find corresponding AHASD config
        parts = base_key.split('_baseline')
        if parts:
            prefix = parts[0]
            ahasd_key = f"{prefix}_ahasd_full"
            
            if ahasd_key in results:
                ee_base = results[base_key].get('Energy Efficiency', 0.0)
                ee_full = results[ahasd_key].get('Energy Efficiency', 0.0)
                
                if isinstance(ee_base, str):
                    ee_base = float(ee_base.split()[0])
                if isinstance(ee_full, str):
                    ee_full = float(ee_full.split()[0])
                
                ee_baseline.append(ee_base)
                ee_ahasd.append(ee_full)
                labels.append(prefix)
    
    x = np.arange(len(labels))
    width = 0.35
    
    ax.bar(x - width/2, ee_baseline, width, label='Baseline', alpha=0.8)
    ax.bar(x + width/2, ee_ahasd, width, label='AHASD Full', alpha=0.8)
    
    ax.set_xlabel('Configuration')
    ax.set_ylabel('Energy Efficiency (tokens/mJ)')
    ax.set_title('Energy Efficiency Comparison')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha='right')
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'energy_efficiency.png'), dpi=300)
    print(f"  Saved: energy_efficiency.png")
    plt.close()

def generate_ablation_study(results: Dict, output_dir: str):
    """Generate ablation study plot."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    # Find one model configuration for ablation
    model_prefix = None
    for key in results.keys():
        if '_baseline' in key:
            model_prefix = key.split('_baseline')[0]
            break
    
    if not model_prefix:
        print("  Warning: No baseline found for ablation study")
        return
    
    # Define ablation configurations
    ablation_configs = [
        'baseline',
        'npu_pim',
        'npu_pim_aau',
        'npu_pim_aau_edc',
        'ahasd_full'
    ]
    
    throughputs = []
    energy_effs = []
    config_labels = ['Baseline', 'NPU+PIM', '+AAU', '+EDC', '+TVC (Full)']
    
    for config in ablation_configs:
        key = f"{model_prefix}_{config}"
        if key in results:
            tp = results[key].get('Throughput', 0.0)
            ee = results[key].get('Energy Efficiency', 0.0)
            
            if isinstance(tp, str):
                tp = float(tp.split()[0])
            if isinstance(ee, str):
                ee = float(ee.split()[0])
            
            throughputs.append(tp)
            energy_effs.append(ee)
        else:
            throughputs.append(0.0)
            energy_effs.append(0.0)
    
    # Normalize to baseline
    if throughputs[0] > 0:
        throughputs_norm = [tp / throughputs[0] for tp in throughputs]
    else:
        throughputs_norm = throughputs
    
    if energy_effs[0] > 0:
        energy_effs_norm = [ee / energy_effs[0] for ee in energy_effs]
    else:
        energy_effs_norm = energy_effs
    
    # Plot throughput
    x = np.arange(len(config_labels))
    bars1 = ax1.bar(x, throughputs_norm, alpha=0.8, color='steelblue')
    ax1.axhline(y=1.0, color='r', linestyle='--', alpha=0.5, label='Baseline')
    ax1.set_xlabel('Configuration')
    ax1.set_ylabel('Normalized Throughput')
    ax1.set_title('Ablation Study: Throughput')
    ax1.set_xticks(x)
    ax1.set_xticklabels(config_labels, rotation=30, ha='right')
    ax1.grid(axis='y', alpha=0.3)
    ax1.legend()
    
    # Add value labels
    for bar in bars1:
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.2f}×',
                ha='center', va='bottom', fontsize=9)
    
    # Plot energy efficiency
    bars2 = ax2.bar(x, energy_effs_norm, alpha=0.8, color='coral')
    ax2.axhline(y=1.0, color='r', linestyle='--', alpha=0.5, label='Baseline')
    ax2.set_xlabel('Configuration')
    ax2.set_ylabel('Normalized Energy Efficiency')
    ax2.set_title('Ablation Study: Energy Efficiency')
    ax2.set_xticks(x)
    ax2.set_xticklabels(config_labels, rotation=30, ha='right')
    ax2.grid(axis='y', alpha=0.3)
    ax2.legend()
    
    # Add value labels
    for bar in bars2:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.2f}×',
                ha='center', va='bottom', fontsize=9)
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'ablation_study.png'), dpi=300)
    print(f"  Saved: ablation_study.png")
    plt.close()

def generate_summary_table(results: Dict, output_dir: str):
    """Generate summary table in CSV format."""
    csv_path = os.path.join(output_dir, 'summary_table.csv')
    
    with open(csv_path, 'w') as f:
        # Header
        f.write('Configuration,Throughput (tokens/s),Energy (mJ),Energy Efficiency (tokens/mJ),'
                'Draft Acceptance Rate (%),EDC Accuracy (%),TVC Success Rate (%)\n')
        
        # Sort results by configuration name
        for config_name in sorted(results.keys()):
            metrics = results[config_name]
            
            throughput = metrics.get('Throughput', 0.0)
            energy = metrics.get('Energy', 0.0)
            ee = metrics.get('Energy Efficiency', 0.0)
            accept_rate = metrics.get('Total Drafts Accepted', 0.0)
            edc_acc = metrics.get('Prediction Accuracy', 0.0)
            tvc_success = metrics.get('Success Rate', 0.0)
            
            f.write(f'{config_name},{throughput},{energy},{ee},'
                   f'{accept_rate},{edc_acc},{tvc_success}\n')
    
    print(f"  Saved: summary_table.csv")

def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_ahasd_results.py <results_directory>")
        sys.exit(1)
    
    results_dir = sys.argv[1]
    
    if not os.path.exists(results_dir):
        print(f"Error: Directory '{results_dir}' not found")
        sys.exit(1)
    
    print(f"Analyzing results from: {results_dir}")
    
    # Load all results
    print("Loading results...")
    results = load_all_results(results_dir)
    print(f"  Found {len(results)} configurations")
    
    if not results:
        print("No results found!")
        sys.exit(1)
    
    # Create plots directory
    plots_dir = os.path.join(results_dir, 'plots')
    os.makedirs(plots_dir, exist_ok=True)
    
    print("\nGenerating plots...")
    
    try:
        generate_throughput_comparison(results, plots_dir)
        generate_energy_efficiency_plot(results, plots_dir)
        generate_ablation_study(results, plots_dir)
        generate_summary_table(results, plots_dir)
    except Exception as e:
        print(f"  Warning: Error generating plots: {e}")
        import traceback
        traceback.print_exc()
    
    print("\nAnalysis complete!")
    print(f"Results saved to: {plots_dir}")

if __name__ == '__main__':
    main()

