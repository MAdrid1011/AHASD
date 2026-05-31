#!/usr/bin/env python3
"""AHASD Hardware Cost Validation (thin wrapper around hardware_cost_model).

Since E2, the per-submodule area + power model lives in
``scripts/hardware_cost_model.py`` and is the single source of truth.
This script now exists solely to:

* Pretty-print the DAC baseline breakdown for reviewers / CI logs.
* Assert the paper's <3% die-overhead claim and return non-zero on violation.
* Produce the W11-optimised view so we can see both profiles in one shot.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from hardware_cost_model import (  # noqa: E402
    compute_breakdown,
    dac_baseline_profile,
    w11_optimized_profile,
)


def _print_breakdown(label: str, breakdown: dict) -> None:
    totals = breakdown["totals"]
    per_module = breakdown["per_module"]
    print(f"\n{'='*70}")
    print(f"{label}")
    print("=" * 70)
    print(
        f"{'Module':<14}{'Area (mm^2)':>14}{'Die %':>10}"
        f"{'Dyn (mW)':>12}{'Static (mW)':>14}{'Total (mW)':>14}"
    )
    print("-" * 70)
    module_order = breakdown.get("module_order") or list(per_module)
    for m in module_order:
        v = per_module[m]
        total_mw = v["dyn_mw"] + v["static_mw"]
        print(
            f"{m:<14}{v['area_mm2']:>14.4f}{v['area_pct_of_die']:>10.2f}"
            f"{v['dyn_mw']:>12.3f}{v['static_mw']:>14.3f}{total_mw:>14.3f}"
        )
    print("-" * 70)
    print(
        f"{'Total':<14}{totals['area_mm2']:>14.4f}"
        f"{totals['area_pct_of_die']:>10.2f}"
        f"{totals['dyn_mw']:>12.3f}{totals['static_mw']:>14.3f}"
        f"{totals['total_mw']:>14.3f}"
    )


def main() -> int:
    print("\n" + "=" * 70)
    print("AHASD HARDWARE COST VALIDATION (E2 / W6)")
    print("Tech node: 28nm-LP | Source: scripts/hardware_cost_model.py")
    print("=" * 70)

    dac = compute_breakdown(dac_baseline_profile())
    w11 = compute_breakdown(w11_optimized_profile())

    _print_breakdown("DAC baseline (FP16 AAU, no resource sharing)", dac)
    _print_breakdown("W11 optimised (INT8 AAU + reduction/control sharing)", w11)

    print("\n" + "=" * 70)
    print("CLAIM VALIDATION")
    print("=" * 70)

    def check(label: str, breakdown: dict, limit_pct: float) -> bool:
        overhead = breakdown["totals"]["area_pct_of_die"]
        status = "✓ PASS" if overhead < limit_pct else "✗ FAIL"
        print(
            f"  {label:<32} overhead = {overhead:.2f}%  "
            f"(limit {limit_pct:.1f}%)  {status}"
        )
        return overhead < limit_pct

    ok = True
    ok &= check("DAC baseline <3% die",     dac, 3.0)
    ok &= check("W11 optimised <2% die",    w11, 2.0)

    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
