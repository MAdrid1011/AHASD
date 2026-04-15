#!/usr/bin/env python3
"""Run and aggregate AHASD contract-style evaluation jobs."""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


MODEL_SETS = {
    "quick": ["llama2-7b-llama2-13b"],
    "paper": [
        "opt-1.3b-opt-6.7b",
        "llama2-7b-llama2-13b",
        "palm-8b-palm-62b",
    ],
}

ALGORITHMS = ["specdec", "svip", "adaedl", "banditspec"]

CONFIGS = {
    "baseline": [],
    "npu_pim": ["--enable-ahasd"],
    "npu_pim_aau": ["--enable-ahasd", "--enable-aau"],
    "npu_pim_aau_edc": ["--enable-ahasd", "--enable-aau", "--enable-edc"],
    "ahasd_full": ["--enable-ahasd", "--enable-aau", "--enable-edc", "--enable-tvc"],
    "ahasd_full_ssrc": [
        "--enable-ahasd",
        "--enable-aau",
        "--enable-edc",
        "--enable-tvc",
        "--enable-ssrc",
        "--enable-ssrc-trace",
    ],
}

METRIC_KEYS = [
    "total_cycles",
    "simulation_time_us",
    "throughput_tokens_per_sec",
    "energy_mj",
    "energy_efficiency_tokens_per_mj",
    "dram_pim_total_power_w",
    "estimated_energy_mj_from_power_time",
    "ahasd_cycle_coupling_active",
    "drafts_generated",
    "drafts_accepted",
    "acceptance_rate",
    "ssrc_baseline_materialized_bytes",
    "ssrc_actual_materialized_bytes",
    "ssrc_avoided_materialization_bytes",
    "ssrc_materialization_avoidance_ratio",
    "ssrc_resident_peak_bytes",
    "ssrc_deferred_batches",
    "ssrc_modeled_dram_request_size_bytes",
    "ssrc_modeled_dram_latency_cycles",
    "ssrc_modeled_dram_request_equiv",
    "ssrc_raw_total_cycles",
    "ssrc_modeled_unclamped_avoided_memory_cycles",
    "ssrc_modeled_upper_bound_avoided_memory_cycles",
    "ssrc_modeled_upper_bound_adjusted_cycles",
    "ssrc_modeled_upper_bound_cycle_reduction_ratio",
    "ssrc_modeled_avoided_memory_cycles",
    "ssrc_modeled_adjusted_cycles",
    "ssrc_modeled_cycle_reduction_ratio",
    "ssrc_metric_quality",
]


def parse_csvish(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run an AHASD batch evaluation through the verified single-config runner."
    )
    parser.add_argument("--output", default=None, help="Output directory")
    parser.add_argument("--model-set", choices=sorted(MODEL_SETS), default="paper")
    parser.add_argument("--models", default=None, help="Comma-separated model pairs")
    parser.add_argument("--algorithms", default=",".join(ALGORITHMS))
    parser.add_argument("--configs", default=",".join(CONFIGS))
    parser.add_argument("--gen-length", type=int, default=1024)
    parser.add_argument("--prompt-length", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--max-draft-length", type=int, default=16)
    parser.add_argument("--npu-freq", type=float, default=1000.0)
    parser.add_argument("--pim-freq", type=float, default=800.0)
    parser.add_argument("--num-pim-ranks", type=int, default=16)
    parser.add_argument("--ssrc-confidence-threshold", type=float, default=0.8)
    parser.add_argument("--ssrc-resident-limit-mb", type=float, default=32.0)
    parser.add_argument("--ssrc-state-bytes-per-token", type=int, default=524288)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--enable-trace", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Run only the first N jobs")
    parser.add_argument(
        "--skip-hardware-validation",
        action="store_true",
        help="Do not run validate_hardware_costs.py after the simulation jobs.",
    )
    return parser.parse_args()


def repo_root():
    return Path(__file__).resolve().parents[1]


def default_output_dir(root):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return root / "results" / f"contract_{stamp}"


def selected_values(args):
    models = parse_csvish(args.models) if args.models else MODEL_SETS[args.model_set]
    algorithms = parse_csvish(args.algorithms)
    configs = parse_csvish(args.configs)

    unknown_algorithms = sorted(set(algorithms) - set(ALGORITHMS))
    unknown_configs = sorted(set(configs) - set(CONFIGS))
    if unknown_algorithms:
        raise ValueError(f"Unknown algorithms: {', '.join(unknown_algorithms)}")
    if unknown_configs:
        raise ValueError(f"Unknown configs: {', '.join(unknown_configs)}")

    return models, algorithms, configs


