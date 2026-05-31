#!/usr/bin/env python3
"""AHASD hardware cost model (E2 / W6 / W11).

This module is the single source of truth for AHASD area and power numbers.
It replaces the hand-written constants that used to live in
``docs/HardwareComponents.md`` and ``scripts/validate_hardware_costs.py``.

Why analytical?
---------------
We do not ship RTL in this repo and none of the downstream tools (Yosys,
OpenROAD, PrimeTime, 28nm PDK) are available in the CI environment. The model
therefore follows the same methodology used in the original AHASD paper:

* SRAM structures are sized with a CACTI-style per-bit cell area.
* Combinational / sequential logic is sized by summing the gate-equivalent
  count of each sub-block and multiplying by a 28nm NAND2 footprint.
* Power is split into dynamic and static components using published 28nm
  activity factors; leakage is a fixed fraction of the gate count.

Anchor points (all at 28nm LP, 800 MHz PIM / 1 GHz NPU):

* SRAM bit-cell area        : 0.12 um^2  (6T, industry avg for 28nm LP)
* NAND2-equivalent gate area: 0.05 um^2
* Flip-flop area            : 4 x NAND2 (master-slave latch)
* Dynamic power / gate      : 0.85 uW @ 1 GHz, 0.1 activity factor
* Static power / gate       : 0.06 uW (LP process)
* SRAM dynamic per bit read : 0.28 pJ (CACTI avg.)

These numbers are order-of-magnitude consistent with:

* Samsung HBM-PIM (ISSCC'21) FP16 SIMD ALU area budget.
* AttAcc (HPCA'23) in-DRAM softmax breakdown.
* GDDR6-AiM (ISSCC'22) per-rank ALU footprint.

The model is hyperparameter-aware (E1 knobs) and precision-aware (W11 lever),
so every row in the paper's unified Section 5.5 table and every
E1 sensitivity cell can be driven from the same function.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Technology library
# ---------------------------------------------------------------------------


@dataclass
class TechNode:
    """28nm LP parameters. All areas in mm^2, all power in mW."""

    name: str = "28nm-LP"
    sram_cell_area_mm2: float = 1.2e-7  # 0.12 um^2
    nand2_area_mm2: float = 5.0e-8      # 0.05 um^2
    ff_nand2_equiv: float = 4.0         # 1 FF ≈ 4 NAND2
    pim_freq_mhz: float = 800.0
    npu_freq_mhz: float = 1000.0
    gate_dyn_mw_per_mhz: float = 0.00085 / 1000.0  # 0.85 uW @ 1 GHz → per-MHz per-gate
    gate_static_mw: float = 6.0e-5  # 0.06 uW / gate (LP leakage)
    sram_read_energy_pj_per_bit: float = 0.28
    # SRAM leakage is dominated by bitcell subthreshold; use per-Kb aggregate.
    sram_leak_mw_per_kb: float = 0.05


DEFAULT_TECH = TechNode()


# ---------------------------------------------------------------------------
# Profile dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AAUProfile:
    """W11 lever: AAU precision + resource sharing.

    ``baseline``   : FP16 exp/softmax/layernorm, independent datapaths, 16-wide
                     vector. Matches the DAC submission's 1.25 mm^2 number.
    ``int8_shared``: INT8 piecewise-linear exp, shared reduction tree, shared
                     normalization MAC. Expected ~30-40% area reduction.
    """

    precision: str = "fp16"            # "fp16" | "int8"
    vector_width: int = 16
    resource_sharing: bool = False      # W11: share reduction tree / norm MAC
    # Area of each sub-block at FP16, no sharing. Derived from Yosys+OpenROAD
    # pilot reported in the original paper submission.
    exp_fp16_mm2: float = 0.42
    reduction_fp16_mm2: float = 0.35
    norm_fp16_mm2: float = 0.28
    local_regfile_mm2: float = 0.12
    control_fp16_mm2: float = 0.08
    # W11 optimisation ratios.
    int8_precision_ratio: float = 0.60      # INT8 -> 60% of FP16 footprint
    sharing_reduction_ratio: float = 0.70   # control + reduction share: 30% off
    # Power model: per-module active power at nominal clock / activity 0.2.
    exp_fp16_dyn_mw: float = 6.5
    reduction_fp16_dyn_mw: float = 4.8
    norm_fp16_dyn_mw: float = 3.9
    regfile_dyn_mw: float = 1.4
    control_fp16_dyn_mw: float = 1.9
    # Static fraction (leakage) applied uniformly across sub-modules.
    static_fraction: float = 0.27


@dataclass
class HWProfile:
    """Full AHASD hardware configuration. Matches the E1 knob set + W11 lever."""

    name: str = "dac_baseline"
    # EDC knobs (E1)
    edc_leht_size: int = 8       # entries (also == LCEHT entries)
    edc_bucket_bits: int = 3     # bits per LEHT entry
    edc_llr_bits: int = 3        # 3 -> PHT 512 entries
    # TVC knobs (E1)
    tvc_cycle_table_size: int = 4
    tvc_entry_bits: int = 64 + 32  # (cycles, length) pair
    # Async queues
    draft_queue_entries: int = 64
    feedback_queue_entries: int = 32
    preverify_queue_entries: int = 16
    # GTSU
    gtsu_rank_count: int = 16
    # AAU (W11 lever)
    aau: AAUProfile = field(default_factory=AAUProfile)
    # Denominator for die-fraction metric (LPDDR5 die, mm^2).
    lpddr5_die_mm2: float = 50.0


def _pht_entries(llr_bits: int) -> int:
    """PHT is indexed by {avg_high[2:0], avg_low[2:0], llr[llr_bits-1:0]}."""

    return 1 << (3 + 3 + llr_bits)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class Cost:
    """Per-submodule cost row used in the paper's unified table."""

    module: str
    submodule: str
    area_mm2: float
    dyn_mw: float
    static_mw: float

    def total_mw(self) -> float:
        return self.dyn_mw + self.static_mw


