#!/usr/bin/env python3
"""F2 / F3 — SSRC threshold sweep driver.

Re-uses `scripts/run_baseline.py` with `--config-override` to vary the
SSRC confidence threshold (and optionally EDC LLR-related knobs) across
a sweep, parses SSRC + AHASD counters out of each run's `log.txt`, and
writes the sweep summary to `workflow/runs/<out>/ssrc_sweep.{json,csv}`.

F2 — Challenge 3 quantification
    vary `ssrc_confidence_threshold` across 8 values (LLR state 0-7
    analog); capture materialized bytes and rejection rate for the
    two-axis plot in §5.6.

F3 — SSRC evaluation matrix (pilot)
    one model pair × 4 algorithms × 4 thresholds.  Production scale
    adds two more model pairs via `--model-pairs`.

Example:

    python3 scripts/run_ssrc_sweep.py \\
        --out workflow/runs/f2_llr_sweep_opt125m \\
        --model-pair opt-125m:opt-125m-t \\
        --workload-trace workloads/smoke_p4_g8_2req.csv \\
        --thresholds 2.0,3.0,4.0,5.0,6.0,7.0,8.0,9.0 \\
        --baselines ahasd_ssrc \\
        --max-draft-length 4

F3 pilot (4 algorithm points × 4 thresholds):

    python3 scripts/run_ssrc_sweep.py \\
        --out workflow/runs/f3_pilot_opt125m \\
        --model-pair opt-125m:opt-125m-t \\
        --workload-trace workloads/smoke_p4_g8_2req.csv \\
        --thresholds 4.0,5.0,6.0,7.0 \\
        --baselines ahasd_ssrc,ahasd_ssrc_aau,ahasd_ssrc_edc,ahasd_ssrc_full

The sweep is resume-able: cells whose `metrics.json` already contains a
non-zero `sim_finished_cycles` are skipped unless `--force` is passed.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# Pull SSRC-specific counters straight out of the log.txt.  These ride
# on top of the `run_baseline.py` REGEX wall so the sweep output
# contains everything a plotter needs without re-implementing the parse.
SSRC_REGEXES = [
    # [SSRC] enable=1 thr=5.000 ... decisions=21 deferred=7 refused=0 commit=2 discard=5 partial=0 | bypass_writes=1344 bytes=43008 | saved=1536 B replayed=256 B peak=896 B
    ("ssrc_decisions",    r"\[SSRC\].*?decisions=(\d+)"),
    ("ssrc_deferred",     r"\[SSRC\].*?deferred=(\d+)"),
    ("ssrc_refused",      r"\[SSRC\].*?refused=(\d+)"),
    ("ssrc_commit",       r"\[SSRC\].*?commit=(\d+)"),
    ("ssrc_discard",      r"\[SSRC\].*?discard=(\d+)"),
    ("ssrc_partial",      r"\[SSRC\].*?partial=(\d+)"),
    ("ssrc_bypass_writes",r"bypass_writes=(\d+)"),
    ("ssrc_bypass_bytes", r"bypass_writes=\d+ bytes=(\d+)"),
    ("ssrc_saved_bytes",  r"saved=(\d+) B"),
    ("ssrc_replayed_bytes",r"replayed=(\d+) B"),
    ("ssrc_peak_bytes",   r"peak=(\d+) B"),
    ("ssrc_tagged_writes_total", r"tagged_writes_total=(\d+)"),
    ("ssrc_tagged_pim_writes_seen", r"tagged_pim_writes_seen=(\d+)"),
    ("ssrc_rejected_not_active", r"rejected_not_active=(\d+)"),
]


def parse_ssrc(text: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for key, pat in SSRC_REGEXES:
        m = re.search(pat, text)
        if m:
            try:
                out[key] = float(m.group(1))
            except ValueError:
                pass
    return out


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--out", required=True, type=Path,
                    help="Output directory (parent for per-cell subdirs + summary files).")
    ap.add_argument("--model-pair", required=True,
                    help="draft:target (e.g. opt-125m:opt-125m-t)")
    ap.add_argument("--workload-trace", required=True, type=Path)
    ap.add_argument("--acceptance-csv", type=Path, default=None)
    ap.add_argument("--thresholds", required=True,
                    help="Comma-separated list of ssrc_confidence_threshold values, e.g. '2.0,3.0,4.0,5.0'")
    ap.add_argument("--baselines", default="ahasd_ssrc",
                    help="Comma-separated overlay names under configs/baselines/")
    ap.add_argument("--max-draft-length", type=int, default=4)
    ap.add_argument("--accept-seed", type=int, default=2025)
    ap.add_argument("--timeout-s", type=int, default=1200,
                    help="Per-cell simulator timeout (seconds)")
    ap.add_argument("--force", action="store_true",
                    help="Re-run cells whose metrics.json already exists.")
    ap.add_argument("--extra-override", action="append", default=[],
                    help="Additional --config-override KEY=JSON to pass to every cell. Repeatable.")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    thresholds = [float(v.strip()) for v in args.thresholds.split(",") if v.strip()]
    baselines = [b.strip() for b in args.baselines.split(",") if b.strip()]

    rows: List[Dict[str, Any]] = []
    for baseline in baselines:
        for thr in thresholds:
            cell_name = f"{baseline}__thr{thr:.1f}"
            cell_dir = out_dir / cell_name
            cell_dir.mkdir(parents=True, exist_ok=True)
            metrics_path = cell_dir / "metrics.json"
            log_path = cell_dir / "log.txt"

            if (not args.force) and metrics_path.exists():
                try:
                    cached = json.loads(metrics_path.read_text())
                    if cached.get("sim_finished_cycles"):
                        print(f"[sweep] cached {cell_name}, skipping")
                        rows.append(_row(cell_name, baseline, thr, cached,
                                         log_path))
                        continue
                except Exception:
                    pass

            cmd = [
                sys.executable, str(HERE / "run_baseline.py"),
                "--baseline", baseline,
                "--model-pair", args.model_pair,
                "--workload-trace", str(args.workload_trace),
                "--accept-seed", str(args.accept_seed),
                "--max-draft-length", str(args.max_draft_length),
                "--output-dir", str(cell_dir),
                "--timeout-s", str(args.timeout_s),
                "--config-override", f"ssrc_confidence_threshold={thr}",
            ]
            if args.acceptance_csv:
                cmd += ["--acceptance-csv", str(args.acceptance_csv)]
            for extra in args.extra_override:
                cmd += ["--config-override", extra]

            print(f"[sweep] $ {' '.join(cmd)}")
            rc = subprocess.run(cmd, cwd=REPO).returncode
            if rc != 0:
                print(f"[sweep] cell {cell_name} failed rc={rc}; see {log_path}",
                      file=sys.stderr)

            metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
            rows.append(_row(cell_name, baseline, thr, metrics, log_path))

    _dump(out_dir, rows)
    print(f"[sweep] {len(rows)} cells; summary at {out_dir / 'ssrc_sweep.csv'}")
    return 0


def _row(name: str, baseline: str, thr: float, metrics: Dict[str, Any],
         log_path: Path) -> Dict[str, Any]:
    ssrc_metrics: Dict[str, Any] = {}
    if log_path.exists():
        ssrc_metrics = parse_ssrc(log_path.read_text())
    row = {
        "cell": name,
        "baseline": baseline,
        "ssrc_confidence_threshold": thr,
        **{k: metrics.get(k) for k in (
            "sim_finished_cycles", "final_npu_cycle", "final_pim_cycle",
            "gtsu_stall_cycles", "total_energy_mj", "draft_rounds", "verifies",
            "pim_aau_fused_events", "gtsu_switches", "acceptance_ratio",
            "acceptance_samples", "accepted_tokens", "accepted_pct",
            "attention_class_requests",
        )},
        **ssrc_metrics,
    }
    return row


def _dump(out_dir: Path, rows: List[Dict[str, Any]]) -> None:
    (out_dir / "ssrc_sweep.json").write_text(json.dumps(rows, indent=2))
    if not rows:
        return
    all_keys = sorted({k for r in rows for k in r.keys()})
    with (out_dir / "ssrc_sweep.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=all_keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


if __name__ == "__main__":
    sys.exit(main())
