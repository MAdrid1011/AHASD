#!/usr/bin/env python3
"""
D1 — Section 5.2 progressive-ablation matrix runner.

Iterates over (model-pair × algorithm) cells, delegates each cell to
`run_baseline.py`, and consolidates the per-cell `metrics.json` into a
single `matrix.csv` + `matrix.json` under the output directory.

Example:

    scripts/run_matrix.py \\
        --model-pairs opt-125m:opt-125m-t \\
        --algorithms ahasd_none,ahasd_aau,ahasd_aau_edc,ahasd_full \\
        --workload-trace workloads/smoke_p4_g8_2req.csv \\
        --max-draft-length 4 \\
        --output-dir workflow/runs/d1_pilot

Writes:

    workflow/runs/d1_pilot/
      <pair>__<algo>/               # forwarded to run_baseline.py
        onnxim_config.json, models_list.json, log.txt, metrics.json
      matrix.csv                    # one row per cell
      matrix.json                   # same data, JSON flavor

The driver is intentionally dumb about timeouts / retries — if a cell
fails, we record its returncode and keep going. Re-runs of the script
pick up only cells missing `metrics.json`, so long-running sweeps can
resume without re-doing completed cells.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# D3/D4 — emit W3 utilization + W9 overlap breakdowns per cell as a
# free side-effect of running the matrix. Both parsers are pure log
# parsing and cheap to call.
try:
    from parse_utilization import parse_log as _parse_util_log  # type: ignore
    from parse_overlap import parse_log as _parse_overlap_log  # type: ignore
except ImportError:  # pragma: no cover — script-relative import
    sys.path.insert(0, str(HERE))
    from parse_utilization import parse_log as _parse_util_log  # type: ignore
    from parse_overlap import parse_log as _parse_overlap_log  # type: ignore


METRIC_COLUMNS = [
    "sim_finished_cycles",
    "final_npu_cycle",
    "final_pim_cycle",
    "gtsu_stall_cycles",
    "tvc_hold_cycles",
    "attention_class_requests",
    "pim_aau_fused_events",
    "gtsu_switches",
    "total_energy_mj",
    "draft_rounds",
    "verifies",
    "acceptance_ratio",
    "acceptance_samples",
    "accepted_tokens",
    "accepted_pct",
]


def cell_dir(root: Path, model_pair: str, algorithm: str) -> Path:
    safe_pair = model_pair.replace(":", "__").replace("/", "_")
    return root / f"{safe_pair}__{algorithm}"


def run_cell(args, model_pair: str, algorithm: str) -> Dict:
    out = cell_dir(args.output_dir, model_pair, algorithm)
    metrics_path = out / "metrics.json"
    if metrics_path.exists() and not args.force:
        print(f"[matrix] cache-hit  {model_pair} x {algorithm}  ({out})")
        return json.loads(metrics_path.read_text())
    out.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(HERE / "run_baseline.py"),
        "--baseline", algorithm,
        "--model-pair", model_pair,
        "--workload-trace", str(args.workload_trace),
        "--max-draft-length", str(args.max_draft_length),
        "--accept-seed", str(args.accept_seed),
        "--output-dir", str(out),
        "--timeout-s", str(args.cell_timeout_s),
    ]
    if args.acceptance_csv:
        cmd += ["--acceptance-csv", str(args.acceptance_csv)]
    print(f"[matrix] run  {model_pair} x {algorithm}  -> {out.name}")
    # Let run_baseline.py write its own log; we just capture final lines
    # here to flag failures.
    rc = subprocess.run(cmd).returncode
    if metrics_path.exists():
        m = json.loads(metrics_path.read_text())
    else:
        m = {"__error": f"run_baseline.py returned rc={rc} without metrics.json"}
    m["__cell_returncode"] = rc

    # D3 — emit W3 utilization breakdown from the cell's log.
    log_path = out / "log.txt"
    util_path = out / "utilization.json"
    if log_path.exists() and (args.force or not util_path.exists()):
        try:
            util = _parse_util_log(log_path)
            util_path.write_text(json.dumps(util, indent=2))
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[matrix] WARNING: utilization parse failed for "
                  f"{model_pair} x {algorithm}: {exc}", file=sys.stderr)

    # D4 — emit W9 overlap-interval timeline from the cell's log.
    overlap_path = out / "overlap_timeline.json"
    if log_path.exists() and (args.force or not overlap_path.exists()):
        try:
            overlap = _parse_overlap_log(log_path)
            overlap_path.write_text(json.dumps(overlap, indent=2))
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[matrix] WARNING: overlap parse failed for "
                  f"{model_pair} x {algorithm}: {exc}", file=sys.stderr)
    return m


def parse_list(arg: str) -> List[str]:
    return [s.strip() for s in arg.split(",") if s.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--model-pairs", required=True,
                    help="Comma-separated draft:target pairs, e.g. "
                         "'opt-1.3b:opt-6.7b,llama2-7b:llama2-13b'")
    ap.add_argument("--algorithms", required=True,
                    help="Comma-separated baseline overlay names")
    ap.add_argument("--workload-trace", required=True, type=Path)
    ap.add_argument("--max-draft-length", type=int, default=4)
    ap.add_argument("--accept-seed", type=int, default=2025)
    ap.add_argument("--acceptance-csv", type=Path, default=None)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--cell-timeout-s", type=int, default=7200,
                    help="Per-cell timeout (default 2h; D1 prod cells can run long)")
    ap.add_argument("--force", action="store_true",
                    help="Re-run cells even if metrics.json already exists")
    args = ap.parse_args()

    pairs = parse_list(args.model_pairs)
    algos = parse_list(args.algorithms)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict] = []
    failures = 0
    for pair in pairs:
        for algo in algos:
            m = run_cell(args, pair, algo)
            if m.get("__cell_returncode", -1) != 0 or "__error" in m:
                failures += 1
            row = {"model_pair": pair, "algorithm": algo}
            for c in METRIC_COLUMNS:
                row[c] = m.get(c)
            row["__cell_returncode"] = m.get("__cell_returncode")
            rows.append(row)

    csv_path = args.output_dir / "matrix.csv"
    json_path = args.output_dir / "matrix.json"
    fields = ["model_pair", "algorithm"] + METRIC_COLUMNS + ["__cell_returncode"]
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    json_path.write_text(json.dumps(rows, indent=2))

    # D3 — consolidated utilization matrix for W3 figure data.
    util_rows: List[Dict] = []
    for pair in pairs:
        for algo in algos:
            cell = cell_dir(args.output_dir, pair, algo)
            up = cell / "utilization.json"
            if not up.exists():
                continue
            u = json.loads(up.read_text())
            util_rows.append({
                "model_pair": pair, "algorithm": algo,
                "total_npu_cycles": u.get("total_npu_cycles"),
                "total_pim_cycles": u.get("total_pim_cycles"),
                **u.get("npu_util_pct", {}),
                "hbm_bw_weighted_avg_pct": u.get("hbm_bw_weighted_avg_pct"),
                "pim_gtsu_stall_cycles": u.get("pim", {}).get("gtsu_stall_cycles"),
                "pim_tvc_hold_cycles": u.get("pim", {}).get("tvc_hold_cycles"),
                "pim_aau_fused_events": u.get("pim", {}).get("aau_fused_events"),
                "pim_aau_fusion_saved_bytes": u.get("pim", {}).get("aau_fusion_saved_bytes"),
            })
    if util_rows:
        (args.output_dir / "utilization_matrix.json").write_text(
            json.dumps(util_rows, indent=2))

    # D4 — consolidated overlap summary matrix for W9 figure data.
    # Keep the payload light: only the summary buckets, not the full
    # per-window timeline (those already live alongside each cell).
    overlap_rows: List[Dict] = []
    for pair in pairs:
        for algo in algos:
            cell = cell_dir(args.output_dir, pair, algo)
            op = cell / "overlap_timeline.json"
            if not op.exists():
                continue
            o = json.loads(op.read_text())
            s = o.get("overlap_summary", {})
            overlap_rows.append({
                "model_pair": pair, "algorithm": algo,
                "window_count": o.get("window_count"),
                "core_print_interval_est": o.get("core_print_interval_est"),
                "classified_windows": s.get("classified_windows"),
                "compute_only_pct": s.get("compute_only_pct"),
                "memory_only_pct": s.get("memory_only_pct"),
                "overlap_pct": s.get("overlap_pct"),
                "idle_pct": s.get("idle_pct"),
                "total_hbm_reads": s.get("total_hbm_reads"),
                "total_hbm_writes": s.get("total_hbm_writes"),
                "peak_hbm_bw_pct": s.get("peak_hbm_bw_pct"),
            })
    if overlap_rows:
        (args.output_dir / "overlap_summary_matrix.json").write_text(
            json.dumps(overlap_rows, indent=2))

    print()
    print(f"[matrix] {len(rows)} cells written to {csv_path}")
    if failures:
        print(f"[matrix] WARNING: {failures} cells failed (see per-cell log.txt)",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
