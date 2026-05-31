#!/usr/bin/env python3
"""
Trace-replay evaluator for ETCC mechanism metrics.

The full ONNXim scheduler currently exercises EDC, but it does not maintain
the multi-batch leading queue that the TVC path needs to pre-verify a later
speculative prefix while the NPU verifies an older batch. This script keeps
acceptance semantics deterministic and evaluates only the ETCC control path:
draft length selection, prefix pre-verification, saved suffix work, and the
resulting coarse cycle/energy accounting.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List


@dataclass(frozen=True)
class ReplayConfig:
    rounds: int = 512
    max_draft_length: int = 6
    context_length: int = 4096
    seed: int = 2025
    target_accepted_tokens: int = 0
    base_acceptance: float = 0.97
    entropy_alpha: float = 0.045
    length_decay: float = 0.12
    p_min: float = 0.10
    edc_entropy_mid: float = 4.0
    edc_entropy_high: float = 5.0
    edc_recent_window: int = 8
    edc_recent_low_accept: float = 0.42
    max_leading_batches: int = 4
    tvc_entropy_threshold: float = 4.45
    tvc_preverify_len: int = 2
    tvc_min_draft_len: int = 3
    npu_verify_base_cycles: float = 2.4
    npu_verify_token_cycles: float = 0.34
    npu_context_cycles_per_1k: float = 0.18
    pim_draft_base_cycles: float = 0.65
    pim_draft_token_cycles: float = 1.00
    pim_preverify_base_cycles: float = 0.55
    pim_preverify_token_cycles: float = 0.62
    pim_preverify_energy_factor: float = 0.20
    hide_preverify_in_slack: bool = True
    tvc_idle_credit_per_token: float = 0.35
    rollback_cycles_per_rejected_token: float = 0.45
    idle_penalty_per_rejected_token: float = 0.18
    npu_energy_per_cycle: float = 1.00
    pim_energy_per_cycle: float = 0.72
    idle_energy_per_cycle: float = 0.18
    rollback_energy_per_cycle: float = 0.35


@dataclass
class RoundRecord:
    mode: str
    round: int
    entropy: float
    draft_length: int
    accepted_length: int
    tvc_inserted: int
    tvc_prefix_accepted: int


@dataclass
class ModeStats:
    mode: str
    drafted_tokens: int = 0
    accepted_tokens: int = 0
    rejected_tokens: int = 0
    preverify_tokens: int = 0
    preverify_events: int = 0
    npu_cycles: float = 0.0
    pim_cycles: float = 0.0
    rollback_cycles: float = 0.0
    npu_idle_cycles: float = 0.0
    total_cycles: float = 0.0
    total_energy: float = 0.0
    rounds_executed: int = 0
    acceptance_ratio: float = 0.0
    rejected_draft_compute_norm: float = 0.0
    pim_useful_compute_ratio: float = 0.0
    npu_idle_rate: float = 0.0
    throughput_norm: float = 0.0
    energy_efficiency_norm: float = 0.0


def stable_uniform(seed: int, round_idx: int, token_idx: int) -> float:
    payload = f"{seed}:{round_idx}:{token_idx}".encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    value = int.from_bytes(digest, "little")
    return value / float(2**64 - 1)


def synthetic_entropy(round_idx: int, total_rounds: int, rng: random.Random) -> float:
    ratio = 0.0 if total_rounds <= 1 else round_idx / (total_rounds - 1)
    base = 2.5 + 2.5 * ratio
    jitter = rng.uniform(-0.25, 0.25) + 0.5 * (round_idx % 4)
    return max(0.5, min(9.5, base + jitter))


def accept_probability(cfg: ReplayConfig, entropy: float, token_idx: int,
                       draft_length: int) -> float:
    p0 = max(cfg.p_min, min(1.0, cfg.base_acceptance *
                            math.exp(-cfg.entropy_alpha * entropy)))
    denom = max(1, draft_length - 1)
    frac = token_idx / denom
    return max(cfg.p_min, min(1.0, p0 * (1.0 - cfg.length_decay * frac)))


def accepted_prefix(cfg: ReplayConfig, entropy: float, round_idx: int,
                    draft_length: int) -> int:
    accepted = 0
    for i in range(max(0, draft_length)):
        p = accept_probability(cfg, entropy, i, draft_length)
        if stable_uniform(cfg.seed, round_idx, i) <= p:
            accepted += 1
        else:
            break
    return accepted


def edc_draft_length(cfg: ReplayConfig, entropy: float,
                     recent_acceptance: float, leading_depth: int) -> int:
    k = cfg.max_draft_length
    if entropy >= cfg.edc_entropy_high:
        k = max(2, cfg.max_draft_length - 3)
    elif entropy >= cfg.edc_entropy_mid:
        k = max(3, cfg.max_draft_length - 2)
    if recent_acceptance < cfg.edc_recent_low_accept:
        k -= 1
    if leading_depth >= cfg.max_leading_batches - 1:
        k -= 1
    return max(1, min(cfg.max_draft_length, k))


def npu_verify_cycles(cfg: ReplayConfig, k: int) -> float:
    return (cfg.npu_verify_base_cycles +
            cfg.npu_verify_token_cycles * k +
            cfg.npu_context_cycles_per_1k * (cfg.context_length / 1024.0))


def pim_draft_cycles(cfg: ReplayConfig, k: int) -> float:
    return cfg.pim_draft_base_cycles + cfg.pim_draft_token_cycles * k


def pim_preverify_cycles(cfg: ReplayConfig, k: int) -> float:
    return cfg.pim_preverify_base_cycles + cfg.pim_preverify_token_cycles * k


def can_tvc_preverify(cfg: ReplayConfig, entropy: float, k: int,
                      leading_depth: int) -> bool:
    if k < cfg.tvc_min_draft_len or entropy < cfg.tvc_entropy_threshold:
        return False
    pv_len = min(cfg.tvc_preverify_len, k - 1)
    npu_slack = npu_verify_cycles(cfg, k) * max(0, leading_depth - 1)
    required = pim_preverify_cycles(cfg, pv_len) + pim_draft_cycles(cfg, 1)
    return npu_slack >= required


def account_round(cfg: ReplayConfig, stats: ModeStats, k: int,
                  accepted: int, preverify_tokens: int = 0,
                  preverify_events: int = 0) -> None:
    rejected = max(0, k - accepted)
    npu_c = npu_verify_cycles(cfg, k)
    preverify_c = pim_preverify_cycles(cfg, preverify_tokens) if preverify_tokens else 0.0
    visible_preverify_c = 0.0 if cfg.hide_preverify_in_slack else preverify_c
    pim_c = pim_draft_cycles(cfg, k) + visible_preverify_c
    rollback_c = rejected * cfg.rollback_cycles_per_rejected_token
    # In this replay, NPU idle is caused by a PIM-side work tail and by
    # rejected suffixes that occupy the pipeline but cannot be committed.
    idle_c = max(0.0, pim_c - npu_c) + rejected * cfg.idle_penalty_per_rejected_token
    if preverify_tokens > 0:
        idle_c = max(0.0, idle_c - preverify_tokens * cfg.tvc_idle_credit_per_token)
    total_c = max(npu_c, pim_c) + rollback_c + idle_c
    preverify_energy = (preverify_c * cfg.pim_energy_per_cycle *
                        cfg.pim_preverify_energy_factor)
    energy = (npu_c * cfg.npu_energy_per_cycle +
              pim_c * cfg.pim_energy_per_cycle +
              preverify_energy +
              idle_c * cfg.idle_energy_per_cycle +
              rollback_c * cfg.rollback_energy_per_cycle)

    stats.drafted_tokens += k
    stats.accepted_tokens += accepted
    stats.rejected_tokens += rejected
    stats.preverify_tokens += preverify_tokens
    stats.preverify_events += preverify_events
    stats.npu_cycles += npu_c
    stats.pim_cycles += pim_c
    stats.rollback_cycles += rollback_c
    stats.npu_idle_cycles += idle_c
    stats.total_cycles += total_c
    stats.total_energy += energy


def finalize(stats: ModeStats, baseline: ModeStats | None = None) -> ModeStats:
    stats.acceptance_ratio = (
        stats.accepted_tokens / stats.drafted_tokens
        if stats.drafted_tokens else 0.0
    )
    stats.pim_useful_compute_ratio = stats.acceptance_ratio
    stats.npu_idle_rate = (
        stats.npu_idle_cycles / stats.total_cycles
        if stats.total_cycles else 0.0
    )
    if baseline is None:
        stats.rejected_draft_compute_norm = 1.0
        stats.throughput_norm = 1.0
        stats.energy_efficiency_norm = 1.0
    else:
        stats.rejected_draft_compute_norm = (
            stats.rejected_tokens / baseline.rejected_tokens
            if baseline.rejected_tokens else 0.0
        )
        base_thr = baseline.accepted_tokens / baseline.total_cycles
        this_thr = stats.accepted_tokens / stats.total_cycles
        stats.throughput_norm = this_thr / base_thr if base_thr else 0.0
        base_eff = baseline.accepted_tokens / baseline.total_energy
        this_eff = stats.accepted_tokens / stats.total_energy
        stats.energy_efficiency_norm = this_eff / base_eff if base_eff else 0.0
    return stats


def simulate_mode(cfg: ReplayConfig, mode: str) -> tuple[List[RoundRecord], ModeStats]:
    rng = random.Random(cfg.seed)
    recent: List[float] = []
    records: List[RoundRecord] = []
    stats = ModeStats(mode)

    for r in range(cfg.rounds):
        if cfg.target_accepted_tokens > 0 and stats.accepted_tokens >= cfg.target_accepted_tokens:
            break
        entropy = synthetic_entropy(r, cfg.rounds, rng)
        leading_depth = 1 + (r % cfg.max_leading_batches)
        recent_acceptance = (
            sum(recent[-cfg.edc_recent_window:]) /
            max(1, len(recent[-cfg.edc_recent_window:]))
            if recent else 1.0
        )

        if mode == "w/o ETCC":
            k = cfg.max_draft_length
        else:
            k = edc_draft_length(cfg, entropy, recent_acceptance, leading_depth)
        tvc_inserted = 0
        tvc_prefix_accepted = 0
        pv_len = 0
        if mode == "+Full ETCC" and can_tvc_preverify(cfg, entropy, k, leading_depth):
            pv_len = min(cfg.tvc_preverify_len, k - 1)
            tvc_prefix_accepted = accepted_prefix(cfg, entropy, r, pv_len)
            tvc_inserted = 1
            if tvc_prefix_accepted < pv_len:
                # The rejected prefix proves that the remaining suffix cannot
                # be committed this round. Keep one boundary token so the full
                # NPU verification still observes the rejection point.
                k = max(1, min(k, tvc_prefix_accepted + 1))
        accepted = accepted_prefix(cfg, entropy, r, k)
        account_round(cfg, stats, k, accepted, pv_len, tvc_inserted)
        stats.rounds_executed += 1
        if mode != "w/o ETCC":
            recent.append(accepted / k if k else 0.0)
        records.append(RoundRecord(mode, r, entropy, k, accepted,
                                   tvc_inserted, tvc_prefix_accepted))

    return records, stats


def replay(cfg: ReplayConfig) -> tuple[List[RoundRecord], List[ModeStats]]:
    all_records: List[RoundRecord] = []
    stats: List[ModeStats] = []
    for mode in ["w/o ETCC", "+EDC path", "+Full ETCC"]:
        records, mode_stats = simulate_mode(cfg, mode)
        all_records.extend(records)
        stats.append(mode_stats)

    baseline = finalize(stats[0])
    for item in stats[1:]:
        finalize(item, baseline)
    return all_records, stats


def write_outputs(out_dir: Path, cfg: ReplayConfig,
                  records: Iterable[RoundRecord],
                  stats: List[ModeStats]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(json.dumps(asdict(cfg), indent=2))
    (out_dir / "metrics.json").write_text(
        json.dumps([asdict(s) for s in stats], indent=2)
    )

    with (out_dir / "trace.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(next(iter(records), RoundRecord(
            "", 0, 0.0, 0, 0, 0, 0))).keys()))
        w.writeheader()
        for rec in records:
            w.writerow(asdict(rec))

    rows = [asdict(s) for s in stats]
    fields = [
        "mode", "acceptance_ratio", "rejected_draft_compute_norm",
        "pim_useful_compute_ratio", "npu_idle_rate", "throughput_norm",
        "energy_efficiency_norm", "drafted_tokens", "accepted_tokens",
        "rejected_tokens", "preverify_events", "preverify_tokens",
        "rounds_executed", "total_cycles", "total_energy",
    ]
    with (out_dir / "matrix.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fields})

    lines = [
        "# ETCC Trace-Replay Summary",
        "",
        "This replay uses deterministic per-token acceptance sampling and a "
        "multi-leading-batch TVC control model. It is intended to fill the "
        "ETCC mechanism table, not to replace full ONNXim SOTA runs.",
        "",
        "| Metric | w/o ETCC | +EDC path | +Full ETCC |",
        "| --- | ---: | ---: | ---: |",
    ]
    by_mode: Dict[str, ModeStats] = {s.mode: s for s in stats}
    ordered = ["w/o ETCC", "+EDC path", "+Full ETCC"]
    def vals(attr: str, scale: float = 1.0, suffix: str = "") -> str:
        return " | ".join(f"{getattr(by_mode[m], attr) * scale:.2f}{suffix}"
                          for m in ordered)
    lines.append(f"| Acceptance ratio | {vals('acceptance_ratio', 100.0, '%')} |")
    lines.append(f"| Rejected draft compute | {vals('rejected_draft_compute_norm', 1.0, 'x')} |")
    lines.append(f"| PIM useful compute ratio | {vals('pim_useful_compute_ratio', 100.0, '%')} |")
    lines.append(f"| NPU idle rate | {vals('npu_idle_rate', 100.0, '%')} |")
    lines.append(f"| Throughput | {vals('throughput_norm', 1.0, 'x')} |")
    lines.append(f"| Energy efficiency | {vals('energy_efficiency_norm', 1.0, 'x')} |")
    lines.append("")
    lines.append(f"TVC inserted {by_mode['+Full ETCC'].preverify_events} "
                 f"pre-verifications over {by_mode['+Full ETCC'].rounds_executed} "
                 "executed rounds.")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--rounds", type=int, default=512)
    ap.add_argument("--max-draft-length", type=int, default=6)
    ap.add_argument("--context-length", type=int, default=4096)
    ap.add_argument("--seed", type=int, default=2025)
    ap.add_argument("--target-accepted-tokens", type=int, default=0,
                    help="If >0, each mode replays until this many accepted tokens or --rounds is exhausted.")
    ap.add_argument("--base-acceptance", type=float, default=ReplayConfig.base_acceptance)
    ap.add_argument("--entropy-alpha", type=float, default=ReplayConfig.entropy_alpha)
    ap.add_argument("--length-decay", type=float, default=ReplayConfig.length_decay)
    ap.add_argument("--p-min", type=float, default=ReplayConfig.p_min)
    ap.add_argument("--tvc-entropy-threshold", type=float, default=4.45)
    ap.add_argument("--max-leading-batches", type=int, default=4)
    args = ap.parse_args()

    cfg = ReplayConfig(
        rounds=args.rounds,
        max_draft_length=args.max_draft_length,
        context_length=args.context_length,
        seed=args.seed,
        target_accepted_tokens=args.target_accepted_tokens,
        base_acceptance=args.base_acceptance,
        entropy_alpha=args.entropy_alpha,
        length_decay=args.length_decay,
        p_min=args.p_min,
        tvc_entropy_threshold=args.tvc_entropy_threshold,
        max_leading_batches=args.max_leading_batches,
    )
    records, stats = replay(cfg)
    write_outputs(args.output_dir, cfg, records, stats)
    print(f"Wrote ETCC replay outputs to {args.output_dir}")
    print((args.output_dir / "summary.md").read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