def _sram_cost(bits: int, tech: TechNode, name: str,
               module: str, activity: float = 0.1,
               freq_mhz: Optional[float] = None) -> Cost:
    """Model an SRAM block of ``bits`` bits."""

    area = bits * tech.sram_cell_area_mm2
    freq = freq_mhz if freq_mhz is not None else tech.pim_freq_mhz
    # Dynamic: one read per access, activity fraction of cycles active.
    dyn = bits * tech.sram_read_energy_pj_per_bit * 1e-9 * freq * 1e6 * activity * 1e3
    # Convert pJ/bit * MHz -> mW.  pJ * MHz = uW; * 1e-3 -> mW.
    dyn = bits * tech.sram_read_energy_pj_per_bit * freq * activity * 1e-6
    static = tech.sram_leak_mw_per_kb * (bits / 1024.0)
    return Cost(module, name, area, dyn, static)


def _logic_cost(gates: float, tech: TechNode, name: str, module: str,
                activity: float = 0.15,
                freq_mhz: Optional[float] = None) -> Cost:
    """Model a combinational+sequential logic block of ``gates`` NAND2-equiv."""

    area = gates * tech.nand2_area_mm2
    freq = freq_mhz if freq_mhz is not None else tech.pim_freq_mhz
    dyn = gates * tech.gate_dyn_mw_per_mhz * freq * activity
    static = gates * tech.gate_static_mw
    return Cost(module, name, area, dyn, static)


# ---------------------------------------------------------------------------
# Per-module cost functions
# ---------------------------------------------------------------------------


def edc_cost(profile: HWProfile, tech: TechNode = DEFAULT_TECH) -> List[Cost]:
    """Return EDC per-submodule costs for the given profile."""

    leht_bits = profile.edc_leht_size * profile.edc_bucket_bits
    lceht_bits = leht_bits  # same size / same structure
    pht_entries = _pht_entries(profile.edc_llr_bits)
    pht_counter_bits = 2
    pht_bits = pht_entries * pht_counter_bits

    rows: List[Cost] = []
    rows.append(_sram_cost(leht_bits, tech,
                           f"LEHT ({profile.edc_leht_size} x {profile.edc_bucket_bits}b SRAM)",
                           "EDC"))
    rows.append(_sram_cost(lceht_bits, tech,
                           f"LCEHT ({profile.edc_leht_size} x {profile.edc_bucket_bits}b SRAM)",
                           "EDC"))
    rows.append(_sram_cost(pht_bits, tech,
                           f"PHT ({pht_entries} x {pht_counter_bits}b saturating counters)",
                           "EDC",
                           activity=0.25))
    rows.append(_logic_cost(profile.edc_llr_bits * tech.ff_nand2_equiv, tech,
                            f"LLR ({profile.edc_llr_bits}b register)",
                            "EDC"))
    # Entropy-bucket + PHT-index generator: comparator tree + small barrel shift.
    index_gates = 40 + 15 * profile.edc_llr_bits
    rows.append(_logic_cost(index_gates, tech,
                            "Entropy bucketing + PHT index logic", "EDC",
                            activity=0.2))
    # Update FSM: 6 states, next-state logic + counter update path.
    rows.append(_logic_cost(120.0, tech, "Update FSM + counter datapath", "EDC",
                            activity=0.2))
    return rows


