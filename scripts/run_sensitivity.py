#!/usr/bin/env python3
"""
E1 — W2 sensitivity-sweep driver.

Runs four axes of hyperparameter sweeps over the `ahasd_full` baseline
on a single model pair and workload, collecting throughput, acceptance
ratio, and NPU memory-idle % per cell.

Axes (match `workflow/AHASDFix.md` W2 plan):

  EDC — H_max            {10.0, 8.0, 7.0, 6.0}   (max / P95 / P90 / mean+2σ)
  EDC — LEHT history     {4, 8, 12, 16}
  EDC — LLR bit width    {2, 3, 4}
  TVC — cycle table size {1, 2, 4, 8}

Each cell is a single invocation of `run_baseline.py --baseline ahasd_full
--config-override <axis>=<value>`. The driver parses the resulting
`metrics.json` plus `utilization.json` (produced by D3's parser if the
run_matrix hook is in use; recomputed here if missing) and consolidates
into `sensitivity_results.json`:

    {
      "model_pair": "opt-125m:opt-125m-t",
      "workload": "/abs/path/to/workloads/smoke_p4_g8_2req.csv",
      "cells": [
        {
          "axis": "edc_h_max", "value": 10.0,
          "sim_finished_cycles": 5141793,
          "tokens_completed": ...,           # from acceptance_samples × accept_pct
          "throughput_tokens_per_mcycle": ...,
          "acceptance_ratio": 0.2353,
          "npu_memory_idle_pct": 75.17,
          "total_energy_mj": 149.81
        },
        ...
      ]
    }

Designed to be re-runnable: existing cells with valid `metrics.json`
short-circuit via `run_baseline.py`'s own caching path.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# Ensure D3 parser is importable so we can compute utilization.json if
# the cell didn't go through run_matrix.
sys.path.insert(0, str(HERE))
from parse_utilization import parse_log as _parse_util_log  # type: ignore


# Default axes (match W2 plan).
DEFAULT_AXES: Dict[str, List] = {
    "edc_h_max":            [10.0, 8.0, 7.0, 6.0],
    "edc_leht_size":        [4, 8, 12, 16],
    "edc_llr_bits":         [2, 3, 4],
    "tvc_cycle_table_size": [1, 2, 4, 8],
}


def cell_dir(root: Path, axis: str, value) -> Path:
    # JSON-safe, filesystem-safe suffix.
    safe = str(value).replace(".", "p").replace("-", "neg")
    return root / f"{axis}__{safe}"


def run_cell(args, axis: str, value) -> Dict:
    out = cell_dir(args.output_dir, axis, value)
    metrics_path = out / "metrics.json"
    if metrics_path.exists() and not args.force:
        print(f"[sensitivity] cache-hit  {axis}={value}  ({out})")
        m = json.loads(metrics_path.read_text())
    else:
        out.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable, str(HERE / "run_baseline.py"),
            "--baseline", "ahasd_full",
            "--model-pair", args.model_pair,
            "--workload-trace", str(args.workload_trace),
            "--max-draft-length", str(args.max_draft_length),
            "--accept-seed", str(args.accept_seed),
            "--output-dir", str(out),
            "--timeout-s", str(args.cell_timeout_s),
            "--config-override", f"{axis}={json.dumps(value)}",
        ]
        print(f"[sensitivity] run  {axis}={value}  -> {out.name}")
        rc = subprocess.run(cmd).returncode
        if metrics_path.exists():
            m = json.loads(metrics_path.read_text())
        else:
            m = {"__error": f"run_baseline rc={rc} no metrics.json"}
        m["__cell_returncode"] = rc

    log_path = out / "log.txt"
    util_path = out / "utilization.json"
    util: Dict = {}
    if log_path.exists() and (args.force or not util_path.exists()):
        try:
            util = _parse_util_log(log_path)
            util_path.write_text(json.dumps(util, indent=2))
        except Exception as exc:  # pragma: no cover
            print(f"[sensitivity] WARN utilization parse failed for "
                  f"{axis}={value}: {exc}", file=sys.stderr)
    elif util_path.exists():
        util = json.loads(util_path.read_text())

    cycles = m.get("sim_finished_cycles")
    accept = m.get("acceptance_ratio")
    samples = m.get("acceptance_samples") or 0
    # Throughput proxy: "accepted tokens per million simulator cycles".
    # Matches the shape of Fig W2's Y-axis (relative throughput) without
    # baking in any particular clock rate.
    throughput = None
    accepted_tokens = None
    if cycles and samples:
        accepted_tokens = samples * (accept or 0.0)
        throughput = round(accepted_tokens / (cycles / 1.0e6), 3)

    mem_idle = None
    if util:
        mem_idle = util.get("npu_util_pct", {}).get("memory_unit_idle_pct")

    return {
        "axis": axis, "value": value,
        "sim_finished_cycles": cycles,
        "acceptance_ratio": accept,
        "acceptance_samples": samples,
        "accepted_tokens": accepted_tokens,
        "throughput_tokens_per_mcycle": throughput,
        "npu_memory_idle_pct": mem_idle,
        "total_energy_mj": m.get("total_energy_mj"),
        "pim_gtsu_stall_cycles": (util.get("pim") or {}).get("gtsu_stall_cycles") if util else None,
        "cell_returncode": m.get("__cell_returncode"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--model-pair", default="opt-125m:opt-125m-t")
    ap.add_argument("--workload-trace", type=Path, required=True)
    ap.add_argument("--max-draft-length", type=int, default=4)
    ap.add_argument("--accept-seed", type=int, default=2025)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--cell-timeout-s", type=int, default=600)
    ap.add_argument("--force", action="store_true",
                    help="Re-run cells even if metrics.json already exists")
    ap.add_argument("--axes", default=",".join(DEFAULT_AXES.keys()),
                    help=f"Comma-separated subset; default all four: "
                         f"{list(DEFAULT_AXES.keys())}")
    args = ap.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected = [a.strip() for a in args.axes.split(",") if a.strip()]
    for a in selected:
        if a not in DEFAULT_AXES:
            print(f"[sensitivity] unknown axis {a!r}; valid: {list(DEFAULT_AXES)}",
                  file=sys.stderr)
            return 2

    cells: List[Dict] = []
    for axis in selected:
        for value in DEFAULT_AXES[axis]:
            cell = run_cell(args, axis, value)
            cells.append(cell)

    results = {
        "model_pair": args.model_pair,
        "workload": str(args.workload_trace.resolve()),
        "max_draft_length": args.max_draft_length,
        "axes": {a: DEFAULT_AXES[a] for a in selected},
        "cells": cells,
    }
    (args.output_dir / "sensitivity_results.json").write_text(
        json.dumps(results, indent=2))

    print()
    print(f"[sensitivity] {len(cells)} cells -> "
          f"{args.output_dir / 'sensitivity_results.json'}")
    # Pretty summary table.
    print()
    print(f"{'axis':<24} {'value':>8} {'cycles':>12} {'accept':>8} "
          f"{'tok/Mc':>8} {'mem_idle%':>10} {'energy':>8}")
    for c in cells:
        print(f"{c['axis']:<24} {str(c['value']):>8} "
              f"{c['sim_finished_cycles'] or '-':>12} "
              f"{c['acceptance_ratio'] or '-':>8} "
              f"{c['throughput_tokens_per_mcycle'] or '-':>8} "
              f"{c['npu_memory_idle_pct'] or '-':>10} "
              f"{c['total_energy_mj'] or '-':>8}")
    bad = sum(1 for c in cells if c.get("cell_returncode", 0) != 0 and c.get("cell_returncode") is not None)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
