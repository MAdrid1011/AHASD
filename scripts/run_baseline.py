#!/usr/bin/env python3
"""
C1 — Reusable baseline runner.

Resolves a committed overlay under `configs/baselines/<name>.json` against
its `_inherits` base, stamps in workload + acceptance choices, runs the
Simulator, and dumps log + parsed metrics into the output directory.

Designed to be consumed by D1's matrix driver (3 model pairs × 4
algorithms × 4 configs) — every cell there is one invocation of this
script with a different `--baseline` + `--model-pair`. For C1 we only
need to prove two presets (npu_only, ahasd_full) match the B2.7 axes.

Usage:

    scripts/run_baseline.py \
        --baseline npu_only \
        --model-pair opt-125m:opt-125m-t \
        --workload-trace workloads/smoke_p4_g8_2req.csv \
        --acceptance-csv workflow/b27/accept_trace.csv \
        --output-dir workflow/c1/npu_only_opt125m
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

BASELINES_DIR = REPO / "configs/baselines"


# Same metric wall used by run_b27_smoke.py, kept close to that file so
# the two scripts agree on definitions. Copy-paste is intentional here;
# extracting to a shared module is scope for a later refactor.
REGEXES = [
    ("sim_finished_cycles",      r"Simulation Finished at (\d+) cycle"),
    ("final_npu_cycle",          r"\[PIMBackend\] final_npu_cycle=(\d+)"),
    ("final_pim_cycle",          r"final_pim_cycle=(\d+)"),
    ("gtsu_stall_cycles",        r"GTSU switches: \d+\s*;\s*total stall cycles:\s*(\d+)"),
    ("tvc_hold_cycles",          r"TVC hold cycles:\s*(\d+)"),
    ("attention_class_requests", r"attention-class requests through PIM:\s*(\d+)"),
    ("total_energy_mj",          r"Total Energy:\s*([\d.]+) mJ"),
    ("draft_rounds",             r"Total Draft Rounds:\s*(\d+)"),
    ("verifies",                 r"Total Verifies:\s*(\d+)"),
    ("pim_aau_fused_events",     r"AAU fused events:\s*(\d+)"),
    ("gtsu_switches",            r"GTSU switches:\s*(\d+)"),
    ("acceptance_ratio",         r"accept_ratio=([\d.]+)"),
    ("acceptance_samples",       r"Acceptance Samples:\s*(\d+)"),
]


def parse_log(text: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for key, pat in REGEXES:
        m = re.search(pat, text)
        if not m:
            continue
        val = m.group(1)
        try:
            out[key] = float(val)
        except ValueError:
            out[key] = val  # type: ignore[assignment]
    m = re.search(r"Total Accepted Tokens:\s*(\d+)\s*\(([\d.]+)%", text)
    if m:
        out["accepted_tokens"] = float(m.group(1))
        out["accepted_pct"] = float(m.group(2))
    return out


def resolve_overlay(baseline: str) -> Dict[str, Any]:
    """Load `<baseline>.json`, merge in the base it inherits from, and
    strip the documentation keys."""
    overlay_path = BASELINES_DIR / f"{baseline}.json"
    if not overlay_path.exists():
        raise SystemExit(f"[baseline] no overlay at {overlay_path}; available: "
                         f"{[p.stem for p in BASELINES_DIR.glob('*.json') if not p.stem.startswith('_')]}")
    overlay = json.loads(overlay_path.read_text())
    base_name = overlay.pop("_inherits", None)
    overlay.pop("_doc", None)
    if not base_name:
        raise SystemExit(f"[baseline] {overlay_path} is missing `_inherits`")
    base_path = BASELINES_DIR / base_name
    if not base_path.exists():
        raise SystemExit(f"[baseline] base {base_path} not found")
    merged = json.loads(base_path.read_text())
    merged.update(overlay)
    return merged


def parse_model_pair(s: str) -> tuple[str, str]:
    if ":" in s:
        a, b = s.split(":", 1)
        return a, b
    # Fallback: treat a single name as self-pair, useful for micro-smokes.
    return s, s


def write_models_list(draft: str, target: str, trace_file_name: str,
                       max_draft_length: int, out_path: Path) -> None:
    models = {
        "models": [
            {"name": draft, "role": "draft", "trace_file": trace_file_name,
             "scheduler": "spec",
             "scheduler_config": {"max_batch_size": 1, "check_mem_size": False,
                                   "default_draft_length": max_draft_length}},
            {"name": target, "role": "target", "trace_file": trace_file_name,
             "scheduler": "spec",
             "scheduler_config": {"max_batch_size": 1, "check_mem_size": False,
                                   "default_draft_length": max_draft_length}},
        ]
    }
    out_path.write_text(json.dumps(models, indent=2))


def run_simulator(onnxim: Path, cfg: Path, models_list: Path,
                   trace_file_name: str, log_path: Path, timeout_s: int) -> int:
    sim_bin = onnxim / "build/bin/Simulator"
    if not sim_bin.exists():
        raise SystemExit(f"[baseline] simulator binary missing at {sim_bin}; "
                         f"run `cmake --build .` under ONNXim/build first")
    env = os.environ.copy()
    env["ONNXIM_HOME"] = str(onnxim)
    cmd = [str(sim_bin), "--config", str(cfg),
           "--models_list", str(models_list),
           "--mode", "language", "--trace_file", trace_file_name]
    print(f"[baseline] $ {' '.join(cmd)}")
    with log_path.open("w") as f:
        return subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                              cwd=onnxim, env=env, timeout=timeout_s).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--baseline", required=True,
                    help="Overlay stem under configs/baselines/ (e.g. npu_only, ahasd_full)")
    ap.add_argument("--model-pair", required=True,
                    help="draft:target (e.g. opt-125m:opt-125m-t)")
    ap.add_argument("--workload-trace", required=True, type=Path,
                    help="Simulator workload CSV (time,prompt_length,target_length,cached_length)")
    ap.add_argument("--acceptance-csv", type=Path, default=None,
                    help="If set, activates trace_replay acceptance mode with this CSV")
    ap.add_argument("--accept-seed", type=int, default=2025)
    ap.add_argument("--max-draft-length", type=int, default=4)
    ap.add_argument("--onnxim", type=Path, default=REPO / "ONNXim")
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--timeout-s", type=int, default=600)
    args = ap.parse_args()

    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = resolve_overlay(args.baseline)
    cfg["max_draft_length"] = args.max_draft_length
    cfg["accept_rng_seed"] = args.accept_seed
    if args.acceptance_csv:
        cfg["accept_mode"] = "trace_replay"
        cfg["accept_trace_path"] = str(args.acceptance_csv.resolve())
    else:
        cfg["accept_mode"] = "parametric"
        cfg.pop("accept_trace_path", None)

    cfg_path = out_dir / "onnxim_config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2))

    draft, target = parse_model_pair(args.model_pair)

    # Deploy workload trace into ONNXim/traces/ under a stable name so
    # Simulator's ONNXIM_HOME-relative resolution can find it.
    traces_dir = args.onnxim.resolve() / "traces"
    traces_dir.mkdir(exist_ok=True)
    deployed_name = f"baseline_{args.baseline}_{draft}_{target}.csv"
    deployed_path = traces_dir / deployed_name
    shutil.copy(args.workload_trace, deployed_path)

    models_list = out_dir / "models_list.json"
    write_models_list(draft, target, deployed_name, args.max_draft_length, models_list)

    log_path = out_dir / "log.txt"
    rc = run_simulator(args.onnxim.resolve(), cfg_path, models_list,
                        deployed_name, log_path, args.timeout_s)
    metrics = parse_log(log_path.read_text())
    metrics["__baseline"] = args.baseline
    metrics["__model_pair"] = f"{draft}:{target}"
    metrics["__workload_trace"] = str(args.workload_trace.resolve())
    metrics["__acceptance_csv"] = (str(args.acceptance_csv.resolve())
                                    if args.acceptance_csv else None)
    metrics["__returncode"] = rc
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))

    if rc != 0:
        print(f"[baseline] simulator rc={rc}; see {log_path}", file=sys.stderr)
        return rc
    print(f"[baseline] ok. cycles={metrics.get('sim_finished_cycles')} "
          f"energy={metrics.get('total_energy_mj')} mJ "
          f"accept_ratio={metrics.get('acceptance_ratio')} "
          f"log={log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
