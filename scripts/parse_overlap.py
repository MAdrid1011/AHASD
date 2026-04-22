#!/usr/bin/env python3
"""
D4 — W9 overlap-interval bandwidth utilization parser.

Ingests a Simulator log.txt (ONNXim + AHASD co-sim) and produces a
per-window time series pairing Core [0] NPU activity with HBM channel-0
bandwidth snapshots. The resulting JSON drives Fig W9, which visualises
that NPU-bus BW and PIM/HBM BW live in complementary time windows.

Design constraints (same discipline as D3 `parse_utilization.py`):

- Pure log parser. No simulator source changes, no new emitters.
- Windows are defined by the simulator's own `core_print_interval` (the
  "Total cycle: T" line on each Core [0] snapshot marks a window end).
- HBM snapshots are bucketed into the most recent window boundary
  encountered in line order. Not cycle-exact, but accurate to ±1 window
  given `core_print_interval = 8000` in current configs.
- ONNXim emits BW utilization only for `HBM2-CH_0`. The other channels
  have no periodic snapshot — this is documented as a figure footnote,
  not a parser bug (same scope as D3).

Output schema (per cell):

    {
      "source_log": "/abs/path/to/log.txt",
      "core_print_interval_est": 8000,
      "window_count": 643,
      "overlap_timeline": [
        {
          "sim_cycle_end": 8000,
          "matmul_active_pct": 0.60,
          "systolic_util_pct": 22.45,
          "vector_util_pct": 0.00,
          "hbm_bw_util_pct": 72,
          "hbm_reads": 6943,
          "hbm_writes": 0
        },
        ...
      ],
      "overlap_summary": {
        "compute_only_pct": ...,  // NPU matmul active, HBM quiet
        "memory_only_pct": ...,   // NPU idle, HBM busy
        "overlap_pct": ...,       // both busy
        "idle_pct": ...,          // both quiet
        "thresholds": {
          "npu_matmul_active_pct": 0.5,   // > this => NPU compute active
          "hbm_bw_util_pct": 30            // > this => memory subsystem busy
        },
        "total_hbm_reads": ...,
        "total_hbm_writes": ...,
        "peak_hbm_bw_pct": ...
      }
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent


# Core [0] snapshot comes as two consecutive info lines; the second one
# carries the simulator cycle boundary. Use it as the window closer.
RE_CORE0_ACTIVE = re.compile(
    r"Core \[0\] : MatMul active cycle (\d+) Vector active cycle (\d+)")
RE_CORE0_UTIL = re.compile(
    r"Core \[0\] : Systolic Array Utilization\(%\) ([\d.]+) "
    r"\(([\d.]+)% PE util\), Vector Unit Utilization\(%\) ([\d.]+), "
    r"Total cycle: (\d+)")
RE_HBM_CH0 = re.compile(
    r"HBM2-CH_0: BW utilization (\d+)% \((\d+) reads, (\d+) writes\)")


def parse_log(log_path: Path,
              npu_thresh_pct: float = 0.5,
              hbm_thresh_pct: float = 30.0) -> Dict:
    """Stream log.txt once, pair Core [0] snapshots with HBM CH_0 bands."""
    timeline: List[Dict] = []
    pending_core0: Optional[Dict] = None
    # Most recent window bucket so that HBM lines arriving between core
    # boundaries attach to the last-closed window (the one whose
    # `sim_cycle_end` immediately precedes them).
    last_window: Optional[Dict] = None

    with log_path.open() as f:
        for line in f:
            m = RE_CORE0_ACTIVE.search(line)
            if m:
                pending_core0 = {
                    "matmul_cycles": int(m.group(1)),
                    "vector_cycles": int(m.group(2)),
                }
                continue
            m = RE_CORE0_UTIL.search(line)
            if m and pending_core0 is not None:
                systolic_util = float(m.group(1))
                pe_util = float(m.group(2))  # == matmul_active_pct
                vec_util = float(m.group(3))
                sim_cycle_end = int(m.group(4))
                window = {
                    "sim_cycle_end": sim_cycle_end,
                    "matmul_active_pct": pe_util,
                    "systolic_util_pct": systolic_util,
                    "vector_util_pct": vec_util,
                    "matmul_cycles": pending_core0["matmul_cycles"],
                    "vector_cycles": pending_core0["vector_cycles"],
                    "hbm_bw_util_pct": None,
                    "hbm_reads": None,
                    "hbm_writes": None,
                }
                timeline.append(window)
                last_window = window
                pending_core0 = None
                continue
            m = RE_HBM_CH0.search(line)
            if m and last_window is not None:
                # HBM lines after the most recent window boundary belong
                # to that window. If a window already has HBM data (rare),
                # the later sample wins — matches the "last snapshot per
                # window" convention used in D3.
                last_window["hbm_bw_util_pct"] = int(m.group(1))
                last_window["hbm_reads"] = int(m.group(2))
                last_window["hbm_writes"] = int(m.group(3))
            elif m and last_window is None:
                # Edge case: HBM snapshot emitted before the first Core
                # [0] window closes. Ignore — aligns with the figure's
                # interval-based semantics.
                pass

    # Post-hoc classification. Windows missing HBM data contribute to the
    # "npu-only view" but not overlap statistics — we skip them in the
    # overlap buckets but keep them in the timeline so downstream plot
    # tooling still sees the NPU axis.
    buckets = {"compute_only": 0, "memory_only": 0,
               "overlap": 0, "idle": 0}
    classified = 0
    for w in timeline:
        if w["hbm_bw_util_pct"] is None:
            continue
        classified += 1
        npu_busy = w["matmul_active_pct"] > npu_thresh_pct
        mem_busy = w["hbm_bw_util_pct"] > hbm_thresh_pct
        if npu_busy and mem_busy:
            buckets["overlap"] += 1
        elif npu_busy and not mem_busy:
            buckets["compute_only"] += 1
        elif mem_busy and not npu_busy:
            buckets["memory_only"] += 1
        else:
            buckets["idle"] += 1

    def pct(n: int) -> float:
        return round(100.0 * n / classified, 2) if classified else 0.0

    # Core-print interval estimation from the first two window boundaries.
    interval_est: Optional[int] = None
    if len(timeline) >= 2:
        interval_est = timeline[1]["sim_cycle_end"] - timeline[0]["sim_cycle_end"]

    total_reads = sum(w["hbm_reads"] or 0 for w in timeline)
    total_writes = sum(w["hbm_writes"] or 0 for w in timeline)
    peak_bw = max((w["hbm_bw_util_pct"] or 0 for w in timeline), default=0)

    return {
        "source_log": str(log_path.resolve()),
        "core_print_interval_est": interval_est,
        "window_count": len(timeline),
        "overlap_timeline": timeline,
        "overlap_summary": {
            "compute_only_pct": pct(buckets["compute_only"]),
            "memory_only_pct": pct(buckets["memory_only"]),
            "overlap_pct": pct(buckets["overlap"]),
            "idle_pct": pct(buckets["idle"]),
            "thresholds": {
                "npu_matmul_active_pct": npu_thresh_pct,
                "hbm_bw_util_pct": hbm_thresh_pct,
            },
            "classified_windows": classified,
            "total_hbm_reads": total_reads,
            "total_hbm_writes": total_writes,
            "peak_hbm_bw_pct": peak_bw,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--log", type=Path, required=True,
                    help="Path to Simulator log.txt")
    ap.add_argument("--out", type=Path, default=None,
                    help="Where to write overlap_timeline.json "
                         "(default: alongside log.txt)")
    ap.add_argument("--npu-thresh-pct", type=float, default=0.5,
                    help="Matmul active %% above which NPU is 'busy' "
                         "(default: 0.5)")
    ap.add_argument("--hbm-thresh-pct", type=float, default=30.0,
                    help="HBM BW util %% above which memory subsystem "
                         "is 'busy' (default: 30.0)")
    args = ap.parse_args()

    if not args.log.exists():
        print(f"[parse_overlap] log not found: {args.log}", file=sys.stderr)
        return 2
    out = parse_log(args.log, args.npu_thresh_pct, args.hbm_thresh_pct)
    dest = args.out or args.log.parent / "overlap_timeline.json"
    dest.write_text(json.dumps(out, indent=2))

    s = out["overlap_summary"]
    print(f"[parse_overlap] {args.log}")
    print(f"  windows={out['window_count']}  "
          f"interval~{out['core_print_interval_est']} cycles  "
          f"classified={s['classified_windows']}")
    print(f"  compute_only={s['compute_only_pct']}%  "
          f"memory_only={s['memory_only_pct']}%  "
          f"overlap={s['overlap_pct']}%  idle={s['idle_pct']}%")
    print(f"  HBM total reads={s['total_hbm_reads']}  "
          f"writes={s['total_hbm_writes']}  "
          f"peak={s['peak_hbm_bw_pct']}%")
    print(f"  -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
