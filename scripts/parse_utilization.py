#!/usr/bin/env python3
"""
D3 — W3 NPU/PIM utilization decomposition parser.

Ingests a Simulator log.txt (ONNXim + AHASD co-sim output) and
produces a `utilization.json` breaking its wall-cycle budget into
figure-ready components.

The simulator emits periodic "core_print_interval"-driven snapshots
per NPU core, plus per-HBM-channel BW lines, plus the end-of-run
`[PIMBackend]` summary. We sum the per-snapshot active / idle cycles
across all cores (because each core's snapshot line is a cumulative
counter, we take the *last* snapshot per core), then combine with
PIM's final cycle + GTSU stall / TVC hold counts to produce a W3-
compatible breakdown.

Outputs (one cell):

    {
      "total_npu_cycles": 5141793,
      "total_pim_cycles": 4118234,
      "cores": [
        {"core_id": 0, "matmul_active": ..., "vector_active": ...,
         "systolic_bubble": ..., "memory_unit_idle": ...,
         "core_idle": ..., "total_cycle": ...},
        ...
      ],
      "npu_summed": {                  # sum across cores
        "matmul_active": ..., "vector_active": ...,
        "systolic_bubble": ..., "memory_unit_idle": ...,
        "core_idle": ..., "total_cycle": ...
      },
      "npu_util_pct": {                # % of each core's last total_cycle
        "matmul_active_pct": ..., "core_idle_pct": ..., ...
      },
      "pim": {
        "final_pim_cycle": ...,
        "gtsu_stall_cycles": ..., "gtsu_switches": ...,
        "tvc_hold_cycles": ...,
        "attention_class_requests": ...,
        "aau_fused_events": ...,
        "aau_fusion_saved_bytes": ...
      },
      "hbm_bw": [                      # one per channel, last snapshot
        {"channel": 0, "bw_util_pct": 55, "reads": 5331, "writes": 16},
        ...
      ],
      "hbm_bw_weighted_avg_pct": ...,
      "source_log": "/abs/path/to/log.txt"
    }

No simulator code changes. If `core_print_interval` is too coarse the
snapshots may miss the final tail, but the `[PIMBackend] final_*`
summary is always emitted so the aggregate stays correct.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# Per-core snapshot trio (three consecutive log lines).
RE_CORE_MATMUL = re.compile(
    r"Core \[(\d+)\] : MatMul active cycle (\d+) Vector active cycle (\d+)")
RE_CORE_MEM = re.compile(
    r"Core \[(\d+)\] : Memory unit idle cycle (\d+) Systolic bubble cycle (\d+) Core idle cycle (\d+)")
RE_CORE_TOTAL = re.compile(
    r"Core \[(\d+)\] : Systolic Array Utilization\(%\) [\d.]+ .* Vector Unit Utilization\(%\) [\d.]+, Total cycle: (\d+)")

RE_HBM_BW = re.compile(r"HBM2-CH_(\d+): BW utilization (\d+)% \((\d+) reads, (\d+) writes\)")

RE_PIM_FINAL = re.compile(r"\[PIMBackend\] final_npu_cycle=(\d+) final_pim_cycle=(\d+)")
RE_SIM_FINISHED = re.compile(r"Simulation Finished at (\d+) cycle")
RE_GTSU = re.compile(r"GTSU switches: (\d+)\s*;\s*total stall cycles:\s*(\d+)")
RE_TVC = re.compile(r"TVC hold cycles:\s*(\d+)")
RE_ATTN = re.compile(r"attention-class requests through PIM:\s*(\d+)")
RE_AAU = re.compile(r"AAU fused events:\s*(\d+)\s*;\s*saved bytes:\s*(\d+)")


def _last_value(core_map: Dict[int, Dict[str, int]], core_id: int,
                 key: str, value: int) -> None:
    """Overwrite `key` for `core_id` — the simulator prints cumulative
    counters on every snapshot, so the very last snapshot per core is
    the authoritative one."""
    core_map.setdefault(core_id, {})
    core_map[core_id][key] = value


def parse_log(log_path: Path) -> Dict:
    txt = log_path.read_text()

    cores: Dict[int, Dict[str, int]] = {}
    for m in RE_CORE_MATMUL.finditer(txt):
        cid = int(m.group(1))
        _last_value(cores, cid, "matmul_active", int(m.group(2)))
        _last_value(cores, cid, "vector_active", int(m.group(3)))
    for m in RE_CORE_MEM.finditer(txt):
        cid = int(m.group(1))
        _last_value(cores, cid, "memory_unit_idle", int(m.group(2)))
        _last_value(cores, cid, "systolic_bubble", int(m.group(3)))
        _last_value(cores, cid, "core_idle", int(m.group(4)))
    for m in RE_CORE_TOTAL.finditer(txt):
        cid = int(m.group(1))
        _last_value(cores, cid, "total_cycle", int(m.group(2)))

    # HBM per-channel bandwidth: last snapshot per channel wins.
    hbm: Dict[int, Dict[str, int]] = {}
    for m in RE_HBM_BW.finditer(txt):
        ch = int(m.group(1))
        hbm[ch] = {"channel": ch, "bw_util_pct": int(m.group(2)),
                   "reads": int(m.group(3)), "writes": int(m.group(4))}

    # End-of-run PIM summary.
    pim_cycle_match = RE_PIM_FINAL.search(txt)
    sim_finished = RE_SIM_FINISHED.search(txt)
    gtsu = RE_GTSU.search(txt)
    tvc = RE_TVC.search(txt)
    attn = RE_ATTN.search(txt)
    aau = RE_AAU.search(txt)

    total_npu_cycles: Optional[int] = None
    if pim_cycle_match:
        total_npu_cycles = int(pim_cycle_match.group(1))
    elif sim_finished:
        total_npu_cycles = int(sim_finished.group(1))

    total_pim_cycles = int(pim_cycle_match.group(2)) if pim_cycle_match else None

    # Aggregate NPU sums across cores (each core ran ~total_cycle cycles;
    # summed actives are what's eligible for a stacked-bar figure).
    summed = {k: 0 for k in ("matmul_active", "vector_active",
                              "systolic_bubble", "memory_unit_idle",
                              "core_idle", "total_cycle")}
    core_list = []
    for cid in sorted(cores):
        c = cores[cid]
        core_list.append({"core_id": cid, **c})
        for k in summed:
            summed[k] += c.get(k, 0)

    npu_util_pct: Dict[str, float] = {}
    # Percentages are computed per-core then averaged; using summed
    # total_cycle makes the denominator the total multi-core work.
    denom = summed["total_cycle"] or 1
    for k in ("matmul_active", "vector_active", "systolic_bubble",
              "memory_unit_idle", "core_idle"):
        npu_util_pct[f"{k}_pct"] = round(100.0 * summed[k] / denom, 3)

    hbm_list = [hbm[c] for c in sorted(hbm)]
    bw_avg = (sum(h["bw_util_pct"] for h in hbm_list) / len(hbm_list)) if hbm_list else 0.0

    out = {
        "total_npu_cycles": total_npu_cycles,
        "total_pim_cycles": total_pim_cycles,
        "cores": core_list,
        "npu_summed": summed,
        "npu_util_pct": npu_util_pct,
        "pim": {
            "final_pim_cycle": total_pim_cycles,
            "gtsu_switches": int(gtsu.group(1)) if gtsu else 0,
            "gtsu_stall_cycles": int(gtsu.group(2)) if gtsu else 0,
            "tvc_hold_cycles": int(tvc.group(1)) if tvc else 0,
            "attention_class_requests": int(attn.group(1)) if attn else 0,
            "aau_fused_events": int(aau.group(1)) if aau else 0,
            "aau_fusion_saved_bytes": int(aau.group(2)) if aau else 0,
        },
        "hbm_bw": hbm_list,
        "hbm_bw_weighted_avg_pct": round(bw_avg, 2),
        "source_log": str(log_path.resolve()),
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--log", type=Path, required=True,
                    help="Path to a Simulator log.txt")
    ap.add_argument("--out", type=Path, default=None,
                    help="Where to write utilization.json "
                         "(default: alongside log.txt)")
    args = ap.parse_args()

    if not args.log.exists():
        print(f"[parse_utilization] log not found: {args.log}", file=sys.stderr)
        return 2
    out = parse_log(args.log)
    dest = args.out or args.log.parent / "utilization.json"
    dest.write_text(json.dumps(out, indent=2))
    pct = out["npu_util_pct"]
    print(f"[parse_utilization] {args.log}")
    print(f"  total_npu_cycles={out['total_npu_cycles']}  "
          f"total_pim_cycles={out['total_pim_cycles']}")
    print(f"  npu matmul={pct['matmul_active_pct']}%  "
          f"vector={pct['vector_active_pct']}%  "
          f"mem_idle={pct['memory_unit_idle_pct']}%  "
          f"core_idle={pct['core_idle_pct']}%")
    print(f"  hbm avg bw util={out['hbm_bw_weighted_avg_pct']}%  "
          f"({len(out['hbm_bw'])} channels)")
    print(f"  -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