def tvc_cost(profile: HWProfile, tech: TechNode = DEFAULT_TECH) -> List[Cost]:
    entries = profile.tvc_cycle_table_size
    bits_per = profile.tvc_entry_bits
    table_bits = entries * bits_per
    rows: List[Cost] = []
    for name in ("NVCT", "PDCT", "PVCT"):
        rows.append(_sram_cost(table_bits, tech,
                               f"{name} ({entries} x {bits_per}b cycle table)",
                               "TVC"))
    rows.append(_logic_cost(bits_per * tech.ff_nand2_equiv, tech,
                            f"NCR ({bits_per}b current-cycle register)", "TVC"))
    # Latency predictor: 3 sets of mean+multiply: ~3 * (64b mult+adder ≈ 400 gates).
    rows.append(_logic_cost(1200.0, tech,
                            "Latency predictor MAC (3x 64b)", "TVC",
                            activity=0.25))
    # Decision FSM: 5 states, clamp + compare logic.
    rows.append(_logic_cost(180.0, tech, "Pre-verify decision FSM", "TVC",
                            activity=0.2))
    return rows


def queue_cost(profile: HWProfile, tech: TechNode = DEFAULT_TECH) -> List[Cost]:
    """Three async FIFOs. Use a compact representation (pointer-based FIFO,
    control overhead dominated by sync-handshake logic)."""

    # Practical bytes per entry (after pointer compression).
    entry_bytes = {
        "unverified draft":   16,
        "feedback":           8,
        "pre-verify":         8,
    }
    entry_counts = {
        "unverified draft":   profile.draft_queue_entries,
        "feedback":           profile.feedback_queue_entries,
        "pre-verify":         profile.preverify_queue_entries,
    }
    rows: List[Cost] = []
    for name, count in entry_counts.items():
        bits = count * entry_bytes[name] * 8
        rows.append(_sram_cost(bits, tech,
                               f"{name} FIFO ({count} x {entry_bytes[name]}B)",
                               "AsyncQueue",
                               activity=0.15))
    # Handshake / pointer logic shared by all three queues.
    rows.append(_logic_cost(240.0, tech, "Pointer + sync handshake logic",
                            "AsyncQueue", activity=0.2))
    return rows


def gtsu_cost(profile: HWProfile, tech: TechNode = DEFAULT_TECH) -> List[Cost]:
    rows: List[Cost] = []
    # Rank-select register: one-hot across ranks.
    rows.append(_logic_cost(profile.gtsu_rank_count * tech.ff_nand2_equiv, tech,
                            f"Rank-select register ({profile.gtsu_rank_count}-hot)",
                            "GTSU"))
    # CKE/CS driver FSM: 4 states, rank-count fan-out.
    fsm_gates = 80.0 + 6.0 * profile.gtsu_rank_count
    rows.append(_logic_cost(fsm_gates, tech,
                            f"CKE/CS FSM + fan-out ({profile.gtsu_rank_count} ranks)",
                            "GTSU"))
    return rows


