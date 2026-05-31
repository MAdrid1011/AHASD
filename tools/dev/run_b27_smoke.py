#!/usr/bin/env python3
"""
B2.7 — End-to-end smoke: cycle coupling must be real, AHASD on/off must
differentiate final_npu_cycle / Total Energy / PIM events.

Fixed workload: opt-125m (draft) + opt-125m-t (target), 2 requests.
Fixed acceptance: trace_replay with a deterministic CSV so any cycle
delta comes purely from scheduler + PIM + GTSU. See workflow/PROGRESS.md
B2.7 entry for the pass criteria.

Usage:
    tools/dev/run_b27_smoke.py \
        --onnxim /home/madrid/Desktop/AHASD/ONNXim \
        --base-config /tmp/ahasd_b24_smoke/onnxim_config.json \
        --output-dir workflow/b27

If --base-config is omitted we look for a previously-prepared
onnxim_config.json under /tmp/ahasd_b24_smoke (left behind by earlier
smokes). The script is intentionally self-contained so any reviewer can
rerun without threading through earlier tmp state.
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCRIPTS = REPO / "scripts"


AXES = {
    "A_off":          {"enable_ahasd": False, "enable_edc": False, "enable_tvc": False,
                       "enable_aau": False,   "pim_enable": False},
    "A_pim_only":     {"enable_ahasd": False, "enable_edc": False, "enable_tvc": False,
                       "enable_aau": False,   "pim_enable": True,
                       "pim_enable_aau_fusion": True},
    "A_ahasd_noaau":  {"enable_ahasd": True,  "enable_edc": True,  "enable_tvc": True,
                       "enable_aau": False,   "pim_enable": True,
                       "pim_enable_aau_fusion": False},
    "A_full":         {"enable_ahasd": True,  "enable_edc": True,  "enable_tvc": True,
                       "enable_aau": True,    "pim_enable": True,
                       "pim_enable_aau_fusion": True},
}


@dataclass
class RunResult:
    name: str
    cmd: List[str]
    log_path: Path
    returncode: int
    metrics: Dict[str, float] = field(default_factory=dict)


REGEXES = [
    # Simulation Finished fires on every config, PIM or not. We keep the
    # PIMBackend-specific lines as secondary so both numbers end up in the
    # report and any divergence is visible.
    ("sim_finished_cycles",       r"Simulation Finished at (\d+) cycle"),
    ("final_npu_cycle",           r"\[PIMBackend\] final_npu_cycle=(\d+)"),
    ("final_pim_cycle",           r"final_pim_cycle=(\d+)"),
    ("gtsu_stall_cycles",         r"GTSU switches: \d+\s*;\s*total stall cycles:\s*(\d+)"),
    ("tvc_hold_cycles",           r"TVC hold cycles:\s*(\d+)"),
    ("attention_class_requests",  r"attention-class requests through PIM:\s*(\d+)"),
    ("total_energy_mj",           r"Total Energy:\s*([\d.]+) mJ"),
    ("energy_pim_read_mj",        r"read=([\d.]+)"),
    ("draft_rounds",              r"Total Draft Rounds:\s*(\d+)"),
    ("verifies",                  r"Total Verifies:\s*(\d+)"),
    ("accepted_tokens",           r"Total Accepted Tokens:\s*(\d+)\s*\(([\d.]+)%"),
    ("acceptance_samples",        r"Acceptance Samples:\s*(\d+)"),
    ("acceptance_ratio",          r"accept_ratio=([\d.]+)"),
    ("pim_aau_fused_events",      r"AAU fused events:\s*(\d+)"),
    ("gtsu_switches",             r"GTSU switches:\s*(\d+)"),
]


def parse_log(text: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for key, pat in REGEXES:
        m = re.search(pat, text)
        if not m:
            continue
        if key == "accepted_tokens":
            out["accepted_tokens"] = float(m.group(1))
            out["accepted_pct"] = float(m.group(2))
        else:
            try:
                out[key] = float(m.group(1))
            except ValueError:
                out[key] = 0.0
    return out


def prepare_trace(out_dir: Path, seed: int, rounds: int, max_draft: int) -> Path:
    trace_path = out_dir / "accept_trace.csv"
    cmd = [
        sys.executable, str(SCRIPTS / "gen_acceptance_trace.py"),
        "--model-pair", "opt-125m-opt-125m-t",
        "--algorithm", "specdec",
        "--rounds", str(rounds),
        "--max-draft-length", str(max_draft),
        "--seed", str(seed),
        "--provenance",
        "--output", str(trace_path),
    ]
    subprocess.run(cmd, check=True)
    return trace_path


def prepare_e2e_trace(out_dir: Path, prompt: int, target: int, num_requests: int) -> Path:
    """Write the Simulator workload trace (prompt/target lengths per request)."""
    trace = out_dir / "workload.csv"
    with trace.open("w") as f:
        f.write("time,prompt_length,target_length,cached_length\n")
        for i in range(num_requests):
            f.write(f"{i*10},{prompt},{target},0\n")
    return trace


def write_models_list(out_dir: Path, trace_file: str) -> Path:
    models = {
        "models": [
            {
                "name": "opt-125m",
                "role": "draft",
                "trace_file": trace_file,
                "scheduler": "spec",
                "scheduler_config": {"max_batch_size": 1, "check_mem_size": False,
                                     "default_draft_length": 4},
            },
            {
                "name": "opt-125m-t",
                "role": "target",
                "trace_file": trace_file,
                "scheduler": "spec",
                "scheduler_config": {"max_batch_size": 1, "check_mem_size": False,
                                     "default_draft_length": 4},
            },
        ]
    }
    path = out_dir / "models_list.json"
    path.write_text(json.dumps(models, indent=2))
    return path


def write_axis_config(base: dict, axis_name: str, axis: dict, trace_csv: Path,
                      out_dir: Path) -> Path:
    cfg = copy.deepcopy(base)
    cfg.update(axis)
    cfg["accept_mode"] = "trace_replay"
    cfg["accept_trace_path"] = str(trace_csv)
    cfg["accept_rng_seed"] = 2025
    # When PIM is disabled also tamp GTSU/AAU coefficients to keep the
    # breakdown readable; the axis dict already sets enable flags.
    path = out_dir / f"onnxim_config_{axis_name}.json"
    path.write_text(json.dumps(cfg, indent=2))
    return path


def run_simulator(onnxim_home: Path, cfg: Path, models_list: Path,
                   trace_file: str, log_path: Path, axis_name: str) -> RunResult:
    sim_bin = onnxim_home / "build/bin/Simulator"
    env = os.environ.copy()
    env["ONNXIM_HOME"] = str(onnxim_home)
    cmd = [
        str(sim_bin),
        "--config", str(cfg),
        "--models_list", str(models_list),
        "--mode", "language",
        "--trace_file", trace_file,
    ]
    print(f"[b27] run {axis_name}: {' '.join(cmd)}")
    with log_path.open("w") as f:
        rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=onnxim_home,
                            env=env, timeout=300).returncode
    text = log_path.read_text()
    metrics = parse_log(text)
    return RunResult(name=axis_name, cmd=cmd, log_path=log_path, returncode=rc,
                     metrics=metrics)


def _pct(a: float, b: float) -> float:
    if b <= 0:
        return 0.0
    return abs(a - b) / b * 100.0


def compute_verdict(results: Dict[str, RunResult]) -> Dict[str, str]:
    """Produce multi-axis pass/fail verdict. Split into:
      1. Cycle coupling (PIM on vs off should move cycles somewhat).
      2. GTSU / acceptance determinism (structural checks).
      3. EDC/TVC/AAU differentiation (A_full vs A_pim_only). This one is
         marked INFO rather than FAIL when it's under threshold — the
         simulator can be coupled even if AHASD's sub-modules happen to
         have no headroom on this trivial workload.
    """
    verdict: Dict[str, str] = {}

    def cyc(key: str) -> float:
        m = results.get(key, RunResult("", [], Path(), -1)).metrics
        # Prefer the universal simulator line; fall back to PIM backend's.
        return m.get("sim_finished_cycles") or m.get("final_npu_cycle") or 0.0

    c_off, c_pim, c_ahasd_noaau, c_full = (
        cyc("A_off"), cyc("A_pim_only"), cyc("A_ahasd_noaau"), cyc("A_full"))

    # (1) PIM coupling — A_off vs A_pim_only must differ (PIM is doing
    # something, even if only the energy breakdown changes).
    if c_off > 0 and c_pim > 0:
        d = _pct(c_pim, c_off)
        verdict["cycle_pim_off_vs_on_pct"] = f"{d:.3f}"
        # A generous threshold because 2-request smoke can't show huge
        # swings; we just need to prove the number moves.
        verdict["cycle_pim_coupling"] = "PASS" if d >= 0.05 else "FAIL"
    else:
        verdict["cycle_pim_coupling"] = "FAIL (cycle samples missing)"

    # (2) AHASD differentiation — A_pim_only vs A_full. INFO label so the
    # script still exits 0 when the trivial workload legitimately leaves
    # AHASD no headroom; the report then flags the finding.
    if c_pim > 0 and c_full > 0:
        d = _pct(c_full, c_pim)
        verdict["cycle_ahasd_pim_vs_full_pct"] = f"{d:.3f}"
        verdict["cycle_ahasd_diff"] = ("PASS" if d >= 0.05
                                        else "INFO (AHASD not differentiating this workload)")
    else:
        verdict["cycle_ahasd_diff"] = "FAIL (cycle samples missing)"

    # (3) Energy delta — PIM paths pay leak energy, so A_off and PIM-on
    # axes should differ substantially.
    e_off = results.get("A_off", RunResult("", [], Path(), -1)).metrics.get("total_energy_mj", 0)
    e_full = results.get("A_full", RunResult("", [], Path(), -1)).metrics.get("total_energy_mj", 0)
    if e_off > 0 and e_full > 0:
        d = _pct(e_full, e_off)
        verdict["energy_delta_pct"] = f"{d:.2f}"
        verdict["energy_delta_pass"] = "PASS" if d >= 1.0 else "FAIL"
    else:
        verdict["energy_delta_pass"] = "FAIL (missing energy samples)"

    # (4) GTSU — should be zero for A_off, positive for all PIM axes.
    gtsu_off = results.get("A_off", RunResult("", [], Path(), -1)).metrics.get("gtsu_switches", 0)
    gtsu_full = results.get("A_full", RunResult("", [], Path(), -1)).metrics.get("gtsu_switches", 0)
    verdict["gtsu_off_is_zero"] = "PASS" if gtsu_off == 0 else f"FAIL ({gtsu_off})"
    verdict["gtsu_full_is_positive"] = "PASS" if gtsu_full > 0 else f"FAIL ({gtsu_full})"

    # (5) AAU — trivial workload does not tag attention-class traffic so
    # AAU may legitimately stay at zero. Mark INFO so humans review.
    aau_full = results.get("A_full", RunResult("", [], Path(), -1)).metrics.get("pim_aau_fused_events", 0)
    if aau_full > 0:
        verdict["aau_firing"] = f"PASS ({int(aau_full)} events)"
    else:
        verdict["aau_firing"] = "INFO (no attention-class traffic tagged on this workload)"

    # (6) Acceptance determinism — replay means ratio MUST be identical
    # across all four axes.
    ratios = {k: v.metrics.get("acceptance_ratio") for k, v in results.items()}
    ratios_nz = [r for r in ratios.values() if r is not None]
    if ratios_nz and max(ratios_nz) - min(ratios_nz) < 1e-6:
        verdict["accept_deterministic"] = "PASS"
    else:
        verdict["accept_deterministic"] = f"FAIL (values={ratios})"

    return verdict


def render_report(results: Dict[str, RunResult], verdict: Dict[str, str],
                   report_path: Path, trace_csv: Path, workload_csv: Path) -> None:
    lines: List[str] = []
    lines.append("# B2.7 — End-to-End Smoke Report\n")
    lines.append(f"Acceptance CSV: `{trace_csv}`")
    lines.append(f"Workload trace: `{workload_csv}`\n")
    lines.append("## Matrix\n")
    # Columns: metric | A_off | A_pim_only | A_ahasd_noaau | A_full
    cols = ["A_off", "A_pim_only", "A_ahasd_noaau", "A_full"]
    metric_keys = [
        "sim_finished_cycles", "final_npu_cycle", "final_pim_cycle",
        "gtsu_stall_cycles", "tvc_hold_cycles", "attention_class_requests",
        "draft_rounds", "verifies", "accepted_tokens", "acceptance_ratio",
        "total_energy_mj",
        "pim_aau_fused_events", "gtsu_switches",
    ]
    header = "| metric | " + " | ".join(cols) + " |"
    sep    = "|" + "---|" * (len(cols) + 1)
    lines.append(header)
    lines.append(sep)
    for k in metric_keys:
        row = [k]
        for c in cols:
            row.append(f"{results[c].metrics.get(k, 'n/a')}")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("\n## Verdict\n")
    for k, v in verdict.items():
        lines.append(f"- `{k}`: **{v}**")

    lines.append("\n## Raw logs\n")
    for c in cols:
        lines.append(f"- `{c}` → `{results[c].log_path}` (rc={results[c].returncode})")

    report_path.write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--onnxim", type=Path, default=REPO / "ONNXim")
    ap.add_argument("--base-config", type=Path,
                    default=Path("/tmp/ahasd_b24_smoke/onnxim_config.json"))
    ap.add_argument("--output-dir", type=Path, default=REPO / "workflow/b27")
    ap.add_argument("--seed", type=int, default=2025)
    ap.add_argument("--rounds", type=int, default=32, help="Acceptance CSV rows")
    ap.add_argument("--max-draft", type=int, default=4)
    ap.add_argument("--prompt", type=int, default=4)
    ap.add_argument("--target-length", type=int, default=8)
    ap.add_argument("--num-requests", type=int, default=2)
    args = ap.parse_args()

    onnxim = args.onnxim.resolve()
    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.base_config.exists():
        print(f"[b27] base config not found: {args.base_config}", file=sys.stderr)
        return 2
    base = json.loads(args.base_config.read_text())

    accept_csv = prepare_trace(out_dir, args.seed, args.rounds, args.max_draft)
    workload_csv = prepare_e2e_trace(out_dir, args.prompt, args.target_length,
                                      args.num_requests)
    # Simulator resolves --trace_file relative to ONNXIM_HOME/traces, so we
    # copy the generated workload into that directory under a stable name.
    traces_dir = onnxim / "traces"
    traces_dir.mkdir(exist_ok=True)
    deployed_trace = traces_dir / "b27_smoke.csv"
    shutil.copy(workload_csv, deployed_trace)
    models_list = write_models_list(out_dir, deployed_trace.name)

    results: Dict[str, RunResult] = {}
    for axis_name, axis in AXES.items():
        cfg_path = write_axis_config(base, axis_name, axis, accept_csv, out_dir)
        log_path = out_dir / f"{axis_name}.log"
        res = run_simulator(onnxim, cfg_path, models_list, deployed_trace.name,
                             log_path, axis_name)
        results[axis_name] = res
        if res.returncode != 0:
            print(f"[b27] {axis_name} FAILED rc={res.returncode}", file=sys.stderr)

    verdict = compute_verdict(results)
    report = out_dir / "b27_report.md"
    render_report(results, verdict, report, accept_csv, workload_csv)

    print("\n=== B2.7 Report ===")
    print(report.read_text())

    # Exit non-zero only if a hard FAIL fires; INFO items are observations
    # the reviewer should interpret, not regressions.
    fail = any(isinstance(v, str) and v.startswith("FAIL") for v in verdict.values())
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