def run_one(root, args, output_root, model, algorithm, config_name):
    output_dir = output_root / f"{model}_{algorithm}_{config_name}"
    cmd = [
        sys.executable,
        str(root / "scripts" / "run_single_config.py"),
        "--model",
        model,
        "--algorithm",
        algorithm,
        "--output",
        str(output_dir),
        "--gen-length",
        str(args.gen_length),
        "--prompt-length",
        str(args.prompt_length),
        "--batch-size",
        str(args.batch_size),
        "--max-draft-length",
        str(args.max_draft_length),
        "--npu-freq",
        str(args.npu_freq),
        "--pim-freq",
        str(args.pim_freq),
        "--num-pim-ranks",
        str(args.num_pim_ranks),
    ]
    cmd.extend(CONFIGS[config_name])
    if config_name == "ahasd_full_ssrc":
        cmd.extend(
            [
                "--ssrc-confidence-threshold",
                str(args.ssrc_confidence_threshold),
                "--ssrc-resident-limit-mb",
                str(args.ssrc_resident_limit_mb),
                "--ssrc-state-bytes-per-token",
                str(args.ssrc_state_bytes_per_token),
            ]
        )
    if args.enable_trace:
        cmd.append("--enable-trace")
    if args.dry_run:
        cmd.append("--dry-run")

    log_file = output_dir / "runner.log"
    output_dir.mkdir(parents=True, exist_ok=True)
    start = time.time()
    with log_file.open("w") as log:
        proc = subprocess.run(cmd, cwd=root, stdout=log, stderr=subprocess.STDOUT)
    duration_s = time.time() - start

    result = {
        "model": model,
        "algorithm": algorithm,
        "config": config_name,
        "output_dir": str(output_dir),
        "runner_log": str(log_file),
        "returncode": proc.returncode,
        "duration_s": duration_s,
        "status": "completed" if proc.returncode == 0 else "failed",
        "metrics": {},
        "result_path": str(output_dir / "results.json"),
    }

    results_json = output_dir / "results.json"
    if results_json.exists():
        try:
            payload = json.loads(results_json.read_text())
            result["payload"] = payload
            result["metrics"] = payload.get("metrics", {})
            result["status"] = payload.get("status", result["status"])
        except json.JSONDecodeError as exc:
            result["status"] = "parse_error"
            result["error"] = f"Invalid results.json: {exc}"

    return result