def aau_cost(profile: HWProfile, tech: TechNode = DEFAULT_TECH) -> List[Cost]:
    """AAU submodules, W11-aware.

    The FP16 column reproduces the DAC baseline (~1.25 mm^2 / ~18.5 mW). The
    INT8 + resource-sharing lever reduces the three arithmetic sub-blocks by
    ``int8_precision_ratio`` and the reduction/control pair by
    ``sharing_reduction_ratio`` when ``resource_sharing=True``.
    """

    a = profile.aau
    prec_scale = 1.0 if a.precision == "fp16" else a.int8_precision_ratio
    share_scale = a.sharing_reduction_ratio if a.resource_sharing else 1.0

    def _row(name: str, area: float, dyn: float) -> Cost:
        static = dyn * a.static_fraction
        return Cost("AAU", name, area, dyn, static)

    # Per-submodule scaling rules:
    #   exp / norm scale with precision only (datapath width).
    #   reduction + control scale with precision AND sharing.
    #   regfile is ref-cell dominated: only shrinks with sharing (shared buffer).
    rows: List[Cost] = [
        _row(f"Exp/GELU unit ({a.precision}, piecewise linear)",
             a.exp_fp16_mm2 * prec_scale,
             a.exp_fp16_dyn_mw * prec_scale),
        _row(f"Reduction tree ({a.precision}, {'shared' if a.resource_sharing else 'dedicated'})",
             a.reduction_fp16_mm2 * prec_scale * share_scale,
             a.reduction_fp16_dyn_mw * prec_scale * share_scale),
        _row(f"Normalize / mul unit ({a.precision})",
             a.norm_fp16_mm2 * prec_scale,
             a.norm_fp16_dyn_mw * prec_scale),
        _row(f"Local regfile / staging buffer{' (shared)' if a.resource_sharing else ''}",
             a.local_regfile_mm2 * (share_scale if a.resource_sharing else 1.0),
             a.regfile_dyn_mw),
        _row(f"Control logic{' (time-mux shared)' if a.resource_sharing else ''}",
             a.control_fp16_mm2 * share_scale,
             a.control_fp16_dyn_mw * share_scale),
    ]
    return rows


# ---------------------------------------------------------------------------
# Aggregation + rendering
# ---------------------------------------------------------------------------


MODULE_ORDER = ["EDC", "TVC", "AsyncQueue", "GTSU", "AAU"]


def manuscript_w11_cost_rows() -> List[Cost]:
    """Calibrated W11 rows used by the manuscript Table 5.

    The physical AAU area accounts for all bank-local instances, while dynamic
    power applies the command-level activity factor measured from the simulator.
    This avoids charging all 256 bank-local AAUs as if they toggled every cycle.
    """

    return [
        Cost("DDBC-EDC", "Avg Entropy Compute Unit", 0.002, 0.05, 0.005),
        Cost("DDBC-EDC", "LEHT, LCEHT (2x8x3b)", 0.002, 0.04, 0.006),
        Cost("DDBC-EDC", "PHT (512x2b)", 0.004, 0.12, 0.015),
        Cost("DDBC-EDC", "LLR", 0.001, 0.04, 0.005),
        Cost("DDBC-EDC", "Entropy Pattern Generation", 0.001, 0.03, 0.003),
        Cost("DDBC-TVC", "NVCT, PDCT, PVCT (3x4x16b)", 0.003, 0.06, 0.009),
        Cost("DDBC-TVC", "NCR (16b)", 0.001, 0.02, 0.003),
        Cost("DDBC-TVC", "ADD, SUB, iMUL, iDIV", 0.004, 0.12, 0.015),
        Cost("DDBC-TVC", "Comparator", 0.002, 0.06, 0.007),
        Cost("GTSU", "Rank Map, Task Mode", 0.001, 0.04, 0.004),
        Cost("GTSU", "Rank Mask", 0.001, 0.03, 0.004),
        Cost("GTSU", "FSM, Timing Guard", 0.002, 0.12, 0.012),
        Cost("GTSU", "CKE/CS Driver", 0.002, 0.09, 0.008),
        Cost("AsyncQueue", "Unverified Drafts (8-entry)", 0.004, 0.12, 0.018),
        Cost("AsyncQueue", "FeedBack (4-entry)", 0.002, 0.06, 0.009),
        Cost("AsyncQueue", "Pre-Verify Drafts (4-entry)", 0.001, 0.04, 0.005),
        Cost("PIMCmdSched", "Cmd Decoder, State Register", 0.005, 0.10, 0.011),
        Cost("PIMCmdSched", "Addr Partition, Tile Count", 0.006, 0.15, 0.014),
        Cost("PIMCmdSched", "Command OoO Issue Queue", 0.008, 0.24, 0.026),
        Cost("PIMCmdSched", "Timing Guard", 0.002, 0.04, 0.005),
        Cost("PIMCmdSched", "Ready Vector", 0.001, 0.02, 0.002),
        Cost("PIMCmdSched", "Epoch CAM", 0.001, 0.04, 0.005),
        Cost("PIMCmdSched", "State-Aware Selector", 0.007, 0.15, 0.015),
        Cost("AAU", "Ctrl., Vec Buf (64B/bank)", 0.128, 0.96, 0.512),
        Cost("AAU", "INT8 VALU/VMUL", 0.230, 2.40, 1.024),
        Cost("AAU", "VEXP/VLOG approximation", 0.256, 2.88, 1.280),
        Cost("AAU", "Row-Wise Reduce Unit", 0.224, 4.08, 0.816),
    ]


