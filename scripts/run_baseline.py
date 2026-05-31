#!/usr/bin/env python3
"""
C1 — Reusable baseline runner.

Resolves a committed overlay under `configs/baselines/<name>.json` against
its `_inherits` base, stamps in workload + acceptance choices, runs the
Simulator, and dumps log + parsed metrics into the output directory.

Designed to be consumed by D1's matrix driver (3 model pairs × 4
algorithms × 4 configs) — every cell there is one invocation of this
script with a different `--baseline` + `--model-pair`. For C1 we only
need to prove two presets (npu_only, ahasd_full) match the B2.7 axes.

Usage:

    scripts/run_baseline.py \
        --baseline npu_only \
        --model-pair opt-125m:opt-125m-t \
        --workload-trace workloads/smoke_p4_g8_2req.csv \
        --acceptance-csv workflow/b27/accept_trace.csv \
        --output-dir workflow/c1/npu_only_opt125m
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

BASELINES_DIR = REPO / "configs/baselines"


# Metric extraction patterns for ONNXim logs. Copy-paste is intentional here;
# extracting to a shared module is scope for a later refactor.
REGEXES = [
    ("sim_finished_cycles",      r"Simulation Finished at (\d+) cycle"),
    ("final_npu_cycle",          r"\[PIMBackend\] final_npu_cycle=(\d+)"),
    ("final_pim_cycle",          r"final_pim_cycle=(\d+)"),
    ("gtsu_stall_cycles",        r"GTSU switches: \d+\s*;\s*total stall cycles:\s*(\d+)"),
    ("tvc_hold_cycles",          r"TVC hold cycles:\s*(\d+)"),
    ("attention_class_requests", r"attention-class requests through PIM:\s*(\d+)"),
    ("total_energy_mj",          r"Total Energy:\s*([\d.]+) mJ"),
    ("draft_rounds",             r"Total Draft Rounds:\s*(\d+)"),
    ("verifies",                 r"Total Verifies:\s*(\d+)"),
    ("preverifies",              r"Total Pre-verifies:\s*(\d+)"),
    ("total_draft_tokens_generated", r"Total Draft Tokens Generated:\s*(\d+)"),
    ("total_verified_draft_tokens", r"Total Verified Draft Tokens:\s*(\d+)"),
    ("total_rejected_draft_tokens", r"Total Rejected Draft Tokens:\s*(\d+)"),
    ("rejected_draft_token_ratio", r"Rejected Draft Token Ratio:\s*([\d.]+)"),
    ("pim_useful_compute_ratio", r"PIM Useful Compute Ratio:\s*([\d.]+)"),
    ("total_preverify_tokens",   r"Total Pre-verify Tokens:\s*(\d+)"),
    ("pim_aau_fused_events",     r"AAU fused events:\s*(\d+)"),
    ("gtsu_switches",            r"GTSU switches:\s*(\d+)"),
    ("acceptance_ratio",         r"accept_ratio=([\d.]+)"),
    ("acceptance_samples",       r"Acceptance Samples:\s*(\d+)"),
    ("mean_draft_length",        r"Acceptance Samples:\s*\d+\s*\|\s*mean_k=([\d.]+)"),
    ("mean_accepted_length",     r"Acceptance Samples:\s*\d+\s*\|\s*mean_k=[\d.]+\s*\|\s*mean_accepted=([\d.]+)"),
    ("mean_uncommitted_batches", r"Mean Uncommitted Batches:\s*([\d.]+)"),
    ("peak_uncommitted_batches", r"Peak Uncommitted Batches:\s*([\d.]+)"),
    ("peak_speculative_kv_bytes", r"Peak Speculative KV Bytes:\s*(\d+)"),
    ("rejected_kv_write_bytes",  r"Rejected KV Write Bytes:\s*(\d+)"),
    ("total_kv_write_bytes",     r"Total KV Write Bytes:\s*(\d+)"),
    ("rejected_kv_write_ratio",  r"Rejected KV Write Ratio:\s*([\d.]+)"),
    ("external_kv_traffic_bytes", r"External KV Traffic Bytes:\s*(\d+)"),
    ("kv_writes_per_accepted_token", r"KV Writes Per Accepted Token:\s*([\d.]+)"),
    ("rollback_cycles",          r"Rollback Cycles:\s*(\d+)"),
    ("rollback_events",          r"Rollback Events:\s*(\d+)"),
    ("version_table_lookups",    r"Version Table Lookups:\s*(\d+)"),
    ("free_list_reuses",         r"Free List Reuses:\s*(\d+)"),
    ("metadata_updates",         r"Metadata Updates:\s*(\d+)"),
    ("metadata_updates_per_round", r"Metadata Updates Per Round:\s*([\d.]+)"),
    ("edc_prediction_accuracy",  r"Total Predictions:\s*\d+,\s*Accuracy:\s*([\d.]+)%"),
    ("edc_suppression_rate",     r"Total Drafts:\s*\d+,\s*Suppressed:\s*\d+\s*\(([\d.]+)%\)"),
    ("tvc_preverifications_inserted", r"Total Decisions:\s*\d+,\s*Pre-verifications Inserted:\s*(\d+)"),
    ("tvc_success_rate",         r"Successful Pre-verifications:\s*\d+\s*\(([\d.]+)%\)"),
    ("tvc_prevented_npu_idles",  r"Prevented NPU Idles:\s*(\d+)"),
    ("pim_command_candidate_slots", r"\[PIMCmd\] candidate slots:\s*(\d+)"),
    ("pim_command_issued",       r"\[PIMCmd\] candidate slots:\s*\d+\s*;\s*issued commands:\s*(\d+)"),
    ("pim_command_issue_pct",    r"\[PIMCmd\] candidate slots:\s*\d+\s*;\s*issued commands:\s*\d+\s*;\s*issue rate:\s*([\d.]+)%"),
    ("tlm_read_attempts",        r"\[PIMCmd\] TLM read attempts:\s*(\d+)"),
    ("tlm_read_blocked",         r"\[PIMCmd\] TLM read attempts:\s*\d+\s*;\s*blocked:\s*(\d+)"),
    ("tlm_read_blocking_pct",    r"\[PIMCmd\] TLM read attempts:\s*\d+\s*;\s*blocked:\s*\d+\s*;\s*blocking rate:\s*([\d.]+)%"),
    ("tlm_read_active_attempts", r"\[PIMCmd\] TLM read active-window attempts:\s*(\d+)"),
    ("tlm_read_active_blocked",  r"\[PIMCmd\] TLM read active-window attempts:\s*\d+\s*;\s*blocked:\s*(\d+)"),
    ("tlm_read_active_blocking_pct", r"\[PIMCmd\] TLM read active-window attempts:\s*\d+\s*;\s*blocked:\s*\d+\s*;\s*blocking rate:\s*([\d.]+)%"),
    ("tlm_read_inactive_attempts", r"\[PIMCmd\] TLM read inactive-window attempts:\s*(\d+)"),
    ("tlm_read_inactive_blocked", r"\[PIMCmd\] TLM read inactive-window attempts:\s*\d+\s*;\s*blocked:\s*(\d+)"),
    ("tlm_read_inactive_blocking_pct", r"\[PIMCmd\] TLM read inactive-window attempts:\s*\d+\s*;\s*blocked:\s*\d+\s*;\s*blocking rate:\s*([\d.]+)%"),
]


def parse_log(text: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for key, pat in REGEXES:
        m = re.search(pat, text)
        if not m:
            continue
        val = m.group(1)
        try:
            out[key] = float(val)
        except ValueError:
            out[key] = val  # type: ignore[assignment]
    m = re.search(r"Total Accepted Tokens:\s*(\d+)\s*\(([\d.]+)%", text)
    if m:
        out["accepted_tokens"] = float(m.group(1))
        out["accepted_pct"] = float(m.group(2))
    return out


def resolve_overlay(baseline: str) -> Dict[str, Any]:
    """Load `<baseline>.json`, merge in the base it inherits from, and
    strip the documentation keys."""
    overlay_path = BASELINES_DIR / f"{baseline}.json"
    if not overlay_path.exists():
        raise SystemExit(f"[baseline] no overlay at {overlay_path}; available: "
                         f"{[p.stem for p in BASELINES_DIR.glob('*.json') if not p.stem.startswith('_')]}")
    overlay = json.loads(overlay_path.read_text())
    base_name = overlay.pop("_inherits", None)
    overlay.pop("_doc", None)
    if not base_name:
        raise SystemExit(f"[baseline] {overlay_path} is missing `_inherits`")
    base_path = BASELINES_DIR / base_name
    if not base_path.exists():
        raise SystemExit(f"[baseline] base {base_path} not found")
    merged = json.loads(base_path.read_text())
    merged.update(overlay)
    return merged


def parse_model_pair(s: str) -> tuple[str, str]:
    if ":" in s:
        a, b = s.split(":", 1)
        return a, b
    # Fallback: treat a single name as self-pair, useful for micro-smokes.
    return s, s


def write_models_list(draft: str, target: str, trace_file_name: str,
                       max_draft_length: int, out_path: Path) -> None:
    models = {
        "models": [
            {"name": draft, "role": "draft", "trace_file": trace_file_name,
             "scheduler": "spec",
             "scheduler_config": {"max_batch_size": 1, "check_mem_size": False,
                                   "default_draft_length": max_draft_length}},
            {"name": target, "role": "target", "trace_file": trace_file_name,
             "scheduler": "spec",
             "scheduler_config": {"max_batch_size": 1, "check_mem_size": False,
                                   "default_draft_length": max_draft_length}},
        ]
    }
    out_path.write_text(json.dumps(models, indent=2))


def run_simulator(onnxim: Path, cfg: Path, models_list: Path,
                   trace_file_name: str, log_path: Path, timeout_s: int) -> int:
    sim_bin = onnxim / "build/bin/Simulator"
    if not sim_bin.exists():
        raise SystemExit(f"[baseline] simulator binary missing at {sim_bin}; "
                         f"run `cmake --build .` under ONNXim/build first")
    env = os.environ.copy()
    env["ONNXIM_HOME"] = str(onnxim)
    cmd = [str(sim_bin), "--config", str(cfg),
           "--models_list", str(models_list),
           "--mode", "language", "--trace_file", trace_file_name]
    print(f"[baseline] $ {' '.join(cmd)}")
    with log_path.open("w") as f:
        return subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                              cwd=onnxim, env=env, timeout=timeout_s).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--baseline", required=True,
                    help="Overlay stem under configs/baselines/ (e.g. npu_only, ahasd_full)")
    ap.add_argument("--model-pair", required=True,
                    help="draft:target (e.g. opt-125m:opt-125m-t)")
    ap.add_argument("--workload-trace", required=True, type=Path,
                    help="Simulator workload CSV (time,prompt_length,target_length,cached_length)")
    ap.add_argument("--acceptance-csv", type=Path, default=None,
                    help="If set, activates trace_replay acceptance mode with this CSV")
    ap.add_argument("--accept-seed", type=int, default=2025)
    ap.add_argument("--max-draft-length", type=int, default=4)
    ap.add_argument("--onnxim", type=Path, default=REPO / "ONNXim")
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--timeout-s", type=int, default=600)
    # E1 — allow sensitivity sweeps to override individual SimulationConfig
    # keys without duplicating the whole overlay. Repeatable, last wins.
    # Values are parsed as JSON so ints/floats/bools/lists are preserved.
    ap.add_argument("--config-override", action="append", default=[],
                    metavar="KEY=JSON_VALUE",
                    help="Override a single SimulationConfig key after the "
                         "overlay merge, e.g. --config-override edc_h_max=8.0. "
                         "Repeatable; JSON-parsed.")
    args = ap.parse_args()

    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = resolve_overlay(args.baseline)
    cfg["max_draft_length"] = args.max_draft_length
    cfg["accept_rng_seed"] = args.accept_seed
    for spec in args.config_override:
        if "=" not in spec:
            raise SystemExit(f"[baseline] --config-override must be KEY=JSON_VALUE, got {spec!r}")
        key, _, raw = spec.partition("=")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        cfg[key] = value
    if args.acceptance_csv:
        cfg["accept_mode"] = "trace_replay"
        cfg["accept_trace_path"] = str(args.acceptance_csv.resolve())
    else:
        cfg["accept_mode"] = "parametric"
        cfg.pop("accept_trace_path", None)

    cfg_path = out_dir / "onnxim_config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2))

    draft, target = parse_model_pair(args.model_pair)

    # Deploy workload trace into ONNXim/traces/ under a stable name so
    # Simulator's ONNXIM_HOME-relative resolution can find it.
    traces_dir = args.onnxim.resolve() / "traces"
    traces_dir.mkdir(exist_ok=True)
    deployed_name = f"baseline_{args.baseline}_{draft}_{target}.csv"
    deployed_path = traces_dir / deployed_name
    shutil.copy(args.workload_trace, deployed_path)

    models_list = out_dir / "models_list.json"
    write_models_list(draft, target, deployed_name, args.max_draft_length, models_list)

    log_path = out_dir / "log.txt"
    timeout_hit = False
    try:
        rc = run_simulator(args.onnxim.resolve(), cfg_path, models_list,
                           deployed_name, log_path, args.timeout_s)
    except subprocess.TimeoutExpired:
        timeout_hit = True
        rc = 124
        with log_path.open("a") as log:
            log.write(f"\n[baseline] simulator timeout after {args.timeout_s}s\n")
    metrics = parse_log(log_path.read_text())
    metrics["__baseline"] = args.baseline
    metrics["__model_pair"] = f"{draft}:{target}"
    metrics["__workload_trace"] = str(args.workload_trace.resolve())
    metrics["__acceptance_csv"] = (str(args.acceptance_csv.resolve())
                                    if args.acceptance_csv else None)
    metrics["__returncode"] = rc
    metrics["__timeout_s"] = args.timeout_s if timeout_hit else None
    metrics["__timed_out"] = timeout_hit
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))

    if rc != 0:
        reason = "timeout" if timeout_hit else f"rc={rc}"
        print(f"[baseline] simulator {reason}; see {log_path}", file=sys.stderr)
        return rc
    print(f"[baseline] ok. cycles={metrics.get('sim_finished_cycles')} "
          f"energy={metrics.get('total_energy_mj')} mJ "
          f"accept_ratio={metrics.get('acceptance_ratio')} "
          f"log={log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
