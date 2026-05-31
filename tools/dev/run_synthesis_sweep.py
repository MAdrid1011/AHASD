#!/usr/bin/env python3
"""E2 driver: emit the W6 unified synthesis table + W11 optimisation comparison.

Usage:
    tools/dev/run_synthesis_sweep.py --out workflow/runs/e2

Produces, inside ``--out``:

* ``w6_dac_baseline.md``        : Paper §5.5 unified table for the DAC design point.
* ``w6_w11_optimized.md``       : Same table with W11 INT8 + resource sharing.
* ``w6_comparison.md``          : Side-by-side module-subtotal comparison.
* ``synthesis_breakdown.json``  : Machine-readable dump of both profiles.
* ``e1_axis_sweep.{md,json}``   : Per-axis row for each E1 sensitivity cell
                                   so the paper can footnote how area / power
                                   move when the E1 knobs are swept.

The intent is that this script is rerun whenever the analytical model or
profile assumptions change; its outputs are committed and cited directly in
AHASPro.md §5.5 and docs/HardwareComponents.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from hardware_cost_model import (  # noqa: E402
    AAUProfile,
    HWProfile,
    compute_breakdown,
    dac_baseline_profile,
    render_w6_markdown,
    w11_optimized_profile,
    MODULE_ORDER,
)


def _fmt_area(v: float) -> str:
    return f"{v:.4f}"


def _fmt_mw(v: float) -> str:
    return f"{v:.3f}"


def _fmt_pct(v: float) -> str:
    return f"{v:.2f}%"


def render_comparison_markdown(dac: Dict, w11: Dict) -> str:
    """Render a module-subtotal side-by-side for §5.5 discussion."""

    lines: List[str] = []
    lines.append("# W6 / W11 synthesis comparison")
    lines.append("")
    lines.append(
        "The DAC baseline column reproduces the submission numbers. The W11 "
        "column applies INT8 precision + reduction/control resource sharing "
        "to the AAU sub-modules, per AHASDFix.md §W11 goal of ≤ 2% die "
        "overhead."
    )
    lines.append("")
    lines.append("| 模块 | DAC 基线 面积 (mm²) | DAC 基线 功耗 (mW) | "
                 "W11 优化 面积 (mm²) | W11 优化 功耗 (mW) | Δ 面积 | Δ 功耗 |")
    lines.append("|------|:------------------:|:------------------:|:------------------:|"
                 ":------------------:|:------:|:------:|")

    def row(module: str) -> str:
        d = dac["per_module"][module]
        w = w11["per_module"][module]
        d_area = d["area_mm2"]
        w_area = w["area_mm2"]
        d_total = d["dyn_mw"] + d["static_mw"]
        w_total = w["dyn_mw"] + w["static_mw"]
        delta_area = (w_area - d_area) / d_area * 100.0 if d_area else 0.0
        delta_power = (w_total - d_total) / d_total * 100.0 if d_total else 0.0
        return (f"| {module} | {_fmt_area(d_area)} | {_fmt_mw(d_total)} | "
                f"{_fmt_area(w_area)} | {_fmt_mw(w_total)} | "
                f"{delta_area:+.1f}% | {delta_power:+.1f}% |")

    for m in MODULE_ORDER:
        lines.append(row(m))

    dt = dac["totals"]
    wt = w11["totals"]
    delta_total_area = (wt["area_mm2"] - dt["area_mm2"]) / dt["area_mm2"] * 100.0
    delta_total_power = ((wt["dyn_mw"] + wt["static_mw"]) -
                         (dt["dyn_mw"] + dt["static_mw"])) / \
        (dt["dyn_mw"] + dt["static_mw"]) * 100.0
    lines.append(
        f"| **Total** | **{_fmt_area(dt['area_mm2'])}** | "
        f"**{_fmt_mw(dt['dyn_mw'] + dt['static_mw'])}** | "
        f"**{_fmt_area(wt['area_mm2'])}** | "
        f"**{_fmt_mw(wt['dyn_mw'] + wt['static_mw'])}** | "
        f"**{delta_total_area:+.1f}%** | **{delta_total_power:+.1f}%** |"
    )
    lines.append("")
    lines.append(
        f"**Die overhead** (LPDDR5 die = 50 mm²): "
        f"DAC baseline {_fmt_pct(dt['area_pct_of_die'])} → "
        f"W11 optimised {_fmt_pct(wt['area_pct_of_die'])}."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# E1 sensitivity rows
# ---------------------------------------------------------------------------


E1_AXES = {
    "edc_h_max":            [10.0, 8.0, 7.0, 6.0],       # informational only
    "edc_leht_size":        [4, 8, 12, 16],
    "edc_llr_bits":         [2, 3, 4],
    "tvc_cycle_table_size": [1, 2, 4, 8],
}


def _e1_profile(axis: str, value) -> HWProfile:
    """Build a ``HWProfile`` reflecting a single E1 sweep cell.

    ``edc_h_max`` is a pure-runtime knob (float threshold) with no area /
    power footprint, so the profile equals the DAC baseline. The row is still
    emitted so readers can see the area is insensitive to H_max.
    """

    p = dac_baseline_profile()
    p.name = f"e1_{axis}={value}"
    if axis == "edc_leht_size":
        p.edc_leht_size = int(value)
    elif axis == "edc_llr_bits":
        p.edc_llr_bits = int(value)
    elif axis == "tvc_cycle_table_size":
        p.tvc_cycle_table_size = int(value)
    # edc_h_max: no-op
    return p


def render_e1_sweep_markdown(rows: List[Dict]) -> str:
    lines: List[str] = []
    lines.append("# E1 sensitivity × E2 synthesis cost")
    lines.append("")
    lines.append(
        "For every W2 sensitivity cell this records the resulting EDC / TVC "
        "footprint. H_max is a runtime-only comparator threshold and therefore "
        "cost-invariant; LEHT / LLR / TVC cycle-table size all have directly "
        "computable area terms."
    )
    lines.append("")
    lines.append("| 轴 | 值 | EDC 面积 (mm²) | TVC 面积 (mm²) | Ctrl-logic 合计 (EDC+TVC+Q+GTSU) | Total 面积 (mm²) | Total 功耗 (mW) |")
    lines.append("|----|----|:--------------:|:--------------:|:--------------------------------:|:----------------:|:----------------:|")
    for r in rows:
        tot = r["breakdown"]["totals"]
        pm = r["breakdown"]["per_module"]
        ctrl_area = sum(pm[m]["area_mm2"] for m in ("EDC", "TVC", "AsyncQueue", "GTSU"))
        lines.append(
            f"| {r['axis']} | {r['value']} | "
            f"{_fmt_area(pm['EDC']['area_mm2'])} | "
            f"{_fmt_area(pm['TVC']['area_mm2'])} | "
            f"{_fmt_area(ctrl_area)} | "
            f"{_fmt_area(tot['area_mm2'])} | "
            f"{_fmt_mw(tot['dyn_mw'] + tot['static_mw'])} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=Path("workflow/runs/e2"),
                        help="Output directory for generated artefacts.")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)

    dac = compute_breakdown(dac_baseline_profile())
    w11 = compute_breakdown(w11_optimized_profile())

    dac_md = render_w6_markdown(dac, title="DAC baseline (FP16 AAU, no sharing)")
    w11_md = render_w6_markdown(w11, title="W11 optimised (INT8 AAU + resource sharing)")
    cmp_md = render_comparison_markdown(dac, w11)

    (args.out / "w6_dac_baseline.md").write_text(dac_md + "\n")
    (args.out / "w6_w11_optimized.md").write_text(w11_md + "\n")
    (args.out / "w6_comparison.md").write_text(cmp_md + "\n")

    e1_rows = []
    for axis, values in E1_AXES.items():
        for v in values:
            prof = _e1_profile(axis, v)
            e1_rows.append({
                "axis": axis,
                "value": v,
                "profile_name": prof.name,
                "breakdown": compute_breakdown(prof),
            })

    (args.out / "e1_axis_sweep.md").write_text(
        render_e1_sweep_markdown(e1_rows) + "\n"
    )

    payload = {
        "dac_baseline": dac,
        "w11_optimized": w11,
        "e1_axes": [
            {"axis": r["axis"], "value": r["value"],
             "totals": r["breakdown"]["totals"],
             "per_module": r["breakdown"]["per_module"]}
            for r in e1_rows
        ],
    }
    (args.out / "synthesis_breakdown.json").write_text(
        json.dumps(payload, indent=2)
    )

    print(f"Wrote DAC baseline + W11 optimised + E1 sweep artefacts to {args.out}")
    print(f"  DAC total: {dac['totals']['area_mm2']:.4f} mm^2 "
          f"({dac['totals']['area_pct_of_die']:.2f}% of die), "
          f"{dac['totals']['total_mw']:.2f} mW")
    print(f"  W11 total: {w11['totals']['area_mm2']:.4f} mm^2 "
          f"({w11['totals']['area_pct_of_die']:.2f}% of die), "
          f"{w11['totals']['total_mw']:.2f} mW")
    return 0


if __name__ == "__main__":
    sys.exit(main())