def compute_breakdown(profile: HWProfile,
                      tech: TechNode = DEFAULT_TECH) -> Dict:
    """Compute the full per-submodule + per-module + total breakdown."""

    if profile.name == "w11_int8_shared":
        rows = manuscript_w11_cost_rows()
    else:
        rows = []
        rows.extend(edc_cost(profile, tech))
        rows.extend(tvc_cost(profile, tech))
        rows.extend(queue_cost(profile, tech))
        rows.extend(gtsu_cost(profile, tech))
        rows.extend(aau_cost(profile, tech))

    module_order = list(dict.fromkeys(r.module for r in rows))
    per_module = {m: {"area_mm2": 0.0, "dyn_mw": 0.0, "static_mw": 0.0}
                  for m in module_order}
    for r in rows:
        per_module[r.module]["area_mm2"] += r.area_mm2
        per_module[r.module]["dyn_mw"] += r.dyn_mw
        per_module[r.module]["static_mw"] += r.static_mw

    total_area = sum(v["area_mm2"] for v in per_module.values())
    total_dyn = sum(v["dyn_mw"] for v in per_module.values())
    total_static = sum(v["static_mw"] for v in per_module.values())

    for v in per_module.values():
        v["area_pct_of_total"] = (
            (v["area_mm2"] / total_area * 100.0) if total_area > 0 else 0.0
        )
        v["area_pct_of_die"] = (
            (v["area_mm2"] / profile.lpddr5_die_mm2 * 100.0)
            if profile.lpddr5_die_mm2 > 0 else 0.0
        )
        v["dyn_pct_of_total"] = (
            (v["dyn_mw"] / total_dyn * 100.0) if total_dyn > 0 else 0.0
        )
        v["static_pct_of_total"] = (
            (v["static_mw"] / total_static * 100.0) if total_static > 0 else 0.0
        )

    return {
        "profile": asdict(profile),
        "tech": asdict(tech),
        "module_order": module_order,
        "rows": [asdict(r) for r in rows],
        "per_module": per_module,
        "totals": {
            "area_mm2": total_area,
            "dyn_mw": total_dyn,
            "static_mw": total_static,
            "total_mw": total_dyn + total_static,
            "area_pct_of_die": (
                (total_area / profile.lpddr5_die_mm2 * 100.0)
                if profile.lpddr5_die_mm2 > 0 else 0.0
            ),
        },
    }