def run_hardware_validation(root, output_root):
    log_path = output_root / "hardware_costs.txt"
    cmd = [sys.executable, str(root / "scripts" / "validate_hardware_costs.py")]
    proc = subprocess.run(cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log_path.write_text(proc.stdout)

    parsed = {
        "returncode": proc.returncode,
        "log_path": str(log_path),
    }
    if match := re.search(r"AHASD Overhead:\s*([\d.]+)%", proc.stdout):
        parsed["area_overhead_percent"] = float(match.group(1))
    if match := re.search(r"Total:\s*([\d.]+)\s*mm", proc.stdout):
        parsed["total_area_mm2"] = float(match.group(1))
    if match := re.search(r"Total AHASD Addition:\s*([\d.]+)\s*mW", proc.stdout):
        parsed["power_addition_mw"] = float(match.group(1))
    return parsed


def ratio(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def run_key(record):
    return record["model"], record["algorithm"]


def metric(record, key):
    value = record.get("metrics", {}).get(key)
    return value if isinstance(value, (int, float)) else None


def collect_ratios(runs, numerator_config, denominator_config, metric_key):
    by_group = {}
    for record in runs:
        by_group.setdefault(run_key(record), {})[record["config"]] = record

    values = []
    for configs in by_group.values():
        numerator = configs.get(numerator_config)
        denominator = configs.get(denominator_config)
        if numerator and denominator:
            value = ratio(metric(numerator, metric_key), metric(denominator, metric_key))
            if value is not None:
                values.append(value)
    return values


def make_metric_entry(value, status, source, note):
    return {
        "value": value,
        "status": status,
        "source": source,
        "note": note,
    }


def summarize_contract(runs, hardware, dry_run=False):
    if dry_run:
        source = "dry-run wiring check"
        return {
            "paper_throughput_speedup_vs_gpu_only_max": make_metric_entry(
                None,
                "dry_run",
                source,
                "Dry-run outputs only verify command wiring; no throughput evidence was measured.",
            ),
            "paper_energy_efficiency_speedup_vs_gpu_only_max": make_metric_entry(
                None,
                "dry_run",
                source,
                "Dry-run outputs only verify command wiring; no energy evidence was measured.",
            ),
            "paper_throughput_speedup_vs_specpim_max": make_metric_entry(
                None,
                "dry_run",
                source,
                "Dry-run outputs only verify command wiring; no SpecPIM comparison was measured.",
            ),
            "paper_energy_efficiency_speedup_vs_specpim_avg": make_metric_entry(
                None,
                "dry_run",
                source,
                "Dry-run outputs only verify command wiring; no energy-efficiency evidence was measured.",
            ),
            "paper_final_ablation_throughput_speedup_avg": make_metric_entry(
                None,
                "dry_run",
                source,
                "Dry-run outputs only verify command wiring; no ablation evidence was measured.",
            ),
            "paper_final_ablation_energy_efficiency_speedup_avg": make_metric_entry(
                None,
                "dry_run",
                source,
                "Dry-run outputs only verify command wiring; no ablation energy evidence was measured.",
            ),
            "paper_power_table_throughput_vs_base": make_metric_entry(
                None,
                "dry_run",
                source,
                "Dry-run outputs only verify command wiring; no throughput comparison was measured.",
            ),
            "paper_power_table_energy_per_token_vs_base": make_metric_entry(
                None,
                "dry_run",
                source,
                "Dry-run outputs only verify command wiring; no energy-per-token evidence was measured.",
            ),
            "paper_area_overhead_total_percent_text": make_metric_entry(
                None,
                "dry_run",
                source,
                "Dry-run outputs only verify command wiring; hardware validation was not measured.",
            ),
            "h100_hardware_area_overhead_percent": make_metric_entry(
                None,
                "dry_run",
                source,
                "Dry-run outputs only verify command wiring; hardware validation was not measured.",
            ),
            "ssrc_avoided_materialization_ratio_avg": make_metric_entry(
                None,
                "dry_run",
                source,
                "Dry-run outputs only verify command wiring; no SSRC materialization evidence was measured.",
            ),
            "ssrc_modeled_cycle_reduction_ratio_avg": make_metric_entry(
                None,
                "dry_run",
                source,
                "Dry-run outputs only verify command wiring; no modeled SSRC cycle evidence was measured.",
            ),
            "ssrc_modeled_upper_bound_cycle_reduction_ratio_avg": make_metric_entry(
                None,
                "dry_run",
                source,
                "Dry-run outputs only verify command wiring; no modeled SSRC upper-bound evidence was measured.",
            ),
        }

    ssrc_candidate = "ahasd_full_ssrc" if any(r["config"] == "ahasd_full_ssrc" for r in runs) else "ahasd_full"
    throughput_vs_gpu = collect_ratios(runs, ssrc_candidate, "baseline", "throughput_tokens_per_sec")
    throughput_vs_specpim = collect_ratios(runs, ssrc_candidate, "npu_pim", "throughput_tokens_per_sec")
    ablation_throughput = collect_ratios(runs, "ahasd_full", "baseline", "throughput_tokens_per_sec")
    energy_vs_gpu = collect_ratios(runs, ssrc_candidate, "baseline", "energy_efficiency_tokens_per_mj")
    energy_vs_specpim = collect_ratios(runs, ssrc_candidate, "npu_pim", "energy_efficiency_tokens_per_mj")
    ablation_energy = collect_ratios(runs, "ahasd_full", "baseline", "energy_efficiency_tokens_per_mj")

    ssrc_avoidance = []
    ssrc_modeled_cycle_reduction = []
    ssrc_modeled_upper_bound_cycle_reduction = []
    for record in runs:
        if record["config"] != "ahasd_full_ssrc":
            continue
        avoided = metric(record, "ssrc_avoided_materialization_bytes")
        baseline = metric(record, "ssrc_baseline_materialized_bytes")
        value = ratio(avoided, baseline)
        if value is not None:
            ssrc_avoidance.append(value)
        modeled_reduction = metric(record, "ssrc_modeled_cycle_reduction_ratio")
        if modeled_reduction is not None:
            ssrc_modeled_cycle_reduction.append(modeled_reduction)
        upper_bound_reduction = metric(record, "ssrc_modeled_upper_bound_cycle_reduction_ratio")
        if upper_bound_reduction is not None:
            ssrc_modeled_upper_bound_cycle_reduction.append(upper_bound_reduction)

    def entry_from_values(values, reducer, source, note):
        if not values:
            return make_metric_entry(None, "missing", source, note)
        value = reducer(values)
        return make_metric_entry(value, "measured", source, note)

    metrics = {
        "paper_throughput_speedup_vs_gpu_only_max": entry_from_values(
            throughput_vs_gpu,
            max,
            "cycle-accurate ONNXim batch evaluation",
            f"Max {ssrc_candidate}/baseline throughput ratio over completed model-algorithm groups.",
        ),
        "paper_energy_efficiency_speedup_vs_gpu_only_max": entry_from_values(
            energy_vs_gpu,
            max,
            "cycle-accurate ONNXim batch evaluation",
            "Missing until simulator emits Total Energy or Energy Efficiency.",
        ),
        "paper_throughput_speedup_vs_specpim_max": entry_from_values(
            throughput_vs_specpim,
            max,
            "cycle-accurate ONNXim batch evaluation",
            f"Uses npu_pim as the available SpecPIM-style proxy comparator for {ssrc_candidate}.",
        ),
        "paper_energy_efficiency_speedup_vs_specpim_avg": entry_from_values(
            energy_vs_specpim,
            lambda values: sum(values) / len(values),
            "cycle-accurate ONNXim batch evaluation",
            "Missing until simulator emits energy-efficiency metrics.",
        ),
        "paper_final_ablation_throughput_speedup_avg": entry_from_values(
            ablation_throughput,
            lambda values: sum(values) / len(values),
            "cycle-accurate ONNXim batch evaluation",
            "Average ahasd_full/baseline throughput ratio.",
        ),
        "paper_final_ablation_energy_efficiency_speedup_avg": entry_from_values(
            ablation_energy,
            lambda values: sum(values) / len(values),
            "cycle-accurate ONNXim batch evaluation",
            "Missing until simulator emits energy-efficiency metrics.",
        ),
        "paper_power_table_throughput_vs_base": entry_from_values(
            throughput_vs_gpu,
            lambda values: sum(values) / len(values),
            "cycle-accurate ONNXim batch evaluation",
            f"Average {ssrc_candidate}/baseline throughput ratio over completed groups.",
        ),
        "paper_power_table_energy_per_token_vs_base": make_metric_entry(
            None,
            "missing",
            "cycle-accurate ONNXim batch evaluation",
            "Energy per token cannot be derived without real energy output.",
        ),
        "paper_area_overhead_total_percent_text": make_metric_entry(
            hardware.get("area_overhead_percent") if hardware else None,
            "measured" if hardware and hardware.get("area_overhead_percent") is not None else "missing",
            "validate_hardware_costs.py",
            "Hardware validation overhead percentage.",
        ),
        "h100_hardware_area_overhead_percent": make_metric_entry(
            hardware.get("area_overhead_percent") if hardware else None,
            "measured" if hardware and hardware.get("area_overhead_percent") is not None else "missing",
            "validate_hardware_costs.py",
            "Same hardware model validation; not a GPU runtime metric.",
        ),
        "ssrc_avoided_materialization_ratio_avg": entry_from_values(
            ssrc_avoidance,
            lambda values: sum(values) / len(values),
            "cycle-accurate ONNXim batch evaluation",
            "Average avoided speculative-state materialization ratio for ahasd_full_ssrc.",
        ),
        "ssrc_modeled_cycle_reduction_ratio_avg": entry_from_values(
            ssrc_modeled_cycle_reduction,
            lambda values: sum(values) / len(values),
            "modeled SSRC sidecar cycle proxy",
            "Average materialization-capped modeled adjusted-cycle reduction ratio; diagnostic only and not a raw ONNXim cycle improvement.",
        ),
        "ssrc_modeled_upper_bound_cycle_reduction_ratio_avg": entry_from_values(
            ssrc_modeled_upper_bound_cycle_reduction,
            lambda values: sum(values) / len(values),
            "modeled SSRC sidecar cycle upper bound",
            "Average unclamped-request model after raw-cycle cap; upper-bound diagnostic only and not a raw ONNXim cycle improvement.",
        ),
    }

    return metrics


def write_summary_files(output_root, args, runs, hardware):
    contract_metrics = summarize_contract(runs, hardware, dry_run=args.dry_run)
    completed = [r for r in runs if r["status"] == "completed" and r["returncode"] == 0]
    failed = [r for r in runs if r not in completed]
    energy_present = (not args.dry_run) and any(
        metric(r, "energy_efficiency_tokens_per_mj") is not None
        or metric(r, "energy_mj") is not None
        for r in runs
    )
    estimated_energy_present = (not args.dry_run) and any(
        metric(r, "estimated_energy_mj_from_power_time") is not None
        for r in runs
    )

    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "generation_length": args.gen_length,
        "prompt_length": args.prompt_length,
        "batch_size": args.batch_size,
        "run_count": len(runs),
        "completed_count": len(completed),
        "failed_count": len(failed),
        "energy_metrics_available": energy_present,
        "estimated_energy_metrics_available": estimated_energy_present,
        "hardware_validation": hardware,
        "contract_metrics": contract_metrics,
        "runs": runs,
    }

    (output_root / "summary.json").write_text(json.dumps(summary, indent=2))
    (output_root / "contract_metrics.json").write_text(json.dumps(contract_metrics, indent=2))

    csv_path = output_root / "summary.csv"
    with csv_path.open("w", newline="") as f:
        fieldnames = [
            "model",
            "algorithm",
            "config",
            "status",
            "returncode",
            "duration_s",
        ] + METRIC_KEYS + ["output_dir"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in runs:
            row = {
                "model": record["model"],
                "algorithm": record["algorithm"],
                "config": record["config"],
                "status": record["status"],
                "returncode": record["returncode"],
                "duration_s": f"{record['duration_s']:.3f}",
                "output_dir": record["output_dir"],
            }
            for key in METRIC_KEYS:
                row[key] = record.get("metrics", {}).get(key, "")
            writer.writerow(row)

    md_lines = [
        "# AHASD Contract Evaluation Summary",
        "",
        f"- Dry run: {args.dry_run}",
        f"- Completed: {len(completed)}/{len(runs)}",
        f"- Energy metrics available: {energy_present}",
        f"- Estimated energy diagnostics available: {estimated_energy_present}",
        f"- Hardware area overhead: {contract_metrics['paper_area_overhead_total_percent_text']['value']}",
        "",
        "## Contract Metrics",
        "",
        "| Metric | Status | Value | Note |",
        "|---|---:|---:|---|",
    ]
    if args.dry_run:
        md_lines.insert(
            6,
            "- Evidence note: dry-run metric values are placeholders and are excluded from measured contract metrics.",
        )
    for key, item in contract_metrics.items():
        value = item["value"]
        value_text = "" if value is None else f"{value:.6g}" if isinstance(value, float) else str(value)
        md_lines.append(f"| {key} | {item['status']} | {value_text} | {item['note']} |")

    (output_root / "summary.md").write_text("\n".join(md_lines) + "\n")

    return summary


def main():
    args = parse_args()
    root = repo_root()
    output_root = Path(args.output) if args.output else default_output_dir(root)
    if not output_root.is_absolute():
        output_root = root / output_root
    output_root.mkdir(parents=True, exist_ok=True)

    models, algorithms, configs = selected_values(args)
    jobs = [(m, a, c) for m in models for a in algorithms for c in configs]
    if args.limit:
        jobs = jobs[: args.limit]

    print(f"AHASD contract evaluation output: {output_root}")
    print(f"Jobs: {len(jobs)}")

    runs = []
    for index, (model, algorithm, config_name) in enumerate(jobs, start=1):
        print(f"[{index}/{len(jobs)}] {model} {algorithm} {config_name}", flush=True)
        result = run_one(root, args, output_root, model, algorithm, config_name)
        runs.append(result)
        if result["returncode"] != 0 and args.fail_fast:
            break

    hardware = None
    if not args.skip_hardware_validation:
        print("Running hardware cost validation...", flush=True)
        hardware = run_hardware_validation(root, output_root)

    summary = write_summary_files(output_root, args, runs, hardware)
    print(f"Summary: {output_root / 'summary.json'}")
    print(f"Completed: {summary['completed_count']}/{summary['run_count']}")

    return 0 if summary["failed_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
