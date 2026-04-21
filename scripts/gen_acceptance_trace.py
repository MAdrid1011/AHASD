#!/usr/bin/env python3
"""
B2.5 — Synthetic acceptance trace generator.

Emits a CSV that the C++ SyntheticAcceptanceModel can replay via
`accept_trace_path` when `accept_mode` is `trace_replay` or
`trace_then_parametric`.

Schema (header row is emitted):
    round,draft_length,avg_entropy,accepted_length

Honesty: this script does NOT run a real LLM. Acceptance rates are drawn
from per-algorithm literature priors (see ALGO_PRIORS below) and modulated
by a synthetic entropy schedule that mirrors the scheduler's
`compute_entropy_hint`. Re-calibration against real LLM draft/target
outputs belongs to a later milestone — at that point the schema stays
the same, only the sampling strategy changes.

Usage example:
    scripts/gen_acceptance_trace.py \
        --model-pair opt-125m-opt-125m-t \
        --algorithm specdec \
        --rounds 32 \
        --max-draft-length 4 \
        --seed 2025 \
        --output /tmp/accept.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from pathlib import Path

# Per-algorithm priors — tuple of (base_acceptance, entropy_alpha,
# length_decay, p_min). Numbers are a rough synthesis of what the
# speculative-decoding literature reports for the paper's model pairs:
#   specdec     : classical speculative sampling (Leviathan et al., 2023)
#   svip        : stochastic verifier-in-place (SVIP, ASPLOS 2024-class)
#   adaedl      : adaptive entropy-driven draft length (AdaEDL variants)
#   banditspec  : bandit-based draft length (ICLR 2024-class)
# These are NOT calibrated from the paper experiments — B2.7 will exercise
# the on/off switch; calibration lives in later phases.
ALGO_PRIORS = {
    "specdec":    (0.82, 0.10, 0.30, 0.05),
    "svip":       (0.85, 0.12, 0.25, 0.07),
    "adaedl":     (0.83, 0.14, 0.20, 0.05),
    "banditspec": (0.80, 0.09, 0.35, 0.05),
}

# Per model-family modifiers (lower-cap only; synthesis). Used to bias
# the base acceptance slightly based on the draft/target model pair so
# the resulting CSV is reproducible, not just a constant distribution.
FAMILY_BUMPS = {
    ("opt", "opt"):     -0.02,
    ("llama2", "llama2"): 0.00,
    ("palm", "palm"):   -0.01,
    ("opt125m", "opt125mt"): -0.03,
}


def family_key(model_name: str) -> str:
    n = model_name.lower()
    for fam in ("llama2", "llama3", "palm", "opt"):
        if n.startswith(fam):
            return fam
    return n


def parse_model_pair(s: str) -> tuple[str, str]:
    """
    Accept formats:
        <draft>-<target>       e.g. opt-125m-opt-125m-t
        <draft>:<target>       explicit separator
    Falls back to splitting at the last '-' pair if ambiguous.
    """
    if ":" in s:
        a, b = s.split(":", 1)
        return a, b
    # Best-effort split for hyphenated names: grab the shortest prefix
    # that matches a known family and use the rest as the target.
    known_prefixes = ("opt-", "llama2-", "llama3-", "palm-")
    for pfx in known_prefixes:
        if s.startswith(pfx):
            # find the second occurrence of a known prefix
            for other in known_prefixes:
                idx = s.find(other, len(pfx))
                if idx > 0:
                    return s[:idx].rstrip("-"), s[idx:]
    # Fall back to midpoint split
    mid = len(s) // 2
    return s[:mid].rstrip("-"), s[mid:].lstrip("-")


def synthetic_entropy(round_idx: int, total_rounds: int, rng: random.Random) -> float:
    """Mirror the scheduler's compute_entropy_hint: ramps from 2.5 -> 5.0
    with a small per-round jitter. Output domain [0.5, 9.5]."""
    if total_rounds <= 1:
        ratio = 0.0
    else:
        ratio = round_idx / (total_rounds - 1)
    base = 2.5 + 2.5 * ratio
    jitter = rng.uniform(-0.25, 0.25) + 0.5 * (round_idx % 4)
    return max(0.5, min(9.5, base + jitter))


def sample_accepted(draft_length: int, entropy: float, coeffs, rng: random.Random) -> int:
    base, alpha, length_decay, p_min = coeffs
    if draft_length <= 0:
        return 0
    p0 = max(p_min, min(1.0, base * math.exp(-alpha * entropy)))
    denom = max(1, draft_length - 1)
    accepted = 0
    for i in range(draft_length):
        frac = i / denom
        p = p0 * (1.0 - length_decay * frac)
        if p < p_min:
            p = p_min
        if p > 1.0:
            p = 1.0
        if rng.random() <= p:
            accepted += 1
        else:
            break
    return accepted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--model-pair", required=True,
                    help="draft-target (e.g. opt-125m-opt-125m-t or llama2-7b-llama2-13b)")
    ap.add_argument("--algorithm", default="specdec", choices=sorted(ALGO_PRIORS.keys()))
    ap.add_argument("--rounds", type=int, default=32)
    ap.add_argument("--max-draft-length", type=int, default=4)
    ap.add_argument("--min-draft-length", type=int, default=1)
    ap.add_argument("--seed", type=int, default=2025)
    ap.add_argument("--output", required=True, help="Path for the CSV trace")
    ap.add_argument("--request-id", type=int, default=None,
                    help="If set, emit 5-column rows with this request_id prefix")
    ap.add_argument("--provenance", action="store_true",
                    help="Emit '# ...' provenance comment lines at the top of the CSV")
    args = ap.parse_args()

    base, alpha, length_decay, p_min = ALGO_PRIORS[args.algorithm]
    draft_name, target_name = parse_model_pair(args.model_pair)
    bump_key = (family_key(draft_name), family_key(target_name))
    base += FAMILY_BUMPS.get(bump_key, 0.0)
    coeffs = (base, alpha, length_decay, p_min)

    rng = random.Random(args.seed)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", newline="") as f:
        if args.provenance:
            f.write("# B2.5 synthetic acceptance trace (NOT calibrated against real LLMs)\n")
            f.write(f"# model_pair={args.model_pair} algorithm={args.algorithm}\n")
            f.write(f"# coeffs base={coeffs[0]:.3f} alpha={coeffs[1]:.3f} "
                    f"length_decay={coeffs[2]:.3f} p_min={coeffs[3]:.3f}\n")
            f.write(f"# seed={args.seed} rounds={args.rounds} "
                    f"max_draft_length={args.max_draft_length}\n")
        writer = csv.writer(f)
        if args.request_id is None:
            writer.writerow(["round", "draft_length", "avg_entropy", "accepted_length"])
        else:
            writer.writerow(["request_id", "round", "draft_length",
                             "avg_entropy", "accepted_length"])
        for r in range(args.rounds):
            k = rng.randint(max(1, args.min_draft_length), max(1, args.max_draft_length))
            h = synthetic_entropy(r, args.rounds, rng)
            a = sample_accepted(k, h, coeffs, rng)
            if args.request_id is None:
                writer.writerow([r, k, f"{h:.4f}", a])
            else:
                writer.writerow([args.request_id, r, k, f"{h:.4f}", a])

    print(f"Wrote {args.rounds} rows to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