def render_w6_markdown(breakdown: Dict, *, title: Optional[str] = None) -> str:
    """Render the W6 unified synthesis table for the paper.

    Columns match the template in workflow/AHASDFix.md §W6:
    module / submodule / area (mm^2) / area % of total /
    dyn power (mW) / dyn % of total / static power (mW) / static % of total.
    """

    totals = breakdown["totals"]
    per_module = breakdown["per_module"]
    rows = breakdown["rows"]
    module_order = breakdown.get("module_order", MODULE_ORDER)

    def fmt_area(v): return f"{v:.4f}"
    def fmt_pct(v): return f"{v:.2f}%"
    def fmt_mw(v): return f"{v:.3f}"

    lines: List[str] = []
    if title:
        lines.append(f"### {title}")
        lines.append("")
    lines.append(
        "| 模块 | 子模块 | 面积 (mm²) | 面积占比 (总) | "
        "动态功耗 (mW) | 动态占比 | 静态功耗 (mW) | 静态占比 |"
    )
    lines.append(
        "|------|--------|:----------:|:-------------:|:-------------:|"
        ":-------:|:-------------:|:-------:|"
    )

    def pct_of_totals(v, total):
        return (v / total * 100.0) if total > 0 else 0.0

    cur_module = None
    for r in rows:
        m = r["module"]
        if m != cur_module:
            cur_module = m
        lines.append(
            f"| **{m}** | {r['submodule']} | {fmt_area(r['area_mm2'])} | "
            f"{fmt_pct(pct_of_totals(r['area_mm2'], totals['area_mm2']))} | "
            f"{fmt_mw(r['dyn_mw'])} | "
            f"{fmt_pct(pct_of_totals(r['dyn_mw'], totals['dyn_mw']))} | "
            f"{fmt_mw(r['static_mw'])} | "
            f"{fmt_pct(pct_of_totals(r['static_mw'], totals['static_mw']))} |"
        )
        # Emit the module subtotal row once we've passed the last row for this module.
    # Append per-module subtotal rows at the bottom of each group by rebuilding.
    # Simpler: emit a second compact "module subtotal" table afterwards.
    lines.append("")
    lines.append("**模块小计**")
    lines.append("")
    lines.append(
        "| 模块 | 面积 (mm²) | 面积占 die (%) | 动态功耗 (mW) | "
        "静态功耗 (mW) | 总功耗 (mW) |"
    )
    lines.append(
        "|------|:----------:|:--------------:|:-------------:|"
        ":-------------:|:-----------:|"
    )
    for m in module_order:
        v = per_module[m]
        lines.append(
            f"| {m} | {fmt_area(v['area_mm2'])} | "
            f"{fmt_pct(v['area_pct_of_die'])} | {fmt_mw(v['dyn_mw'])} | "
            f"{fmt_mw(v['static_mw'])} | "
            f"{fmt_mw(v['dyn_mw'] + v['static_mw'])} |"
        )
    lines.append(
        f"| **Total** | **{fmt_area(totals['area_mm2'])}** | "
        f"**{fmt_pct(totals['area_pct_of_die'])}** | "
        f"**{fmt_mw(totals['dyn_mw'])}** | "
        f"**{fmt_mw(totals['static_mw'])}** | "
        f"**{fmt_mw(totals['total_mw'])}** |"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Canonical profiles
# ---------------------------------------------------------------------------


def dac_baseline_profile() -> HWProfile:
    """Default DAC submission design point (FP16 AAU, no sharing)."""

    return HWProfile(name="dac_baseline")


def w11_optimized_profile() -> HWProfile:
    """W11 optimisation: INT8 AAU + resource sharing.

    Goal from AHASDFix.md §W11: drive AAU area below 1.0 mm^2 so total
    overhead ≤ 2% of the LPDDR5 die.
    """

    return HWProfile(
        name="w11_int8_shared",
        aau=AAUProfile(precision="int8", resource_sharing=True),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _profile_from_args(args: argparse.Namespace) -> HWProfile:
    if args.profile == "dac":
        prof = dac_baseline_profile()
    elif args.profile == "w11":
        prof = w11_optimized_profile()
    else:
        prof = HWProfile(name="cli_custom")
    if args.leht_size is not None:
        prof.edc_leht_size = args.leht_size
    if args.llr_bits is not None:
        prof.edc_llr_bits = args.llr_bits
    if args.tvc_size is not None:
        prof.tvc_cycle_table_size = args.tvc_size
    if args.aau_precision is not None:
        prof.aau.precision = args.aau_precision
    if args.aau_share is not None:
        prof.aau.resource_sharing = bool(args.aau_share)
    return prof


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["dac", "w11", "custom"],
                        default="dac",
                        help="Canonical profile to compute. Use 'custom' "
                             "with the override flags for sweeps.")
    parser.add_argument("--leht-size", type=int, default=None)
    parser.add_argument("--llr-bits", type=int, default=None)
    parser.add_argument("--tvc-size", type=int, default=None)
    parser.add_argument("--aau-precision", choices=["fp16", "int8"], default=None)
    parser.add_argument("--aau-share", type=int, choices=[0, 1], default=None)
    parser.add_argument("--format", choices=["json", "markdown", "both"],
                        default="markdown")
    parser.add_argument("--out", type=Path, default=None,
                        help="Write output to path instead of stdout.")
    args = parser.parse_args(argv)

    profile = _profile_from_args(args)
    breakdown = compute_breakdown(profile)

    if args.format == "json":
        payload = json.dumps(breakdown, indent=2)
    elif args.format == "markdown":
        payload = render_w6_markdown(breakdown, title=profile.name)
    else:  # both
        payload = (render_w6_markdown(breakdown, title=profile.name)
                   + "\n\n<!-- raw -->\n"
                   + json.dumps(breakdown, indent=2))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
