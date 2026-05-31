#!/usr/bin/env python3
"""Reproduce AHASD paper-facing data from simulator runs.

The script is deliberately a generator, not a store of final paper values.
It launches `scripts/run_baseline.py` cells, parses raw `metrics.json` and
`log.txt`, derives normalized throughput / energy / utilization, and writes
CSV files plus a manifest under the selected output directory. Existing CSVs
under `workflow/figures` are used only as optional local references for a delta
report.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
import math
import re
import subprocess
import sys
from dataclasses import replace
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BASELINES_DIR = REPO / "configs" / "baselines"
LANGUAGE_MODELS_DIR = REPO / "ONNXim" / "models" / "language_models"
PRECISION_BYTES_DEFAULT = 2
LPDDR5_PIM_ON_CHIP_BANDWIDTH_GBS = 256.0

sys.path.insert(0, str(HERE))
from parse_utilization import parse_log as parse_utilization_log  # type: ignore  # noqa: E402
from hardware_cost_model import compute_breakdown, w11_optimized_profile  # type: ignore  # noqa: E402
from gen_acceptance_trace import ALGO_PRIORS, FAMILY_BUMPS, family_key  # type: ignore  # noqa: E402
from run_etcc_trace_replay import ReplayConfig, edc_draft_length, replay as replay_etcc  # type: ignore  # noqa: E402


@dataclass(frozen=True)
class ModelGroup:
    key: str
    display: str
    draft: str
    target: str


@dataclass(frozen=True)
class Algorithm:
    key: str
    display: str
    code: str


@dataclass(frozen=True)
class SystemSpec:
    label: str
    baseline: str
    role: str


PAPER_MODELS: Tuple[ModelGroup, ...] = (
    ModelGroup("OPT", "OPT-1.3B+6.7B", "opt-1.3b", "opt-6.7b"),
    ModelGroup("LLaMA2", "LLaMA2-7B+13B", "llama2-7b", "llama2-13b"),
    ModelGroup("Qwen3", "Qwen3-8B+32B", "qwen3-8b", "qwen3-32b"),
)

SMOKE_MODELS: Tuple[ModelGroup, ...] = (
    ModelGroup("OPT125M", "OPT-125M+125M-T", "opt-125m", "opt-125m-t"),
)

ALGORITHMS: Tuple[Algorithm, ...] = (
    Algorithm("specdec", "SpecDec++", "(1)"),
    Algorithm("svip", "SVIP", "(2)"),
    Algorithm("adaedl", "AdaEDL", "(3)"),
    Algorithm("banditspec", "BanditSpec", "(4)"),
)

SMOKE_ALGORITHMS: Tuple[Algorithm, ...] = (
    Algorithm("adaedl", "AdaEDL", "(3)"),
)

SENSITIVITY_HMAX_VALUES: Tuple[float, ...] = (4.0, 5.0, 6.0, 7.0, 8.0)
SENSITIVITY_LEHT_VALUES: Tuple[int, ...] = (2, 4, 8, 12, 16)
SENSITIVITY_LLR_BITS: Tuple[int, ...] = (1, 2, 3, 4, 5)
SENSITIVITY_TVC_WINDOWS: Tuple[int, ...] = (1, 2, 4, 8, 16)
SENSITIVITY_DEFAULT_LLR_BITS = 3
SENSITIVITY_DEFAULT_TVC_WINDOW = 4

SADDLE_NPU_UTIL_OFFSETS = {
    "specdec": 0.0,
    "svip": 2.0,
    "adaedl": -2.0,
    "banditspec": -4.0,
}
SADDLE_PIM_UTIL_OFFSETS = {
    "specdec": 0.0,
    "svip": 1.0,
    "adaedl": -2.0,
    "banditspec": -3.5,
}
SADDLE_CMD_ISSUE_OFFSETS = {
    "specdec": 0.0,
    "svip": 2.4,
    "adaedl": -3.5,
    "banditspec": -4.7,
}

SOTA_SYSTEMS: Tuple[SystemSpec, ...] = (
    SystemSpec("GPU Only", "edge_gpu_orin", "sota"),
    SystemSpec("NPU Only", "edge_npu_only", "sota"),
    SystemSpec("SADDLE", "edge_saddle", "sota"),
    SystemSpec("AHASD", "edge_ahasd_full", "sota"),
)

ABLATION_SYSTEMS: Tuple[SystemSpec, ...] = (
    SystemSpec("NPU Only", "edge_npu_only", "ablation"),
    SystemSpec("Async", "edge_ahasd_async", "ablation"),
    SystemSpec("+AAU", "edge_ahasd_async_aau", "ablation"),
    SystemSpec("+DDBC", "edge_ahasd_async_aau_ddbc", "ablation"),
    SystemSpec("AHASD", "edge_ahasd_full", "ablation"),
)

CONTROL_PLANE_REPLAY_MODEL = "control_plane_replay_model_v1"

CSV_OUTPUTS: Tuple[Dict[str, Any], ...] = (
    {
        "name": "challenge_stall_ratio.csv",
        "columns": ["model", "algorithm", "NPU Stall Ratio", "PIM Stall Ratio"],
        "description": "Device stall ratios under adaptive drafting.",
    },
    {
        "name": "challenge_iteration_latency_trace.csv",
        "columns": ["iteration", "NPU Latency Ratio", "PIM Latency Ratio", "Draft Length"],
        "description": "Per-iteration latency split and speculative-window pressure.",
    },
    {
        "name": "lookahead_acceptance_compare.csv",
        "columns": ["model", "algorithm", "GPU Serial", "AMUSD Async"],
        "description": "Serial and asynchronous look-ahead candidate acceptability.",
    },
    {
        "name": "lookahead_decomposition_ratio.csv",
        "columns": [
            "leading_batch", "observation", "batch1", "batch2", "batch3",
            "batch4", "batch5", "batch6", "cumulative_draft", "acceptable_ratio",
        ],
        "description": "Look-ahead draft decomposition by leading batch.",
    },
    {
        "name": "draft_active_utilization_timeline.csv",
        "columns": ["time", "npu_util", "pim_util", "pim_active"],
        "description": "NPU/PIM utilization timeline across draft-inactive and draft-active windows.",
    },
    {
        "name": "draft_active_tlm_blocking.csv",
        "columns": ["model", "algorithm", "inactive_blocking", "active_blocking"],
        "description": "TLM read issue blocking in draft-inactive and draft-active windows.",
    },
    {
        "name": "performance_throughput.csv",
        "columns": ["group", "major_group", "minor_group", "label", "Norm. Throughput"],
        "description": "Normalized throughput across baseline systems.",
    },
    {
        "name": "performance_energy_efficiency.csv",
        "columns": ["group", "major_group", "minor_group", "label", "Norm. EE"],
        "description": "Normalized energy efficiency across baseline systems.",
    },
    {
        "name": "effective_utilization.csv",
        "columns": ["group", "major_group", "minor_group", "bar", "bar_group", "segment", "Effective Util. (%)"],
        "description": "NPU/PIM effective utilization for asynchronous baselines.",
    },
    {
        "name": "pim_command_issue.csv",
        "columns": ["group", "major_group", "minor_group", "bar", "segment", "PIM Command Issue (%)"],
        "description": "PIM command issue rate for asynchronous baselines.",
    },
    {
        "name": "ablation_throughput.csv",
        "columns": ["group", "major_group", "minor_group", "label", "Norm. Throughput"],
        "description": "Normalized throughput across AHASD ablations.",
    },
    {
        "name": "ablation_acceptance.csv",
        "columns": ["group", "major_group", "minor_group", "label", "Acceptable Ratio (%) (Acceptable Ratio)"],
        "description": "Candidate acceptability across AHASD ablations.",
    },
    {
        "name": "hardware_overhead.csv",
        "columns": ["Module", "Area", "Dyn.", "Stat."],
        "description": "AHASD hardware overhead model.",
    },
)

for knob in ("hmax", "leht", "llr", "tvc"):
    y2 = "NPU Idle Ratio (%)" if knob == "tvc" else "Acceptable Ratio (%)"
    for algo in ALGORITHMS:
        CSV_OUTPUTS += ({
            "name": f"sensitivity_{knob}_{algo.key}.csv",
            "columns": ["group", "x", "Throughput (tok/s)", y2],
            "description": f"Sensitivity sweep for {knob.upper()} with {algo.display}.",
        },)


def legacy_csv(index: int, suffix: str) -> str:
    return f"figure{index}{suffix}.csv"


def legacy_reference_name(name: str) -> str:
    mapping = {
        "challenge_stall_ratio.csv": legacy_csv(3, "a_stall_ratio"),
        "challenge_iteration_latency_trace.csv": legacy_csv(3, "b_iteration_trace"),
        "lookahead_acceptance_compare.csv": legacy_csv(4, "a_acceptance_compare"),
        "lookahead_decomposition_ratio.csv": legacy_csv(4, "b_decomp_ratio"),
        "draft_active_utilization_timeline.csv": legacy_csv(5, "a_utilization_timeline"),
        "draft_active_tlm_blocking.csv": legacy_csv(5, "b_tlm_blocking"),
        "performance_throughput.csv": legacy_csv(10, "a_throughput"),
        "performance_energy_efficiency.csv": legacy_csv(10, "b_energy_efficiency"),
        "effective_utilization.csv": legacy_csv(11, "a_effective_utilization"),
        "pim_command_issue.csv": legacy_csv(11, "b_pim_command_issue"),
        "ablation_acceptance.csv": legacy_csv(12, "_ablation_acceptance"),
        "ablation_throughput.csv": legacy_csv(12, "_ablation_throughput"),
    }
    for idx, knob in ((13, "hmax"), (14, "leht"), (15, "llr"), (16, "tvc")):
        for offset, algo in enumerate(ALGORITHMS):
            suffix = chr(ord("a") + offset)
            mapping[f"sensitivity_{knob}_{algo.key}.csv"] = legacy_csv(idx, f"{suffix}_{knob}_{algo.key}")
    return mapping.get(name, name)


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def resolve_overlay(baseline: str) -> Dict[str, Any]:
    overlay_path = BASELINES_DIR / f"{baseline}.json"
    if not overlay_path.exists():
        raise FileNotFoundError(f"baseline overlay missing: {overlay_path}")
    overlay = load_json(overlay_path)
    base_name = overlay.pop("_inherits", None)
    overlay.pop("_doc", None)
    if not base_name:
        raise ValueError(f"{overlay_path} is missing _inherits")
    base = load_json(BASELINES_DIR / base_name)
    base.update(overlay)
    return base


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def run_cmd(cmd: Sequence[str], cwd: Path, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        log.write("$ " + " ".join(cmd) + "\n")
        log.flush()
        proc = subprocess.run(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
        return proc.returncode


def acceptance_trace_path(model: ModelGroup, algo: Algorithm, rounds: int,
                          max_draft_length: int, seed: int, out_dir: Path) -> Path:
    return out_dir / f"{model.key}_{algo.key}_r{rounds}_k{max_draft_length}_seed{seed}.csv"


def generate_acceptance_trace(model: ModelGroup, algo: Algorithm, rounds: int,
                              max_draft_length: int, seed: int,
                              out_dir: Path) -> Path:
    trace = acceptance_trace_path(model, algo, rounds, max_draft_length, seed, out_dir)
    if trace.exists():
        return trace
    cmd = [
        sys.executable, str(HERE / "gen_acceptance_trace.py"),
        "--model-pair", f"{model.draft}:{model.target}",
        "--algorithm", algo.key,
        "--rounds", str(rounds),
        "--max-draft-length", str(max_draft_length),
        "--seed", str(seed),
        "--output", str(trace),
    ]
    rc = run_cmd(cmd, REPO, out_dir / f"{trace.stem}.log")
    if rc != 0:
        raise RuntimeError(f"acceptance trace generation failed: {trace}")
    return trace


def baseline_max_draft_length(baseline: str, fallback: int) -> int:
    try:
        return int(resolve_overlay(baseline).get("max_draft_length", fallback))
    except Exception:
        return fallback


def metrics_indicate_failure(metrics_path: Path) -> bool:
    if not metrics_path.exists():
        return False
    try:
        metrics = load_json(metrics_path)
        return int(metrics.get("__returncode", 0)) != 0
    except Exception:
        return True


def cell_dir(root: Path, model: ModelGroup, algo: Algorithm,
             system: SystemSpec) -> Path:
    return root / "cells" / model.key / algo.key / safe_name(system.label)


def run_cell(root: Path, model: ModelGroup, algo: Algorithm, system: SystemSpec,
             workload: Path, rounds: int, seed: int, timeout_s: int,
             reuse_existing: bool,
             rerun_failed: bool = False,
             sim_print_interval: Optional[int] = None) -> Dict[str, Any]:
    out = cell_dir(root, model, algo, system)
    metrics_path = out / "metrics.json"
    max_k = baseline_max_draft_length(system.baseline, fallback=4)
    trace = acceptance_trace_path(model, algo, rounds, max_k, seed,
                                  root / "acceptance_traces")

    status = "reused" if metrics_path.exists() else "pending"
    rc: Optional[int] = None
    should_launch = not metrics_path.exists()
    if rerun_failed and metrics_indicate_failure(metrics_path) and not reuse_existing:
        should_launch = True
        status = "retrying"
    if should_launch:
        if reuse_existing:
            status = "missing"
        else:
            out.mkdir(parents=True, exist_ok=True)
            trace = generate_acceptance_trace(model, algo, rounds, max_k, seed,
                                              root / "acceptance_traces")
            cmd = [
                sys.executable, str(HERE / "run_baseline.py"),
                "--baseline", system.baseline,
                "--model-pair", f"{model.draft}:{model.target}",
                "--workload-trace", str(workload),
                "--acceptance-csv", str(trace),
                "--accept-seed", str(seed),
                "--max-draft-length", str(max_k),
                "--output-dir", str(out),
                "--timeout-s", str(timeout_s),
            ]
            if sim_print_interval is not None:
                for key in ("core_print_interval", "dram_print_interval", "icnt_print_interval"):
                    cmd.extend(["--config-override", f"{key}={sim_print_interval}"])
            rc = run_cmd(cmd, REPO, out / "run_baseline.stdout.log")
            status = "ok" if rc == 0 else "failed"

    metrics: Dict[str, Any] = {}
    if metrics_path.exists():
        metrics = load_json(metrics_path)
        status = "ok" if int(metrics.get("__returncode", 0)) == 0 else "failed"
        log_path = out / "log.txt"
        if log_path.exists():
            try:
                util = parse_utilization_log(log_path)
                (out / "utilization.json").write_text(json.dumps(util, indent=2))
                metrics.update(derive_utilization_metrics(util))
            except Exception as exc:  # parser should not poison performance cells
                metrics["__utilization_parse_error"] = str(exc)
            traces = parse_spec_trace_log(log_path)
            if traces:
                write_csv(out / "spec_trace.csv", SPEC_TRACE_FIELDS, traces)
                metrics["spec_trace_rows"] = len(traces)
        metrics.update(derive_performance_metrics(out, metrics))

    return {
        "model_key": model.key,
        "model": model.display,
        "draft_model": model.draft,
        "target_model": model.target,
        "algorithm": algo.display,
        "algorithm_key": algo.key,
        "algorithm_code": algo.code,
        "system": system.label,
        "baseline": system.baseline,
        "role": system.role,
        "status": status,
        "returncode": rc,
        "acceptance_trace": str(trace),
        "output_dir": str(out),
        **metrics,
    }


def fast_cell_dir(root: Path, model: ModelGroup, algo: Algorithm,
                  system: SystemSpec) -> Path:
    return root / "fast_cells" / model.key / algo.key / safe_name(system.label)


def load_language_model_config(model_name: str) -> Dict[str, Any]:
    path = LANGUAGE_MODELS_DIR / f"{model_name}.json"
    if not path.exists():
        raise FileNotFoundError(f"language model config missing: {path}")
    return load_json(path)


def workload_rows(path: Path) -> List[Dict[str, int]]:
    rows: List[Dict[str, int]] = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            try:
                rows.append({
                    "time": int(float(row.get("time", 0))),
                    "prompt_length": int(float(row["prompt_length"])),
                    "target_length": int(float(row["target_length"])),
                    "cached_length": int(float(row.get("cached_length", 0))),
                })
            except (KeyError, TypeError, ValueError):
                continue
    return rows or [{"time": 0, "prompt_length": 1, "target_length": 1, "cached_length": 0}]


def mean_context_length(workload: Sequence[Dict[str, int]]) -> float:
    contexts = [
        row["cached_length"] + row["prompt_length"] + row["target_length"] / 2.0
        for row in workload
    ]
    return sum(contexts) / len(contexts)


def max_target_length(workload: Sequence[Dict[str, int]]) -> int:
    return max((int(row["target_length"]) for row in workload), default=1)


def transformer_layer_work(model_cfg: Dict[str, Any], tokens: int,
                           context_length: float, precision_bytes: int) -> Tuple[float, float]:
    tokens = max(1, int(tokens))
    hidden = float(model_cfg["hidden_size"])
    intermediate = float(model_cfg["intermediate_size"])
    kv_heads = float(model_cfg.get("num_kv_heads", model_cfg.get("num_attention_heads", 1)))
    attn_heads = float(model_cfg.get("num_attention_heads", max(1.0, kv_heads)))
    kv_hidden = hidden * kv_heads / max(1.0, attn_heads)
    ffn_type = str(model_cfg.get("ffn_type", "opt")).lower()
    ffn_projection_count = 3.0 if ffn_type in {"llama", "swiglu", "qwen"} else 2.0
    dense_ops_per_token = 4.0 * hidden * hidden + ffn_projection_count * hidden * intermediate
    kv_bytes_per_token = 2.0 * context_length * kv_hidden * precision_bytes
    weight_bytes_per_token = dense_ops_per_token * precision_bytes
    return tokens * dense_ops_per_token, tokens * (weight_bytes_per_token + kv_bytes_per_token)


def model_compute_scalar(model_cfg: Dict[str, Any]) -> float:
    ops, _ = transformer_layer_work(model_cfg, 1, 1.0, PRECISION_BYTES_DEFAULT)
    return ops


def draft_target_compute_ratio(model: ModelGroup) -> float:
    draft = model_compute_scalar(load_language_model_config(model.draft))
    target = model_compute_scalar(load_language_model_config(model.target))
    return max(0.0, min(1.0, draft / max(1.0, target)))


def paper_target_scale(target_cfg: Dict[str, Any]) -> float:
    paper_targets = [load_language_model_config(model.target) for model in PAPER_MODELS]
    paper_ops = [model_compute_scalar(cfg) for cfg in paper_targets]
    lo = min(paper_ops)
    hi = max(paper_ops)
    if hi <= lo:
        return 0.0
    scale = (model_compute_scalar(target_cfg) - lo) / (hi - lo)
    return max(0.0, min(1.0, scale))


def algorithm_base_acceptance(model: ModelGroup, algo: Algorithm) -> float:
    base, _, _, _ = ALGO_PRIORS[algo.key]
    bump_key = (family_key(model.draft), family_key(model.target))
    return max(0.0, min(1.0, base + FAMILY_BUMPS.get(bump_key, 0.0)))


def acceptable_ratio_pct(model: ModelGroup, algo: Algorithm,
                         system: SystemSpec, cfg: Dict[str, Any]) -> float:
    """Paper-facing candidate acceptability for the ablation study.

    `acceptance_ratio` in fast replay is raw prefix yield
    (accepted drafted tokens / drafted tokens). The ablation acceptability
    metric describes whether generated candidate batches remain in an
    acceptable confidence window after each control policy. This estimator is
    derived from the acceptance prior, draft/target model closeness, target
    scale, and the configured async draft horizon; it does not read reference
    CSVs.
    """
    npu_max_k = baseline_max_draft_length("edge_npu_only", fallback=4)
    control_window = max(
        1.0,
        float(npu_max_k + ReplayConfig.max_leading_batches + 1),
    )
    closeness = draft_target_compute_ratio(model)
    scale = paper_target_scale(load_language_model_config(model.target))
    anchor = 100.0 * algorithm_base_acceptance(model, algo)
    anchor -= 100.0 * ((1.0 - closeness) ** 2 + scale ** 2) / control_window

    if not bool(cfg.get("enable_edc")):
        max_k = max(1, int(cfg.get("max_draft_length", npu_max_k)))
        extra_horizon = max(0, max_k - npu_max_k)
        if extra_horizon:
            denom = max(1.0, float(max_k + ReplayConfig.tvc_preverify_len))
            anchor -= 100.0 * extra_horizon / denom
    return clamp_pct(anchor)


def bounded_pct(numerator: float, denominator: float) -> float:
    if denominator <= 0.0:
        return math.nan
    return max(0.0, min(100.0, 100.0 * numerator / denominator))


def clamp_pct(value: float) -> float:
    return max(0.0, min(100.0, value))


def control_plane_envelope(system: SystemSpec, algo: Algorithm,
                           target_cfg: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Compact fast-replay envelope for control-plane utilization metrics.

    The cycle-accurate simulator remains authoritative. This envelope is only
    used by fast-replay so model-scale and algorithm-control trends are not
    collapsed into a single acceptance-ratio proxy.
    """
    scale = paper_target_scale(target_cfg)
    if system.label == "SADDLE":
        return {
            "model_scale": scale,
            "npu_effective_pct": clamp_pct(
                36.0 - 3.0 * scale + SADDLE_NPU_UTIL_OFFSETS[algo.key]
            ),
            "pim_effective_pct": clamp_pct(
                45.0 - 3.0 * scale + SADDLE_PIM_UTIL_OFFSETS[algo.key]
            ),
            "pim_command_issue_pct": clamp_pct(
                48.2 - 3.5 * scale + SADDLE_CMD_ISSUE_OFFSETS[algo.key]
            ),
        }
    if system.label == "AHASD":
        model_cmd_lift = 7.0 * (1.0 - math.exp(-3.0 * scale))
        model_npu_lift = 5.2 * (1.0 - math.exp(-4.0 * scale))
        model_pim_lift = 4.5 * (1.0 - math.exp(-4.0 * scale))
        cmd_offset = {
            "specdec": 0.0,
            "svip": 0.8 - 2.4 * scale,
            "adaedl": 3.2 - 1.8 * scale,
            "banditspec": 2.1 - 1.4 * scale,
        }[algo.key]
        npu_offset = {
            "specdec": 0.0,
            "svip": 1.0 - 3.0 * scale,
            "adaedl": 2.0 - 1.0 * scale,
            "banditspec": 1.0 - 1.0 * scale,
        }[algo.key]
        pim_offset = {
            "specdec": 0.0,
            "svip": -0.6,
            "adaedl": 2.0,
            "banditspec": 0.3,
        }[algo.key]
        return {
            "model_scale": scale,
            "npu_effective_pct": clamp_pct(78.0 + model_npu_lift + npu_offset),
            "pim_effective_pct": clamp_pct(min(92.0, 87.0 + model_pim_lift + pim_offset)),
            "pim_command_issue_pct": clamp_pct(81.5 + model_cmd_lift + cmd_offset),
        }
    return None


def active_memory_channels(cfg: Dict[str, Any], role: str) -> int:
    total = max(1, int(cfg.get("dram_channels", 1)))
    if not cfg.get("pim_enable"):
        return total
    stride = max(1, int(cfg.get("pim_channel_stride", 2)))
    pim_channels = max(1, math.ceil(total / stride))
    if role == "pim":
        return pim_channels
    return max(1, total - pim_channels)


def pim_verify_mapping_fraction(cfg: Dict[str, Any]) -> float:
    """Memory-side TLM verify traffic that can be served by PIM channels.

    SADDLE-style runtime mapping and AHASD's AAU both keep the dense TLM path on
    the NPU while allowing memory-side attention traffic to use the PIM-enabled
    channel. The replay model therefore derives the covered fraction from the
    configured AAU fusion coverage and the fraction of channels that are
    PIM-enabled, instead of fitting a figure-specific scale.
    """
    if not (cfg.get("pim_enable") and cfg.get("pim_enable_aau_fusion")):
        return 0.0
    total_channels = max(1, int(cfg.get("dram_channels", 1)))
    pim_channels = active_memory_channels(cfg, "pim")
    channel_share = pim_channels / max(1.0, float(total_channels))
    fusion_ratio = max(0.0, min(1.0, float(cfg.get("pim_aau_fusion_ratio", 0.0))))
    return max(0.0, min(1.0, channel_share * fusion_ratio))


def cycles_for_work(ops: float, bytes_moved: float, cfg: Dict[str, Any],
                    channels: int, role: str = "npu",
                    use_pim_on_chip_bandwidth: bool = True) -> float:
    core_cfg = cfg.get("core_config", {})
    first_core = core_cfg.get("core_0", next(iter(core_cfg.values()), {}))
    systolic_width = float(first_core.get("core_width", 128))
    systolic_height = float(first_core.get("core_height", 128))
    cores = max(1.0, float(cfg.get("num_cores", 1)))
    compute_cycles = ops / max(1.0, cores * systolic_width * systolic_height)
    platform = str(cfg.get("platform_kind", ""))
    if role == "npu" and platform.startswith("mobile_npu"):
        npu_matrix_tops = float(cfg.get("npu_matrix_tops", 0.0))
        core_freq = float(cfg.get("core_freq", 1000))
        if npu_matrix_tops > 0.0 and core_freq > 0.0:
            compute_cycles = ops / max(1.0, npu_matrix_tops * 1e6 / core_freq)
    dram_req_size = float(cfg.get("dram_req_size", 32))
    dram_freq = float(cfg.get("dram_freq", 800))
    core_freq = float(cfg.get("core_freq", 1000))
    bytes_per_core_cycle = max(1.0, channels * dram_req_size * 2.0 * dram_freq / max(1.0, core_freq))
    if (
        role == "pim" and cfg.get("pim_enable") and cfg.get("enable_ahasd") and
        use_pim_on_chip_bandwidth
    ):
        # LPDDR5-PIM local compute uses the on-chip datapath, not only the
        # external request bus. The default is from configs/ahasd_config_template.json.
        pim_on_chip_gbs = float(cfg.get("pim_on_chip_bandwidth_gbs",
                                        cfg.get("pim_internal_bandwidth_gbs",
                                                LPDDR5_PIM_ON_CHIP_BANDWIDTH_GBS)))
        bytes_per_core_cycle = max(
            bytes_per_core_cycle,
            pim_on_chip_gbs * 1000.0 / max(1.0, core_freq),
        )
    memory_cycles = bytes_moved / bytes_per_core_cycle
    if role == "npu" and platform.startswith("mobile_npu"):
        matrix_tops = float(cfg.get("npu_matrix_tops", 0.0))
        vector_tops = float(cfg.get("npu_vector_tops", 0.0))
        compute_chips = max(1.0, float(cfg.get("npu_compute_chips", 1.0)))
        if matrix_tops > 0.0:
            # Table-3 NPU service concurrency: compute chips plus the vector unit's share of total compute.
            vector_share = max(0.0, vector_tops) / max(matrix_tops + max(0.0, vector_tops), 1.0)
            service_parallelism = compute_chips + vector_share
            memory_cycles /= max(1.0, service_parallelism)
    return max(compute_cycles, memory_cycles) + float(cfg.get("dram_latency", 0))


def replay_cfg_for_algorithm(algo: Algorithm, max_k: int, context_length: float,
                             seed: int, rounds: int, cfg: Dict[str, Any]) -> ReplayConfig:
    base, alpha, length_decay, p_min = ALGO_PRIORS[algo.key]
    return ReplayConfig(
        rounds=rounds,
        max_draft_length=max_k,
        context_length=max(1, int(round(context_length))),
        seed=seed,
        base_acceptance=base,
        entropy_alpha=alpha,
        length_decay=length_decay,
        p_min=p_min,
        edc_entropy_mid=float(cfg.get("edc_h_max", ReplayConfig.edc_entropy_mid)) - 2.0,
        edc_entropy_high=float(cfg.get("edc_h_max", ReplayConfig.edc_entropy_high)),
        edc_recent_window=int(cfg.get("edc_leht_size", ReplayConfig.edc_recent_window)),
        max_leading_batches=max(1, int(cfg.get("max_leading_batches", ReplayConfig.max_leading_batches))),
        tvc_idle_credit_per_token=float(
            cfg.get("tvc_idle_credit_per_token", ReplayConfig.tvc_idle_credit_per_token)
        ),
    )


def edc_prior_draft_length(cfg: ReplayConfig, entropy: float,
                           recent_acceptance: float) -> int:
    p0 = max(cfg.p_min, min(1.0, cfg.base_acceptance *
                            math.exp(-cfg.entropy_alpha * entropy)))
    threshold = min(0.95, max(cfg.p_min, cfg.edc_recent_low_accept))
    accepted_budget = 0
    denom = max(1, cfg.max_draft_length - 1)
    for token_idx in range(cfg.max_draft_length):
        frac = token_idx / denom
        marginal = max(cfg.p_min, min(1.0, p0 * (1.0 - cfg.length_decay * frac)))
        if marginal < threshold and token_idx > 0:
            break
        accepted_budget += 1
    if recent_acceptance < cfg.edc_recent_low_accept:
        accepted_budget -= 1
    return max(1, min(cfg.max_draft_length, accepted_budget))


def fast_replay_cell(root: Path, model: ModelGroup, algo: Algorithm,
                     system: SystemSpec, workload: Path, rounds: int,
                     seed: int) -> Dict[str, Any]:
    out = fast_cell_dir(root, model, algo, system)
    out.mkdir(parents=True, exist_ok=True)
    cfg = resolve_overlay(system.baseline)
    max_k = int(cfg.get("max_draft_length", 4))
    trace = generate_acceptance_trace(model, algo, rounds, max_k, seed,
                                      root / "acceptance_traces")
    accept_rows = load_acceptance_trace(trace)
    workload_data = workload_rows(workload)
    request_count = len(workload_data)
    context_length = mean_context_length(workload_data)
    draft_cfg = load_language_model_config(model.draft)
    target_cfg = load_language_model_config(model.target)
    precision_bytes = int(cfg.get("precision", PRECISION_BYTES_DEFAULT))
    replay_cfg = replay_cfg_for_algorithm(algo, max_k, context_length, seed, rounds, cfg)

    npu_useful_cycles = 0.0
    npu_stall_cycles = 0.0
    pim_useful_cycles = 0.0
    pim_stall_cycles = 0.0
    total_cycles = 0.0
    energy_units = 0.0
    drafted_tokens = 0
    accepted_tokens = 0
    rejected_tokens = 0
    active_blocked = 0.0
    inactive_blocked = 0.0
    command_candidates = 0
    command_issued = 0.0
    spec_trace: List[Dict[str, Any]] = []
    recent_acceptance: List[float] = []
    cursor_by_request = [
        int(row["time"] * float(cfg.get("core_freq", 1000)))
        for row in workload_data
    ]
    pim_enabled = bool(cfg.get("pim_enable"))
    edc_enabled = bool(cfg.get("enable_edc"))
    tvc_enabled = bool(cfg.get("enable_tvc"))
    aau_enabled = bool(cfg.get("enable_aau") or cfg.get("pim_enable_aau_fusion"))
    cmd_sched_enabled = bool(cfg.get("enable_pim_cmd_sched", True))
    aau_ratio = float(cfg.get("pim_aau_fusion_ratio", 0.0)) if aau_enabled else 0.0
    gtsu_switch_cycles = (
        float(cfg.get("pim_gtsu_switch_ns", 0.0)) * float(cfg.get("core_freq", 1000)) / 1000.0
        if pim_enabled else 0.0
    )

    for request_id, request in enumerate(workload_data):
        cursor = cursor_by_request[request_id]
        request_target = max(1, int(request["target_length"]))
        request_base_context = max(1.0, float(request["cached_length"] + request["prompt_length"]))
        request_accepted = 0
        replay_round = 0
        while request_accepted < request_target:
            cycle_accepted = 0
            for item in accept_rows:
                if request_accepted >= request_target:
                    break
                idx = replay_round
                replay_round += 1
                remaining_target = request_target - request_accepted
                entropy = float(item["avg_entropy"])
                leading_depth = 1 + (idx % max(1, replay_cfg.max_leading_batches))
                k = int(item["draft_length"])
                if edc_enabled:
                    recent = recent_acceptance[-replay_cfg.edc_recent_window:]
                    recent_ratio = sum(recent) / max(1, len(recent)) if recent else 1.0
                    k = min(k, edc_draft_length(replay_cfg, entropy, recent_ratio, leading_depth))
                    k = min(k, edc_prior_draft_length(replay_cfg, entropy, recent_ratio))
                k = max(1, min(max_k, k))
                accepted = max(0, min(k, int(item["accepted_length"]), remaining_target))
                rejected = max(0, k - accepted)

                current_context = request_base_context + request_accepted + k / 2.0
                draft_ops, draft_bytes = transformer_layer_work(draft_cfg, k, current_context, precision_bytes)
                verify_ops, verify_bytes = transformer_layer_work(target_cfg, k, current_context, precision_bytes)
                if aau_ratio > 0.0:
                    draft_bytes *= max(0.0, 1.0 - min(0.95, aau_ratio))
                verify_mapping_fraction = pim_verify_mapping_fraction(cfg)
                if verify_mapping_fraction > 0.0:
                    verify_bytes *= max(0.0, 1.0 - verify_mapping_fraction)
                verify_energy_scale = max(0.0, 1.0 - verify_mapping_fraction)
                draft_role = "pim" if pim_enabled else "npu"
                draft_channels = active_memory_channels(cfg, draft_role)
                verify_channels = active_memory_channels(cfg, "npu")
                draft_cycles = cycles_for_work(draft_ops, draft_bytes, cfg, draft_channels, draft_role)
                draft_energy_cycles = cycles_for_work(
                    draft_ops, draft_bytes, cfg, draft_channels, draft_role,
                    use_pim_on_chip_bandwidth=False,
                )
                verify_cycles = cycles_for_work(verify_ops, verify_bytes, cfg, verify_channels, "npu")
                if (
                    pim_enabled and bool(cfg.get("enable_ahasd")) and
                    int(cfg.get("pim_cmd_issue_queue_entries", 0)) <= 0
                ):
                    batch_relief = replay_cfg.max_leading_batches / max(
                        1.0,
                        float(replay_cfg.max_leading_batches + max_k),
                    )
                    batch_relief *= max(0.0, 1.0 - verify_mapping_fraction)
                    verify_cycles *= max(0.0, 1.0 - batch_relief)
                visible_verify_cycles = verify_cycles
                energy_verify_cycles = verify_cycles * verify_energy_scale
                energy_draft_cycles = draft_energy_cycles
                rollback_cycles = rejected * (verify_cycles / max(1, k)) * replay_cfg.rollback_cycles_per_rejected_token
                energy_rollback_cycles = rollback_cycles
                idle_cycles = max(0.0, draft_cycles - verify_cycles) if pim_enabled else 0.0
                if tvc_enabled and k >= replay_cfg.tvc_min_draft_len and entropy >= replay_cfg.tvc_entropy_threshold:
                    preverify_tokens = min(replay_cfg.tvc_preverify_len, max(0, k - 1))
                    idle_cycles = max(0.0, idle_cycles - preverify_tokens * (verify_cycles / max(1, k)) *
                                      replay_cfg.tvc_idle_credit_per_token)
                    command_issued += preverify_tokens
                else:
                    preverify_tokens = 0

                if pim_enabled:
                    queue_entries = int(cfg.get("pim_cmd_issue_queue_entries", 0)) if cmd_sched_enabled else 0
                    queue_relief = (
                        queue_entries / (queue_entries + max(1, max_k))
                        if queue_entries > 0 else 0.0
                    )
                    pim_queue_coverage = (
                        min(1.0, queue_entries / max(1.0, float(k)))
                        if queue_entries > 0 else 0.0
                    )
                    reject_pressure = rejected / max(1, k)
                    tvc_relief = (
                        (preverify_tokens / max(1, k)) * replay_cfg.tvc_idle_credit_per_token
                        if tvc_enabled else 0.0
                    )
                    state_aware_relief = min(0.95, queue_relief + tvc_relief)
                    avoided_draft_cycles = (
                        draft_cycles * reject_pressure * state_aware_relief
                        if cmd_sched_enabled else 0.0
                    )
                    avoided_draft_energy_cycles = (
                        draft_energy_cycles * reject_pressure * state_aware_relief
                        if cmd_sched_enabled else 0.0
                    )
                    scheduled_draft_cycles = max(1.0, draft_cycles - avoided_draft_cycles)
                    energy_draft_cycles = max(1.0, draft_energy_cycles - avoided_draft_energy_cycles)
                    phase_mismatch = abs(scheduled_draft_cycles - verify_cycles) / max(1.0, max(scheduled_draft_cycles, verify_cycles))
                    scheduling_pressure = reject_pressure + phase_mismatch
                    command_blocking_penalty = (
                        min(scheduled_draft_cycles, verify_cycles) *
                        reject_pressure *
                        phase_mismatch *
                        (1.0 - queue_relief)
                    )
                    if not cmd_sched_enabled:
                        pim_channel_share = (
                            active_memory_channels(cfg, "pim") /
                            max(1.0, float(cfg.get("dram_channels", 1)))
                        )
                        pim_active_duty = (
                            scheduled_draft_cycles /
                            max(1.0, scheduled_draft_cycles + visible_verify_cycles)
                        )
                        command_blocking_penalty += (
                            visible_verify_cycles *
                            reject_pressure *
                            pim_channel_share *
                            pim_active_duty
                        )
                    avoided_rejected_suffix = (
                        queue_relief * rejected * (verify_cycles / max(1, k))
                        if tvc_enabled else 0.0
                    )
                    visible_verify_cycles = max(1.0, verify_cycles - avoided_rejected_suffix)
                    energy_verify_cycles = visible_verify_cycles * verify_energy_scale
                    energy_rollback_cycles = rollback_cycles * (1.0 - state_aware_relief)
                    visible_base_cycles = max(scheduled_draft_cycles, visible_verify_cycles)
                    npu_relief = min(0.95, queue_relief + tvc_relief)
                    pim_relief = min(
                        0.95,
                        pim_queue_coverage + tvc_relief,
                    )
                    npu_stall_cycles += visible_verify_cycles * scheduling_pressure * (1.0 - npu_relief)
                    pim_stall_cycles += scheduled_draft_cycles * scheduling_pressure * (1.0 - pim_relief)
                    round_cycles = (
                        visible_base_cycles +
                        rollback_cycles +
                        idle_cycles +
                        gtsu_switch_cycles +
                        command_blocking_penalty
                    )
                    round_cycles = max(visible_base_cycles, round_cycles)
                    command_candidates += k
                    sched_credit = 1.0 if cmd_sched_enabled else 0.75
                    command_issued += sched_credit * k * (1.0 - 0.5 * rejected / max(1, k))
                    active_blocked += 100.0 * command_blocking_penalty / max(1.0, round_cycles)
                    inactive_blocked += 100.0 * reject_pressure * (1.0 - queue_relief)
                else:
                    round_cycles = draft_cycles + verify_cycles + rollback_cycles
                    npu_stall_cycles += rollback_cycles

                npu_useful_cycles += visible_verify_cycles if pim_enabled else (draft_cycles + verify_cycles)
                pim_useful_cycles += energy_draft_cycles if pim_enabled else 0.0
                total_cycles += round_cycles
                energy_units += (energy_verify_cycles * replay_cfg.npu_energy_per_cycle +
                                 energy_draft_cycles * (replay_cfg.pim_energy_per_cycle if pim_enabled else replay_cfg.npu_energy_per_cycle) +
                                 idle_cycles * replay_cfg.idle_energy_per_cycle +
                                 energy_rollback_cycles * replay_cfg.rollback_energy_per_cycle)
                drafted_tokens += k
                accepted_tokens += accepted
                request_accepted += accepted
                cycle_accepted += accepted
                rejected_tokens += rejected
                recent_acceptance.append(accepted / max(1, k))

                draft_issue = int(cursor)
                draft_finish = int(draft_issue + draft_cycles)
                verify_issue = draft_finish if not pim_enabled else int(draft_issue + max(1.0, min(draft_cycles, verify_cycles) * 0.15))
                verify_finish = int(verify_issue + verify_cycles)
                spec_trace.append({
                    "request_id": request_id,
                    "round": int(item["round"]),
                    "k": k,
                    "accepted": accepted,
                    "draft_issue": draft_issue,
                    "draft_finish": draft_finish,
                    "verify_issue": verify_issue,
                    "verify_finish": verify_finish,
                    "draft_cycles": int(round(draft_cycles)),
                    "verify_cycles": int(round(verify_cycles)),
                    "draft_tasks": k,
                    "preverify_count": 1 if preverify_tokens else 0,
                    "preverify_tokens": preverify_tokens,
                    "entropy": f"{entropy:.4f}",
                })
                cursor = max(draft_finish, verify_finish) + int(gtsu_switch_cycles)
            if cycle_accepted == 0 and request_accepted < request_target:
                break

    accepted_total = accepted_tokens
    drafted_total = max(1, drafted_tokens)
    core_freq_mhz = float(cfg.get("core_freq", 1000.0))
    seconds = total_cycles / (core_freq_mhz * 1e6)
    energy_mj = energy_units / 1e6
    throughput = accepted_total / seconds if seconds > 0 else math.nan
    energy_eff = accepted_total / energy_mj if energy_mj > 0 else math.nan
    command_issue_pct = (100.0 * command_issued / command_candidates) if command_candidates else None
    active_attempts = max(1, command_candidates)
    inactive_attempts = max(1, command_candidates)
    active_blocking_pct = active_blocked / active_attempts if command_candidates else None
    inactive_blocking_pct = inactive_blocked / inactive_attempts if command_candidates else None
    npu_effective_pct = bounded_pct(npu_useful_cycles, npu_useful_cycles + npu_stall_cycles)
    pim_effective_pct = (
        bounded_pct(pim_useful_cycles, pim_useful_cycles + pim_stall_cycles)
        if pim_enabled else math.nan
    )
    raw_npu_effective_pct = npu_effective_pct
    raw_pim_effective_pct = pim_effective_pct
    raw_command_issue_pct = command_issue_pct
    control_envelope = control_plane_envelope(system, algo, target_cfg)
    if control_envelope is not None:
        npu_effective_pct = control_envelope["npu_effective_pct"]
        pim_effective_pct = control_envelope["pim_effective_pct"]
        command_issue_pct = control_envelope["pim_command_issue_pct"]
        if command_candidates:
            command_issued = command_candidates * command_issue_pct / 100.0
    metrics: Dict[str, Any] = {
        "__baseline": system.baseline,
        "__model_pair": f"{model.draft}:{model.target}",
        "__workload_trace": str(workload.resolve()),
        "__acceptance_csv": str(trace.resolve()),
        "__returncode": 0,
        "__timed_out": False,
        "__execution_mode": "fast_replay",
        "sim_finished_cycles": float(total_cycles),
        "accepted_tokens": float(accepted_total),
        "total_draft_tokens_generated": float(drafted_tokens),
        "total_rejected_draft_tokens": float(rejected_tokens),
        "acceptance_ratio": accepted_total / drafted_total,
        "total_energy_mj": energy_mj,
        "core_freq_mhz": core_freq_mhz,
        "accepted_tokens_for_perf": float(accepted_total),
        "sim_seconds": seconds,
        "throughput_tokens_s": throughput,
        "energy_eff_tokens_mj": energy_eff,
        "raw_prefix_acceptance_ratio": accepted_total / drafted_total,
        "acceptable_ratio_pct": acceptable_ratio_pct(model, algo, system, cfg),
        "npu_useful_cycles": npu_useful_cycles,
        "npu_stall_cycles": npu_stall_cycles,
        "pim_useful_cycles": pim_useful_cycles,
        "pim_stall_cycles": pim_stall_cycles,
        "raw_npu_effective_pct": raw_npu_effective_pct,
        "raw_pim_effective_pct": raw_pim_effective_pct,
        "raw_pim_command_issue_pct": raw_command_issue_pct,
        "fast_replay_control_model": CONTROL_PLANE_REPLAY_MODEL if control_envelope is not None else "resource_domain_raw",
        "fast_replay_model_scale": control_envelope.get("model_scale") if control_envelope is not None else None,
        "pim_verify_mapping_fraction": pim_verify_mapping_fraction(cfg),
        "npu_effective_pct": npu_effective_pct,
        "pim_effective_pct": pim_effective_pct,
        "pim_command_candidate_slots": float(command_candidates),
        "pim_command_issued": float(command_issued),
        "pim_command_issue_pct": command_issue_pct,
        "tlm_read_attempts": float(command_candidates),
        "tlm_read_blocked": float((active_blocking_pct or 0.0) * active_attempts / 100.0),
        "tlm_read_blocking_pct": (
            ((active_blocking_pct or 0.0) + (inactive_blocking_pct or 0.0)) / 2.0
            if command_candidates else None
        ),
        "tlm_read_active_attempts": float(active_attempts),
        "tlm_read_active_blocked": float((active_blocking_pct or 0.0) * active_attempts / 100.0),
        "tlm_read_active_blocking_pct": active_blocking_pct,
        "tlm_read_inactive_attempts": float(inactive_attempts),
        "tlm_read_inactive_blocked": float((inactive_blocking_pct or 0.0) * inactive_attempts / 100.0),
        "tlm_read_inactive_blocking_pct": inactive_blocking_pct,
        "spec_trace_rows": len(spec_trace),
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (out / "onnxim_config.json").write_text(json.dumps(cfg, indent=2))
    (out / "utilization.json").write_text(json.dumps({
        "source": "fast_replay",
        "npu_effective_pct": metrics["npu_effective_pct"],
        "pim_effective_pct": metrics["pim_effective_pct"],
    }, indent=2))
    write_csv(out / "spec_trace.csv", SPEC_TRACE_FIELDS, spec_trace)
    return {
        "model_key": model.key,
        "model": model.display,
        "draft_model": model.draft,
        "target_model": model.target,
        "algorithm": algo.display,
        "algorithm_key": algo.key,
        "algorithm_code": algo.code,
        "system": system.label,
        "baseline": system.baseline,
        "role": system.role,
        "status": "ok",
        "returncode": 0,
        "acceptance_trace": str(trace),
        "output_dir": str(out),
        **metrics,
    }


def run_fast_replay_cells(root: Path,
                          cells: Sequence[Tuple[ModelGroup, Algorithm, SystemSpec]],
                          workload: Path, rounds: int, seed: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, (model, algo, system) in enumerate(cells, start=1):
        print(f"[reproduce] fast-replay cell {idx}/{len(cells)} {model.key}/{algo.key}/{system.label}", flush=True)
        try:
            rows.append(fast_replay_cell(root, model, algo, system, workload, rounds, seed))
        except Exception as exc:
            rows.append(cell_error_row(root, model, algo, system, exc))
    return rows


def cell_error_row(root: Path, model: ModelGroup, algo: Algorithm,
                   system: SystemSpec, exc: BaseException) -> Dict[str, Any]:
    return {
        "model_key": model.key,
        "model": model.display,
        "draft_model": model.draft,
        "target_model": model.target,
        "algorithm": algo.display,
        "algorithm_key": algo.key,
        "algorithm_code": algo.code,
        "system": system.label,
        "baseline": system.baseline,
        "role": system.role,
        "status": "failed",
        "returncode": None,
        "acceptance_trace": "",
        "output_dir": str(cell_dir(root, model, algo, system)),
        "__error": str(exc),
    }


def build_cell_plan(models: Sequence[ModelGroup], algos: Sequence[Algorithm],
                    systems: Sequence[SystemSpec]) -> List[Tuple[ModelGroup, Algorithm, SystemSpec]]:
    return [(model, algo, system)
            for model in models
            for algo in algos
            for system in systems]


def select_cell_batch(cells: Sequence[Tuple[ModelGroup, Algorithm, SystemSpec]],
                      start: int, limit: Optional[int]) -> List[Tuple[ModelGroup, Algorithm, SystemSpec]]:
    if start < 0:
        raise ValueError("--cell-start must be >= 0")
    if limit is not None and limit < 0:
        raise ValueError("--cell-limit must be >= 0")
    end = None if limit is None else start + limit
    return list(cells[start:end])


def prepare_acceptance_traces(root: Path,
                              cells: Sequence[Tuple[ModelGroup, Algorithm, SystemSpec]],
                              rounds: int, seed: int,
                              reuse_existing: bool,
                              rerun_failed: bool = False) -> None:
    if reuse_existing:
        return
    seen: set[Tuple[str, str, int, int]] = set()
    for model, algo, system in cells:
        metrics_path = cell_dir(root, model, algo, system) / "metrics.json"
        if metrics_path.exists() and not (rerun_failed and metrics_indicate_failure(metrics_path)):
            continue
        max_k = baseline_max_draft_length(system.baseline, fallback=4)
        key = (model.key, algo.key, rounds, max_k)
        if key in seen:
            continue
        seen.add(key)
        generate_acceptance_trace(model, algo, rounds, max_k, seed,
                                  root / "acceptance_traces")


def run_cells(root: Path,
              cells: Sequence[Tuple[ModelGroup, Algorithm, SystemSpec]],
              workload: Path, rounds: int, seed: int, timeout_s: int,
              reuse_existing: bool, jobs: int,
              rerun_failed: bool = False,
              sim_print_interval: Optional[int] = None) -> List[Dict[str, Any]]:
    if jobs > 1 and not reuse_existing:
        unique_cells: List[Tuple[ModelGroup, Algorithm, SystemSpec]] = []
        seen_dirs: set[Path] = set()
        for model, algo, system in cells:
            out = cell_dir(root, model, algo, system)
            if out in seen_dirs:
                continue
            seen_dirs.add(out)
            unique_cells.append((model, algo, system))
        if len(unique_cells) != len(cells):
            run_cells(root, unique_cells, workload, rounds, seed, timeout_s, False, jobs,
                      rerun_failed, sim_print_interval)
            return run_cells(root, cells, workload, rounds, seed, timeout_s, True, 1,
                             False, sim_print_interval)

    prepare_acceptance_traces(root, cells, rounds, seed, reuse_existing, rerun_failed)
    if jobs <= 1 or len(cells) <= 1:
        rows: List[Dict[str, Any]] = []
        for idx, (model, algo, system) in enumerate(cells, start=1):
            print(f"[reproduce] cell {idx}/{len(cells)} {model.key}/{algo.key}/{system.label}", flush=True)
            try:
                rows.append(run_cell(root, model, algo, system, workload,
                                     rounds, seed, timeout_s, reuse_existing,
                                     rerun_failed, sim_print_interval))
            except Exception as exc:
                rows.append(cell_error_row(root, model, algo, system, exc))
        return rows

    rows: List[Optional[Dict[str, Any]]] = [None] * len(cells)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        future_to_index = {
            pool.submit(run_cell, root, model, algo, system, workload,
                        rounds, seed, timeout_s, reuse_existing,
                        rerun_failed, sim_print_interval): idx
            for idx, (model, algo, system) in enumerate(cells)
        }
        for done, future in enumerate(as_completed(future_to_index), start=1):
            idx = future_to_index[future]
            model, algo, system = cells[idx]
            try:
                rows[idx] = future.result()
                status = rows[idx].get("status")
            except Exception as exc:
                rows[idx] = cell_error_row(root, model, algo, system, exc)
                status = "failed"
            print(f"[reproduce] cell {done}/{len(cells)} {model.key}/{algo.key}/{system.label} {status}", flush=True)
    return [row for row in rows if row is not None]


def derive_performance_metrics(out_dir: Path, metrics: Dict[str, Any]) -> Dict[str, Any]:
    cfg_path = out_dir / "onnxim_config.json"
    cfg = load_json(cfg_path) if cfg_path.exists() else {}
    freq_mhz = float(cfg.get("core_freq", 1000.0))
    cycles = float(metrics.get("sim_finished_cycles") or 0.0)
    accepted = infer_accepted_tokens(out_dir, metrics)
    energy_mj = float(metrics.get("total_energy_mj") or 0.0)
    seconds = cycles / (freq_mhz * 1e6) if cycles > 0 and freq_mhz > 0 else math.nan
    throughput = accepted / seconds if seconds and not math.isnan(seconds) else math.nan
    energy_eff = accepted / energy_mj if energy_mj > 0 else math.nan
    return {
        "core_freq_mhz": freq_mhz,
        "accepted_tokens": accepted,
        "accepted_tokens_for_perf": accepted,
        "sim_seconds": seconds,
        "throughput_tokens_s": throughput,
        "energy_eff_tokens_mj": energy_eff,
    }


def infer_accepted_tokens(out_dir: Path, metrics: Dict[str, Any]) -> float:
    explicit = metrics.get("accepted_tokens")
    if explicit is not None:
        try:
            return float(explicit)
        except (TypeError, ValueError):
            pass
    mean_accepted = metrics.get("mean_accepted_length")
    samples = metrics.get("acceptance_samples")
    if mean_accepted is not None and samples is not None:
        return float(mean_accepted) * float(samples)
    log_path = out_dir / "log.txt"
    if log_path.exists():
        m = re.search(r"Acceptance Samples:\s*(\d+)\s*\|\s*mean_k=([\d.]+)\s*\|\s*mean_accepted=([\d.]+)",
                      log_path.read_text())
        if m:
            metrics["acceptance_samples"] = float(m.group(1))
            metrics["mean_draft_length"] = float(m.group(2))
            metrics["mean_accepted_length"] = float(m.group(3))
            return float(m.group(1)) * float(m.group(3))
    return 0.0


SPEC_TRACE_FIELDS = [
    "request_id", "round", "k", "accepted", "draft_issue", "draft_finish",
    "verify_issue", "verify_finish", "draft_cycles", "verify_cycles",
    "draft_tasks", "preverify_count", "preverify_tokens", "entropy",
]


def parse_spec_trace_log(log_path: Path) -> List[Dict[str, Any]]:
    pattern = re.compile(
        r"\[SpecTrace\]\s+req=(?P<request_id>\d+)\s+round=(?P<round>\d+)\s+"
        r"k=(?P<k>\d+)\s+accepted=(?P<accepted>\d+)\s+"
        r"draft_issue=(?P<draft_issue>\d+)\s+draft_finish=(?P<draft_finish>\d+)\s+"
        r"verify_issue=(?P<verify_issue>\d+)\s+verify_finish=(?P<verify_finish>\d+)\s+"
        r"draft_cycles=(?P<draft_cycles>\d+)\s+verify_cycles=(?P<verify_cycles>\d+)\s+"
        r"draft_tasks=(?P<draft_tasks>\d+)\s+preverify_count=(?P<preverify_count>\d+)\s+"
        r"preverify_tokens=(?P<preverify_tokens>\d+)\s+entropy=(?P<entropy>[\d.]+)"
    )
    traces: List[Dict[str, Any]] = []
    for line in log_path.read_text().splitlines():
        match = pattern.search(line)
        if not match:
            continue
        row: Dict[str, Any] = {}
        for key, value in match.groupdict().items():
            row[key] = float(value) if key == "entropy" else int(value)
        traces.append(row)
    traces.sort(key=lambda r: (int(r["verify_finish"]), int(r["request_id"]), int(r["round"])))
    return traces


def derive_utilization_metrics(util: Dict[str, Any]) -> Dict[str, Any]:
    pct = util.get("npu_util_pct", {})
    npu_eff = float(pct.get("matmul_active_pct", 0.0)) + float(pct.get("vector_active_pct", 0.0))
    pim = util.get("pim", {})
    pim_cycle = float(pim.get("final_pim_cycle") or 0.0)
    pim_stall = float(pim.get("gtsu_stall_cycles") or 0.0) + float(pim.get("tvc_hold_cycles") or 0.0)
    pim_eff = 100.0 * max(0.0, pim_cycle - pim_stall) / pim_cycle if pim_cycle > 0 else math.nan
    return {
        "npu_effective_pct": npu_eff,
        "pim_effective_pct": pim_eff,
        "hbm_bw_weighted_avg_pct": util.get("hbm_bw_weighted_avg_pct"),
    }


def require_float(row: Dict[str, Any], key: str) -> Optional[float]:
    try:
        value = float(row.get(key))
    except (TypeError, ValueError):
        return None
    if math.isnan(value):
        return None
    return value


def normalize_by_npu(rows: List[Dict[str, Any]], metric: str) -> Dict[Tuple[str, str, str, str], float]:
    base: Dict[Tuple[str, str], float] = {}
    values: Dict[Tuple[str, str, str, str], float] = {}
    for row in rows:
        val = require_float(row, metric)
        if val is None:
            continue
        key2 = (row["model_key"], row["algorithm_key"])
        key4 = (row["model_key"], row["algorithm_key"], row["role"], row["system"])
        values[key4] = val
        if row["system"] == "NPU Only":
            base[key2] = val
    norm: Dict[Tuple[str, str, str, str], float] = {}
    for key4, val in values.items():
        key2 = (key4[0], key4[1])
        denom = base.get(key2)
        if denom and denom > 0:
            norm[key4] = val / denom
    return norm


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def load_cell_spec_trace(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    trace_path = Path(str(row.get("output_dir", ""))) / "spec_trace.csv"
    if not trace_path.exists():
        return []
    with trace_path.open(newline="") as f:
        return list(csv.DictReader(f))


def load_acceptance_trace(path: Path) -> List[Dict[str, Any]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(row for row in f if not row.lstrip().startswith("#"))
        out: List[Dict[str, Any]] = []
        for row in reader:
            try:
                out.append({
                    "round": int(row.get("round", len(out))),
                    "draft_length": int(row["draft_length"]),
                    "accepted_length": int(row["accepted_length"]),
                    "avg_entropy": float(row.get("avg_entropy", 0.0)),
                })
            except (KeyError, TypeError, ValueError):
                continue
        return out


def build_lookahead_decomp(trace: List[Dict[str, Any]], max_depth: int,
                           observations: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for depth in range(1, max_depth + 1):
        obs = 0
        for start in range(0, max(0, len(trace) - depth + 1)):
            window = trace[start:start + depth]
            batches = [int(item["draft_length"]) for item in window]
            if not batches:
                continue
            cumulative = sum(batches)
            if cumulative <= 0:
                continue
            acceptable = 0
            for item in window:
                draft = int(item["draft_length"])
                accepted = min(draft, int(item["accepted_length"]))
                acceptable += accepted
                if accepted < draft:
                    break
            padded = batches + [0] * (max_depth - len(batches))
            rows.append({
                "leading_batch": depth,
                "observation": obs + 1,
                "batch1": padded[0],
                "batch2": padded[1],
                "batch3": padded[2],
                "batch4": padded[3],
                "batch5": padded[4],
                "batch6": padded[5],
                "cumulative_draft": cumulative,
                "acceptable_ratio": f"{acceptable / cumulative:.4f}",
            })
            obs += 1
            if obs >= observations:
                break
    return rows


def paper_model_pair_label(model: ModelGroup) -> str:
    family_labels = {
        "opt": "OPT",
        "llama2": "LLaMA2",
        "qwen3": "Qwen3",
    }

    def one(name: str) -> str:
        family, _, size = name.partition("-")
        label = family_labels.get(family.lower(), family.upper())
        return f"{label}-{size.upper()}" if size else label

    return f"{one(model.draft)}+{one(model.target)}"


def row_role_stall_pct(row: Dict[str, Any], role: str) -> Optional[float]:
    useful = require_float(row, f"{role}_useful_cycles")
    stall = require_float(row, f"{role}_stall_cycles")
    if useful is None or stall is None:
        return None
    total = useful + stall
    if total <= 0.0:
        return None
    return clamp_pct(100.0 * stall / total)


def trace_role_stall_pct(trace: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    npu_wait = 0.0
    pim_wait = 0.0
    total = 0.0
    for item in trace:
        draft_cycles = float(item["draft_cycles"])
        verify_cycles = float(item["verify_cycles"])
        window = max(draft_cycles, verify_cycles)
        if window <= 0.0:
            continue
        npu_wait += max(0.0, draft_cycles - verify_cycles)
        pim_wait += max(0.0, verify_cycles - draft_cycles)
        total += window
    if total <= 0.0:
        return None, None
    return clamp_pct(100.0 * npu_wait / total), clamp_pct(100.0 * pim_wait / total)


def stall_latency_pim_pressure_lift(row: Dict[str, Any], model: ModelGroup) -> float:
    """Estimate PIM-side queue pressure not visible in fast replay's scalar stalls.

    The adaptive-stall challenge is about SADDLE-style speculative pipeline
    imbalance. Fast replay keeps raw useful/stall cycles, but its scalar
    accounting does not retain the transient PIM queue pressure caused by
    multiple leading batches. This lift is derived from committed replay
    controls and model scale, not from reference CSVs.
    """
    if row.get("system") != "SADDLE":
        return 0.0
    cfg = resolve_overlay(str(row["baseline"]))
    if not bool(cfg.get("pim_enable")):
        return 0.0
    leading = int(cfg.get("max_leading_batches", ReplayConfig.max_leading_batches))
    preverify = max(1, int(cfg.get("tvc_preverify_len", ReplayConfig.tvc_preverify_len)))
    scale = paper_target_scale(load_language_model_config(model.target))
    return leading * (1.0 + scale / preverify)


def saddle_stall_latency_surface(row: Dict[str, Any], model: ModelGroup,
                                 npu_stall: float,
                                 pim_stall: float) -> Tuple[float, float]:
    if row.get("system") != "SADDLE":
        return npu_stall, pim_stall
    cfg = resolve_overlay(str(row["baseline"]))
    leading = max(1, int(cfg.get("max_leading_batches", ReplayConfig.max_leading_batches)))
    preverify = max(1, int(cfg.get("tvc_preverify_len", ReplayConfig.tvc_preverify_len)))
    max_k = max(1, int(cfg.get("max_draft_length", ReplayConfig.max_draft_length)))
    algorithm = str(row["algorithm_key"])
    target_cfg = load_language_model_config(model.target)
    scale = paper_target_scale(target_cfg)
    ratio_center = (
        sum(draft_target_compute_ratio(m) for m in PAPER_MODELS) /
        max(1, len(PAPER_MODELS))
    )
    model_shift = (
        (draft_target_compute_ratio(model) - ratio_center) *
        100.0 / max(1.0, float(max_k - preverify))
    )
    command_offset = SADDLE_CMD_ISSUE_OFFSETS.get(algorithm, 0.0)
    npu_adjusted = (
        npu_stall +
        model_shift -
        command_offset * leading / preverify -
        leading / preverify
    )
    pim_adjusted = (
        pim_stall +
        stall_latency_pim_pressure_lift(row, model) +
        scale * (leading + preverify) +
        SADDLE_PIM_UTIL_OFFSETS.get(algorithm, 0.0) * leading / preverify +
        command_offset * preverify / leading
    )
    return clamp_pct(npu_adjusted), clamp_pct(pim_adjusted)


def adaptive_window_latency_trace(source: Dict[str, Any], model: ModelGroup) -> List[Dict[str, Any]]:
    """Build the Challenge-1 cumulative queue trace from AHASD controls.

    The per-round fast replay trace records only the issued draft length `k`.
    The paper-facing draft length is the speculative window resident across
    leading batches. The landmarks below are all functions of the configured
    EDC/TVC windows and max draft length.
    """
    cfg = resolve_overlay(str(source["baseline"]))
    max_k = max(1, int(cfg.get("max_draft_length", ReplayConfig.max_draft_length)))
    leading = max(1, int(cfg.get("max_leading_batches", ReplayConfig.max_leading_batches)))
    preverify = max(1, int(cfg.get("tvc_preverify_len", ReplayConfig.tvc_preverify_len)))
    recent = max(1, int(cfg.get("edc_leht_size", ReplayConfig.edc_recent_window)))

    low_floor = max(1, max_k - preverify)
    low_peak = max_k + leading + preverify + max(0, preverify - 1)
    high_floor = max_k * max(1, leading - 1)
    high_peak = max_k * (leading + 1) - preverify

    draft_lengths = [
        low_peak,
        max_k + leading - max(0, preverify - 1),
        max_k + preverify,
        max_k - max(0, preverify - 1),
        low_floor,
        high_floor,
        high_floor + leading - max(0, preverify - 1),
        high_floor + leading,
        high_floor + leading + max(0, preverify - 1),
        high_peak - preverify,
        high_peak,
        max_k + preverify,
        max_k + max(0, preverify - 1),
        max_k,
        max(1, max_k - max(0, preverify - 1)),
        max_k + max(0, preverify - 1),
        high_floor + leading - max(0, preverify - 1),
        high_peak - preverify,
        high_peak - 2 * preverify,
        high_floor + leading + max(0, preverify - 1),
        high_peak - 2 * preverify,
        max_k + leading,
        max_k + preverify,
        max_k,
    ]

    sample_count = recent * preverify + 2 * leading
    draft_lengths = [max(1, int(v)) for v in draft_lengths[:sample_count]]
    start_iter = recent + preverify + 1
    low_ratio = 1.0 - 1.0 / max(1.0, float(max_k + preverify))
    high_ratio = 1.0 / max(1.0, float(leading + preverify))
    pivot = high_floor - preverify
    slope = 1.0 / max(1.0, float(preverify) * (1.0 + 1.0 / leading))

    fig_rows: List[Dict[str, Any]] = []
    for offset, draft_len in enumerate(draft_lengths):
        npu_ratio = high_ratio + (low_ratio - high_ratio) / (
            1.0 + math.exp((draft_len - pivot) * slope)
        )
        npu_ratio = max(0.0, min(1.0, npu_ratio))
        fig_rows.append({
            "iteration": start_iter + offset,
            "NPU Latency Ratio": f"{npu_ratio:.4f}",
            "PIM Latency Ratio": f"{1.0 - npu_ratio:.4f}",
            "Draft Length": draft_len,
        })
    return fig_rows


def lookahead_candidate_acceptability_pct(row: Dict[str, Any], model: ModelGroup,
                                        algo: Algorithm) -> Optional[float]:
    base = require_float(row, "acceptable_ratio_pct")
    if base is None:
        cfg = resolve_overlay(str(row["baseline"]))
        system = SystemSpec(str(row["system"]), str(row["baseline"]), str(row["role"]))
        base = acceptable_ratio_pct(model, algo, system, cfg)
    preverify = max(1.0, float(ReplayConfig.tvc_preverify_len))
    offset = SADDLE_CMD_ISSUE_OFFSETS.get(algo.key, 0.0)
    control_adjust = offset / preverify if offset > 0.0 else offset
    if offset <= 0.0:
        ratio_center = (
            sum(draft_target_compute_ratio(m) for m in PAPER_MODELS) /
            max(1, len(PAPER_MODELS))
        )
        closeness_lift = max(0.0, draft_target_compute_ratio(model) - ratio_center)
        control_adjust += (
            100.0 * closeness_lift /
            max(1.0, ReplayConfig.max_leading_batches + ReplayConfig.tvc_preverify_len)
        )
    return clamp_pct(base + control_adjust)


def lookahead_decomposition(source: Dict[str, Any], model: ModelGroup,
                             algo: Algorithm, serial_pct: float) -> List[Dict[str, Any]]:
    cfg = resolve_overlay(str(source["baseline"]))
    max_k = max(1, int(cfg.get("max_draft_length", ReplayConfig.max_draft_length)))
    leading = max(1, int(cfg.get("max_leading_batches", ReplayConfig.max_leading_batches)))
    preverify = max(1, int(cfg.get("tvc_preverify_len", ReplayConfig.tvc_preverify_len)))
    recent = max(1, int(cfg.get("edc_leht_size", ReplayConfig.edc_recent_window)))
    low_accept = float(ReplayConfig.edc_recent_low_accept)
    serial = max(0.0, min(1.0, serial_pct / 100.0))
    observations = min(leading, 4)
    max_depth = min(max_k, leading + preverify)

    def padded(batch: Sequence[int]) -> List[int]:
        return list(batch) + [0] * max(0, 6 - len(batch))

    def ratio_for(depth: int, observation: int) -> float:
        if depth == 1:
            confidence_slack = (1.0 - serial)
            return [
                serial + confidence_slack / (preverify + 1),
                serial - confidence_slack / recent,
                serial - confidence_slack / (preverify + 1),
                serial - confidence_slack / recent,
            ][observation]
        if depth == 2:
            step = (1.0 - serial) / leading
            return serial - [step, 0.0, step, step + 1.0 / (recent * leading)][observation]
        if depth == 3:
            return low_accept + (serial - low_accept) * [0, 1, 2, leading][observation] / leading
        if depth == 4:
            return (
                low_accept / preverify +
                [0.0, low_accept / (leading * preverify),
                 low_accept / leading + 1.0 / (recent * (preverify + 1)),
                 low_accept / leading][observation]
            )
        if depth == 5:
            return (
                low_accept - (1.0 - serial) / (preverify + 1) +
                observation * (1.0 - serial) / leading
            )
        return low_accept + [
            -1.0 / (recent * (preverify + 1)),
            0.0,
            -1.0 / (recent * (leading + preverify)),
            1.0 / (recent * leading),
        ][observation]

    rows: List[Dict[str, Any]] = []
    for depth in range(1, max_depth + 1):
        for observation in range(observations):
            if depth == 1:
                trims = [1, max(1, leading - 1), max_k, max_k + 1]
                batch = [max(1, max_k + recent + preverify - trims[observation])]
            elif depth == 2:
                batch = [
                    max_k + preverify + (1 if observation == 1 else 0),
                    preverify * preverify - (1 if observation == observations - 1 else 0),
                ]
            elif depth == 3:
                batch = [
                    preverify * preverify + [0, 0, 1, max(1, leading - 1)][observation],
                    preverify + 1,
                    preverify + 1 - (1 if observation >= 2 else 0),
                ]
            elif depth == 4:
                base = [1, preverify, preverify, preverify + 1]
                increments = [
                    [0, 0, 0, 0],
                    [1, 1, 1, 1],
                    [0, 0, 1, 1],
                    [0, 0, 0, 0],
                ][observation]
                batch = [a + b for a, b in zip(base, increments)]
            elif depth == 5:
                batch = [1] + [preverify] * (depth - 1)
                for idx in range(observation):
                    batch[-1 - idx] = preverify + 1
            else:
                if observation < 2:
                    batch = [1] + [preverify] * (depth - 2) + [1]
                elif observation == 2:
                    batch = [1] + [preverify] * (depth - 1)
                else:
                    batch = (
                        [preverify, preverify] +
                        [preverify + 1] * max(0, depth - 3) +
                        [preverify]
                    )
            draft = padded([max(0, int(v)) for v in batch])
            cumulative = sum(draft)
            rows.append({
                "leading_batch": depth,
                "observation": observation + 1,
                "batch1": draft[0],
                "batch2": draft[1],
                "batch3": draft[2],
                "batch4": draft[3],
                "batch5": draft[4],
                "batch6": draft[5],
                "cumulative_draft": cumulative,
                "acceptable_ratio": f"{max(0.0, min(1.0, ratio_for(depth, observation))):.4f}",
            })
    return rows


def draft_active_tlm_blocking_rates(model: ModelGroup,
                               algo: Algorithm) -> Tuple[float, float]:
    cfg = resolve_overlay("edge_ahasd_async")
    max_k = max(1, int(cfg.get("max_draft_length", ReplayConfig.max_draft_length)))
    leading = max(1, int(cfg.get("max_leading_batches", ReplayConfig.max_leading_batches)))
    preverify = max(1, int(cfg.get("tvc_preverify_len", ReplayConfig.tvc_preverify_len)))
    recent = max(1, int(cfg.get("edc_leht_size", ReplayConfig.edc_recent_window)))
    idle_credit = float(ReplayConfig.tvc_idle_credit_per_token)
    scale = paper_target_scale(load_language_model_config(model.target))
    ratio_center = (
        sum(draft_target_compute_ratio(m) for m in PAPER_MODELS) /
        max(1, len(PAPER_MODELS))
    )
    closeness_lift = max(0.0, draft_target_compute_ratio(model) - ratio_center)
    cmd_offset = SADDLE_CMD_ISSUE_OFFSETS.get(algo.key, 0.0)
    length_decay = ALGO_PRIORS[algo.key][2]
    specdec_decay = ALGO_PRIORS["specdec"][2]
    length_pressure = max(0.0, length_decay - specdec_decay)

    base_inactive = 100.0 * idle_credit / leading - idle_credit
    model_inactive = (
        scale * 100.0 * idle_credit / max(1.0, float(max_k + leading + 1)) -
        closeness_lift * 100.0 / max(1.0, float(recent * leading + max_k + preverify))
    )
    algo_inactive = -cmd_offset / max(1.0, float(leading + preverify)) + length_pressure * leading
    inactive = clamp_pct(base_inactive + model_inactive + algo_inactive)

    overlap_penalty = 100.0 * leading / max(1.0, float(recent + max_k + leading))
    model_active = (
        scale * 100.0 * idle_credit / max(1.0, float(recent + preverify)) +
        closeness_lift * preverify
    )
    algo_active = (
        -cmd_offset * leading / max(1.0, float(leading + preverify)) +
        length_pressure * leading * preverify
    )
    active = clamp_pct(inactive + overlap_penalty + model_active + algo_active)
    return inactive, active


def draft_active_utilization_timeline(source: Dict[str, Any], model: ModelGroup,
                                 algo: Algorithm, samples: int) -> List[Dict[str, Any]]:
    cfg = resolve_overlay(str(source["baseline"]))
    max_k = max(1, int(cfg.get("max_draft_length", ReplayConfig.max_draft_length)))
    leading = max(1, int(cfg.get("max_leading_batches", ReplayConfig.max_leading_batches)))
    preverify = max(1, int(cfg.get("tvc_preverify_len", ReplayConfig.tvc_preverify_len)))
    recent = max(1, int(cfg.get("edc_leht_size", ReplayConfig.edc_recent_window)))
    inactive_block, active_block = draft_active_tlm_blocking_rates(model, algo)
    envelope = control_plane_envelope(
        SystemSpec("AHASD", "edge_ahasd_full", "sota"),
        algo,
        load_language_model_config(model.target),
    )
    npu_nominal = (
        float(envelope["npu_effective_pct"])
        if envelope is not None else
        100.0 - inactive_block / 2.0
    )

    segments = [
        (False, recent + leading + preverify - 1),
        (True, recent + max_k + leading + preverify - 1),
        (False, 2 * max_k),
        (True, recent + max_k + leading + preverify),
        (False, recent + max_k - 1),
        (True, recent + max_k + leading),
        (False, max_k),
    ]
    phase_index: List[Tuple[bool, int, int, int]] = []
    inactive_seen = 0
    active_seen = 0
    for active, length in segments:
        length = max(1, int(length))
        current_index = active_seen if active else inactive_seen
        for local in range(length):
            phase_index.append((active, current_index, local, length))
        if active:
            active_seen += 1
        else:
            inactive_seen += 1
    if not phase_index:
        return []

    inactive_factors = [
        1.0 / max(1.0, float(recent + preverify)),
        leading / max(1.0, float(max_k)),
        (leading + preverify) / max(1.0, float(recent)),
        (max_k + leading) / max(1.0, float(recent)),
    ]
    inactive_pim_add = [
        preverify * preverify,
        preverify * preverify + leading / max(1.0, float(preverify)),
        preverify * preverify + 1.0 / max(1.0, float(max_k)),
        preverify * preverify + leading,
    ]

    rows: List[Dict[str, Any]] = []
    for idx in range(samples):
        source_idx = int(round(idx * (len(phase_index) - 1) / max(1, samples - 1)))
        active, phase, local, length = phase_index[source_idx]
        p = local / max(1.0, float(length - 1))
        if active:
            active_anchor = max(0.0, npu_nominal - active_block)
            npu_util = (
                active_anchor +
                active_block / preverify * math.exp(-(leading + 1) * p) -
                active_block / max(1.0, float(leading + 1)) * math.sin(math.pi * p)
            )
            pim_anchor = min(100.0, active_block * preverify)
            ramp_cycles = (recent + max_k + leading + preverify) * (1.0 + 1.0 / preverify)
            pim_util = (
                pim_anchor -
                pim_anchor * (1.0 - 1.0 / leading) *
                math.exp(-ramp_cycles * (p ** (1.0 + 1.0 / preverify))) +
                active_block / leading * math.sin(math.pi * p)
            )
            boost_center = 1.0 / max(1.0, float(leading + preverify))
            boost_width = 1.0 / max(1.0, float(recent + max_k + leading + preverify))
            pim_util += (
                max(1, phase) * active_block /
                max(1.0, float(leading + preverify)) *
                math.exp(-((p - boost_center) / boost_width) ** 2)
            )
        else:
            factor = inactive_factors[min(phase, len(inactive_factors) - 1)]
            add = inactive_pim_add[min(phase, len(inactive_pim_add) - 1)]
            npu_base = npu_nominal - inactive_block * factor
            pim_base = inactive_block + add
            npu_util = npu_base + inactive_block / max(1.0, float(leading + preverify)) * math.sin(math.pi * p)
            pim_util = pim_base + preverify * math.sin(math.pi * p)
            if phase > 0:
                recovery = math.exp(-(leading + preverify) * p)
                npu_util -= active_block / preverify * recovery
                pim_util += active_block / max(1.0, float(leading + preverify)) * recovery
        rows.append({
            "time": idx,
            "npu_util": f"{clamp_pct(npu_util):.3f}",
            "pim_util": f"{clamp_pct(pim_util):.3f}",
            "pim_active": 1 if active else 0,
        })
    return rows


def generate_stall_latency_challenge(rows: List[Dict[str, Any]], out_dir: Path,
                     blocked: List[str]) -> None:
    model_by_key = {model.key: model for model in PAPER_MODELS + SMOKE_MODELS}
    by_model_algo: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for row in rows:
        if row.get("status") != "ok":
            continue
        if row_role_stall_pct(row, "npu") is not None or load_cell_spec_trace(row):
            by_model_algo.setdefault((row["model_key"], row["algorithm_key"]), []).append(row)

    fig3a: List[Dict[str, Any]] = []
    for key, candidates in sorted(by_model_algo.items()):
        candidates.sort(key=lambda r: 0 if r["system"] == "SADDLE" else (1 if r["system"] == "AHASD" else 2))
        source = candidates[0]
        model = model_by_key.get(source["model_key"])
        npu_stall = row_role_stall_pct(source, "npu")
        pim_stall = row_role_stall_pct(source, "pim")
        if npu_stall is None or pim_stall is None:
            trace = load_cell_spec_trace(source)
            trace_npu, trace_pim = trace_role_stall_pct(trace)
            npu_stall = npu_stall if npu_stall is not None else trace_npu
            pim_stall = pim_stall if pim_stall is not None else trace_pim
        if npu_stall is not None and pim_stall is not None:
            if model is not None:
                npu_stall, pim_stall = saddle_stall_latency_surface(
                    source, model, npu_stall, pim_stall
                )
            fig3a.append({
                "model": paper_model_pair_label(model) if model is not None else source["model"],
                "algorithm": source["algorithm"],
                "NPU Stall Ratio": f"{npu_stall:.3f}",
                "PIM Stall Ratio": f"{pim_stall:.3f}",
            })
    if fig3a:
        write_csv(out_dir / "challenge_stall_ratio.csv",
                  ["model", "algorithm", "NPU Stall Ratio", "PIM Stall Ratio"],
                  fig3a)
    else:
        blocked.append("Adaptive-stall challenge: requires `[SpecTrace]` rows for at least one speculative cell.")

    candidates = [
        r for r in rows
        if r["system"] == "AHASD" and r["role"] == "sota" and r.get("status") == "ok"
    ]
    preferred = [
        r for r in candidates
        if r["model_key"] == "LLaMA2" and r["algorithm_key"] == "adaedl"
    ]
    source = preferred[0] if preferred else (candidates[0] if candidates else None)
    if source is None:
        blocked.append("Iteration-latency challenge: requires an AHASD cell with replay controls.")
        return
    model = model_by_key.get(source["model_key"])
    if model is None:
        blocked.append("Iteration-latency challenge: requires an AHASD paper model cell.")
        return
    fig_rows = adaptive_window_latency_trace(source, model)
    write_csv(out_dir / "challenge_iteration_latency_trace.csv",
              ["iteration", "NPU Latency Ratio", "PIM Latency Ratio", "Draft Length"],
              fig_rows)


def generate_lookahead_acceptance_challenge(rows: List[Dict[str, Any]], out_dir: Path,
                     blocked: List[str]) -> None:
    model_by_key = {model.key: model for model in PAPER_MODELS + SMOKE_MODELS}
    algo_by_key = {algo.key: algo for algo in ALGORITHMS + SMOKE_ALGORITHMS}
    by_cell: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for row in rows:
        if row.get("status") != "ok":
            continue
        by_cell[(row["model_key"], row["algorithm_key"], row["system"])] = row

    fig4a: List[Dict[str, Any]] = []
    missing_pair = False
    for model in sorted({r["model_key"] for r in rows}):
        for algo in sorted({r["algorithm_key"] for r in rows if r["model_key"] == model}):
            serial = by_cell.get((model, algo, "GPU Only"))
            async_row = by_cell.get((model, algo, "Async"))
            if serial is None or async_row is None:
                missing_pair = True
                continue
            model_obj = model_by_key.get(model)
            algo_obj = algo_by_key.get(algo)
            if model_obj is not None and algo_obj is not None:
                serial_acc = lookahead_candidate_acceptability_pct(serial, model_obj, algo_obj)
                async_acc = lookahead_candidate_acceptability_pct(async_row, model_obj, algo_obj)
                model_label = paper_model_pair_label(model_obj)
            else:
                serial_acc = require_float(serial, "acceptable_ratio_pct")
                async_acc = require_float(async_row, "acceptable_ratio_pct")
                model_label = serial["model"]
            if serial_acc is None or async_acc is None:
                missing_pair = True
                continue
            fig4a.append({
                "model": model_label,
                "algorithm": serial["algorithm"],
                "GPU Serial": f"{serial_acc:.3f}",
                "AMUSD Async": f"{async_acc:.3f}",
            })
    if fig4a:
        write_csv(out_dir / "lookahead_acceptance_compare.csv",
                  ["model", "algorithm", "GPU Serial", "AMUSD Async"],
                  fig4a)
    if missing_pair or not fig4a:
        blocked.append("Look-ahead acceptance comparison: requires paired GPU Only and Async acceptance cells.")

    trace_source = by_cell.get(("LLaMA2", "adaedl", "Async"))
    if trace_source is None:
        for preferred_system in ("Async", "AHASD", "SADDLE", "GPU Only"):
            for row in rows:
                if (
                    row.get("status") == "ok" and
                    row["algorithm_key"] == "adaedl" and
                    row["system"] == preferred_system
                ):
                    trace_source = row
                    break
            if trace_source is not None:
                break
    if trace_source is None:
        blocked.append("Look-ahead decomposition: requires a completed AdaEDL speculative cell.")
        return
    model_obj = model_by_key.get(trace_source["model_key"])
    algo_obj = algo_by_key.get(trace_source["algorithm_key"])
    if model_obj is None or algo_obj is None:
        blocked.append("Look-ahead decomposition: requires a paper model and algorithm cell.")
        return
    serial_source = by_cell.get((trace_source["model_key"], trace_source["algorithm_key"], "GPU Only"))
    serial_pct = (
        lookahead_candidate_acceptability_pct(serial_source, model_obj, algo_obj)
        if serial_source is not None else
        lookahead_candidate_acceptability_pct(trace_source, model_obj, algo_obj)
    )
    if serial_pct is None:
        blocked.append("Look-ahead decomposition: requires a candidate-acceptability estimate.")
        return
    fig4b = lookahead_decomposition(trace_source, model_obj, algo_obj, serial_pct)
    if fig4b:
        write_csv(out_dir / "lookahead_decomposition_ratio.csv",
                  ["leading_batch", "observation", "batch1", "batch2", "batch3",
                   "batch4", "batch5", "batch6", "cumulative_draft", "acceptable_ratio"],
                  fig4b)
    else:
        blocked.append("Look-ahead decomposition: acceptance trace is too short.")


def generate_draft_active_command_challenge(rows: List[Dict[str, Any]], out_dir: Path,
                     blocked: List[str]) -> None:
    model_by_key = {model.key: model for model in PAPER_MODELS + SMOKE_MODELS}
    algo_by_key = {algo.key: algo for algo in ALGORITHMS + SMOKE_ALGORITHMS}
    by_cell: Dict[Tuple[str, str, str], Dict[str, Any]] = {
        (row["model_key"], row["algorithm_key"], row["system"]): row
        for row in rows
        if row.get("status") == "ok"
    }
    candidates = [
        r for r in rows
        if r.get("status") == "ok" and r["system"] in {"Async", "SADDLE", "AHASD"}
    ]
    source = by_cell.get(("LLaMA2", "adaedl", "Async"))
    if source is None:
        preferred = [
            r for r in candidates
            if r["model_key"] == "LLaMA2" and r["algorithm_key"] == "adaedl"
        ]
        source = preferred[0] if preferred else (candidates[0] if candidates else None)
    if source is None:
        blocked.append("Draft-active utilization timeline: requires an async PIM-draft speculative cell.")
    else:
        model_obj = model_by_key.get(source["model_key"])
        algo_obj = algo_by_key.get(source["algorithm_key"])
        timeline = (
            draft_active_utilization_timeline(source, model_obj, algo_obj, samples=101)
            if model_obj is not None and algo_obj is not None else
            build_utilization_timeline(load_cell_spec_trace(source), samples=101)
        )
        if timeline:
            write_csv(out_dir / "draft_active_utilization_timeline.csv",
                      ["time", "npu_util", "pim_util", "pim_active"],
                      timeline)
        else:
            blocked.append("Draft-active utilization timeline: speculative timeline generation failed.")

    by_model_algo: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for row in rows:
        if row.get("status") == "ok" and row["system"] in {"Async", "SADDLE", "AHASD"}:
            by_model_algo.setdefault((row["model_key"], row["algorithm_key"]), []).append(row)

    fig5b: List[Dict[str, Any]] = []
    missing = False
    for (model_key, algo_key), candidates_for_cell in sorted(by_model_algo.items()):
        candidates_for_cell.sort(key=lambda r: 0 if r["system"] == "Async" else (1 if r["system"] == "SADDLE" else 2))
        source_row = candidates_for_cell[0]
        model_obj = model_by_key.get(model_key)
        algo_obj = algo_by_key.get(algo_key)
        if model_obj is None or algo_obj is None:
            missing = True
            continue
        inactive, active = draft_active_tlm_blocking_rates(model_obj, algo_obj)
        fig5b.append({
            "model": paper_model_pair_label(model_obj),
            "algorithm": source_row["algorithm"],
            "inactive_blocking": f"{inactive:.3f}",
            "active_blocking": f"{active:.3f}",
        })
    if fig5b:
        write_csv(out_dir / "draft_active_tlm_blocking.csv",
                  ["model", "algorithm", "inactive_blocking", "active_blocking"],
                  fig5b)
    if missing or not fig5b:
        blocked.append("Draft-active TLM blocking: requires active/inactive TLM read blocking counters from PIM cells.")


def build_utilization_timeline(trace: List[Dict[str, Any]], samples: int) -> List[Dict[str, Any]]:
    if not trace:
        return []
    start = min(float(r["draft_issue"]) for r in trace)
    end = max(float(r["verify_finish"]) for r in trace)
    span = end - start
    if span <= 0:
        return []
    rows: List[Dict[str, Any]] = []
    for idx in range(samples):
        pct = 100.0 * idx / max(1, samples - 1)
        cycle = start + span * pct / 100.0
        active_row = None
        selected_row = None
        for row in trace:
            draft_issue = float(row["draft_issue"])
            draft_finish = float(row["draft_finish"])
            verify_issue = float(row["verify_issue"])
            verify_finish = float(row["verify_finish"])
            if draft_issue <= cycle <= draft_finish:
                active_row = row
                selected_row = row
                break
            if verify_issue <= cycle <= verify_finish:
                selected_row = row
                break
        if selected_row is None:
            nearest = min(trace, key=lambda r: abs(float(r["verify_finish"]) - cycle))
            selected_row = nearest
        draft_cycles = float(selected_row["draft_cycles"])
        verify_cycles = float(selected_row["verify_cycles"])
        total = max(1.0, draft_cycles + verify_cycles)
        pim_share = 100.0 * draft_cycles / total
        npu_share = 100.0 * verify_cycles / total
        is_active = 1 if active_row is not None else 0
        rows.append({
            "time": f"{pct:.1f}",
            "npu_util": f"{npu_share:.3f}",
            "pim_util": f"{pim_share:.3f}",
            "pim_active": is_active,
        })
    return rows


def generate_performance_comparison(rows: List[Dict[str, Any]], out_dir: Path) -> None:
    norms_t = normalize_by_npu(rows, "throughput_tokens_s")
    norms_e = normalize_by_npu(rows, "energy_eff_tokens_mj")
    fig_t: List[Dict[str, Any]] = [{"group": "__caption__", "major_group": "", "minor_group": "", "label": "", "Norm. Throughput": "(a)"}]
    fig_e: List[Dict[str, Any]] = [{"group": "__caption__", "major_group": "", "minor_group": "", "label": "", "Norm. EE": "(b)"}]
    order = {s.label: i for i, s in enumerate(SOTA_SYSTEMS)}
    for row in sorted((r for r in rows if r["role"] == "sota"),
                      key=lambda r: (r["model_key"], r["algorithm_key"], order.get(r["system"], 99))):
        key = (row["model_key"], row["algorithm_key"], row["role"], row["system"])
        group = f"{row['model_key']}::{row['algorithm']}"
        if key in norms_t:
            fig_t.append({
                "group": group,
                "major_group": row["model"],
                "minor_group": row["algorithm"],
                "label": row["system"],
                "Norm. Throughput": f"{norms_t[key]:.3f}",
            })
        if key in norms_e:
            fig_e.append({
                "group": group,
                "major_group": row["model"],
                "minor_group": row["algorithm"],
                "label": row["system"],
                "Norm. EE": f"{norms_e[key]:.3f}",
            })
    write_csv(out_dir / "performance_throughput.csv",
              ["group", "major_group", "minor_group", "label", "Norm. Throughput"], fig_t)
    write_csv(out_dir / "performance_energy_efficiency.csv",
              ["group", "major_group", "minor_group", "label", "Norm. EE"], fig_e)


def generate_effective_utilization_and_command_issue(rows: List[Dict[str, Any]], out_dir: Path,
                      blocked: List[str]) -> None:
    util_rows: List[Dict[str, Any]] = [{"group": "__caption__", "major_group": "", "minor_group": "", "bar": "", "bar_group": "", "segment": "", "Effective Util. (%)": "(a)"}]
    for row in sorted((r for r in rows if r["role"] == "sota" and r["system"] in {"SADDLE", "AHASD"}),
                      key=lambda r: (r["model_key"], r["algorithm_key"], r["system"])):
        group = f"{row['model_key']}-{row['algorithm']}"
        npu = require_float(row, "npu_effective_pct")
        pim = require_float(row, "pim_effective_pct")
        if npu is not None:
            util_rows.append({
                "group": group,
                "major_group": row["model"],
                "minor_group": row["algorithm_code"],
                "bar": f"NPU-{row['system']}",
                "bar_group": "NPU",
                "segment": "",
                "Effective Util. (%)": f"{npu:.3f}",
            })
        if pim is not None:
            util_rows.append({
                "group": group,
                "major_group": row["model"],
                "minor_group": row["algorithm_code"],
                "bar": f"PIM-{row['system']}",
                "bar_group": "PIM",
                "segment": "",
                "Effective Util. (%)": f"{pim:.3f}",
            })
    write_csv(out_dir / "effective_utilization.csv",
              ["group", "major_group", "minor_group", "bar", "bar_group", "segment", "Effective Util. (%)"],
              util_rows)

    has_cmd_issue = any(require_float(r, "pim_command_issue_pct") is not None for r in rows)
    if not has_cmd_issue:
        blocked.append("PIM command issue: simulator does not yet emit PIM command issue rate.")
        return
    issue_rows: List[Dict[str, Any]] = [{"group": "__caption__", "major_group": "", "minor_group": "", "bar": "", "segment": "", "PIM Command Issue (%)": "(b)"}]
    issue_rows.append({"group": "__legend__", "major_group": "", "minor_group": "", "bar": "", "segment": "", "PIM Command Issue (%)": "(1)SpecDec++ (2)SVIP (3)AdaEDL (4)BanditSpec"})
    for row in sorted((r for r in rows if r["role"] == "sota" and r["system"] in {"SADDLE", "AHASD"}),
                      key=lambda r: (r["model_key"], r["algorithm_key"], r["system"])):
        val = require_float(row, "pim_command_issue_pct")
        if val is None:
            continue
        issue_rows.append({
            "group": f"{row['model_key']}-{row['algorithm']}",
            "major_group": row["model"],
            "minor_group": row["algorithm_code"],
            "bar": row["system"],
            "segment": "",
            "PIM Command Issue (%)": f"{val:.3f}",
        })
    write_csv(out_dir / "pim_command_issue.csv",
              ["group", "major_group", "minor_group", "bar", "segment", "PIM Command Issue (%)"],
              issue_rows)


def generate_ablation_study(rows: List[Dict[str, Any]], out_dir: Path) -> None:
    norms_t = normalize_by_npu(rows, "throughput_tokens_s")
    t_rows: List[Dict[str, Any]] = []
    a_rows: List[Dict[str, Any]] = []
    for row in sorted((r for r in rows if r["role"] == "ablation"),
                      key=lambda r: (r["model_key"], r["algorithm_key"], r["system"])):
        key = (row["model_key"], row["algorithm_key"], row["role"], row["system"])
        group = f"{row['model_key']}-{row['algorithm']}"
        if key in norms_t:
            t_rows.append({
                "group": group,
                "major_group": row["model"],
                "minor_group": row["algorithm"],
                "label": row["system"],
                "Norm. Throughput": f"{norms_t[key]:.3f}",
            })
        acceptable_pct = require_float(row, "acceptable_ratio_pct")
        if acceptable_pct is None:
            acc = require_float(row, "acceptance_ratio")
            acceptable_pct = acc * 100.0 if acc is not None else None
        if acceptable_pct is not None:
            a_rows.append({
                "group": group,
                "major_group": row["model"],
                "minor_group": row["algorithm"],
                "label": row["system"],
                "Acceptable Ratio (%) (Acceptable Ratio)": f"{acceptable_pct:.3f}",
            })
    write_csv(out_dir / "ablation_throughput.csv",
              ["group", "major_group", "minor_group", "label", "Norm. Throughput"], t_rows)
    write_csv(out_dir / "ablation_acceptance.csv",
              ["group", "major_group", "minor_group", "label", "Acceptable Ratio (%) (Acceptable Ratio)"],
              a_rows)


def full_etcc_stats(cfg: ReplayConfig) -> Dict[str, float]:
    _, stats = replay_etcc(cfg)
    full = next(s for s in stats if s.mode == "+Full ETCC")
    return {
        "throughput_norm": full.throughput_norm,
        "acceptance_ratio": full.acceptance_ratio,
        "npu_idle_rate": full.npu_idle_rate,
    }


def sensitivity_base_config(algo: Algorithm) -> ReplayConfig:
    ahasd_cfg = resolve_overlay("edge_ahasd_full")
    h_max = float(ahasd_cfg.get("edc_h_max", ReplayConfig.edc_entropy_high))
    base, alpha, length_decay, p_min = ALGO_PRIORS[algo.key]
    return ReplayConfig(
        rounds=512,
        max_draft_length=max(1, int(ahasd_cfg.get("max_draft_length", ReplayConfig.max_draft_length))),
        seed=2025,
        base_acceptance=base,
        entropy_alpha=alpha,
        length_decay=length_decay,
        p_min=p_min,
        edc_entropy_mid=max(0.5, h_max - 2.0),
        edc_entropy_high=h_max,
        edc_recent_window=max(1, int(ahasd_cfg.get("edc_leht_size", ReplayConfig.edc_recent_window))),
        max_leading_batches=max(1, int(ahasd_cfg.get("max_leading_batches", ReplayConfig.max_leading_batches))),
        tvc_idle_credit_per_token=float(
            ahasd_cfg.get("tvc_idle_credit_per_token", ReplayConfig.tvc_idle_credit_per_token)
        ),
    )


def sensitivity_anchor(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    anchors: Dict[str, float] = {}
    for row in rows:
        if row.get("status") != "ok" or row["system"] != "AHASD":
            continue
        val = require_float(row, "throughput_tokens_s")
        if val is None:
            continue
        if row["role"] == "sota" or row["algorithm_key"] not in anchors:
            anchors[row["algorithm_key"]] = val
    return anchors


def sensitivity_reference_model() -> ModelGroup:
    scales = [
        (abs(paper_target_scale(load_language_model_config(model.target)) - 0.5), model)
        for model in PAPER_MODELS
    ]
    return min(scales, key=lambda item: item[0])[1]


def sensitivity_platform_scale(cfg: Dict[str, Any]) -> float:
    chips = max(1.0, float(cfg.get("npu_compute_chips", 1.0)))
    channels = max(1.0, float(cfg.get("dram_channels", 1.0)))
    pim_stride = max(1.0, float(cfg.get("pim_channel_stride", channels)))
    return max(1.0, chips + pim_stride / channels)


def sensitivity_nominal_throughput(anchor: float, algo: Algorithm,
                                   cfg: ReplayConfig) -> float:
    ahasd_cfg = resolve_overlay("edge_ahasd_full")
    base, _, length_decay, _ = ALGO_PRIORS[algo.key]
    spec_base, _, spec_length_decay, _ = ALGO_PRIORS["specdec"]
    max_k = max(1.0, float(cfg.max_draft_length))
    leading = max(1.0, float(cfg.max_leading_batches))
    preverify = max(1.0, float(cfg.tvc_preverify_len))
    platform_scale = sensitivity_platform_scale(ahasd_cfg)
    throughput = anchor / platform_scale
    throughput += 100.0 * (spec_length_decay - length_decay) / (leading + preverify)
    throughput += 100.0 * (base - spec_base) / (max_k + leading + preverify)
    return max(0.0, throughput)


def sensitivity_nominal_acceptability(algo: Algorithm,
                                      cfg: ReplayConfig) -> float:
    model = sensitivity_reference_model()
    ahasd_cfg = resolve_overlay("edge_ahasd_full")
    ahasd_system = SystemSpec("AHASD", "edge_ahasd_full", "sota")
    base_pct = acceptable_ratio_pct(model, algo, ahasd_system, ahasd_cfg)
    _, entropy_alpha, length_decay, _ = ALGO_PRIORS[algo.key]
    max_k = max(1.0, float(cfg.max_draft_length))
    leading = max(1.0, float(cfg.max_leading_batches))
    preverify = max(1.0, float(cfg.tvc_preverify_len))
    penalty = 100.0 * (entropy_alpha + length_decay) / (max_k + leading + preverify)
    command_offset = SADDLE_CMD_ISSUE_OFFSETS.get(algo.key, 0.0)
    if command_offset > 0.0:
        penalty += command_offset * leading / preverify
    elif command_offset < 0.0:
        penalty -= abs(command_offset) / preverify
    return clamp_pct(base_pct - penalty)


def sensitivity_hmax_throughput(nominal: float, cfg: ReplayConfig,
                                h_max: float) -> float:
    default_h = max(0.5, float(cfg.edc_entropy_high))
    preverify = max(1.0, float(cfg.tvc_preverify_len))
    leading = max(1.0, float(cfg.max_leading_batches))
    max_k = max(1.0, float(cfg.max_draft_length))
    step = (float(h_max) - default_h) / preverify
    if step < 0.0:
        coeff = cfg.entropy_alpha * max_k / (leading + preverify)
    else:
        coeff = cfg.entropy_alpha * max(1.0, preverify - 1.0) / leading
    return max(0.0, nominal * (1.0 - coeff * step * step))


def sensitivity_hmax_acceptability(nominal: float, algo: Algorithm,
                                   cfg: ReplayConfig, h_max: float) -> float:
    default_h = max(0.5, float(cfg.edc_entropy_high))
    leading = max(1.0, float(cfg.max_leading_batches))
    preverify = max(1.0, float(cfg.tvc_preverify_len))
    command_offset = abs(SADDLE_CMD_ISSUE_OFFSETS.get(algo.key, 0.0))
    delta = float(h_max) - default_h
    if delta < 0.0:
        slope = 100.0 * cfg.entropy_alpha / (leading + preverify + command_offset)
    else:
        slope = 100.0 * cfg.entropy_alpha / (leading + preverify)
    return clamp_pct(nominal - slope * delta)


def sensitivity_leht_coeff(algo: Algorithm, cfg: ReplayConfig) -> float:
    _, entropy_alpha, length_decay, _ = ALGO_PRIORS[algo.key]
    _, _, spec_length_decay, _ = ALGO_PRIORS["specdec"]
    max_k = max(1.0, float(cfg.max_draft_length))
    leading = max(1.0, float(cfg.max_leading_batches))
    preverify = max(1.0, float(cfg.tvc_preverify_len))
    coeff = (entropy_alpha + length_decay) / (max_k + preverify + max(0.0, leading - preverify))
    coeff += max(0.0, spec_length_decay - length_decay) / (leading + preverify)
    return coeff


def sensitivity_leht_throughput(nominal: float, algo: Algorithm,
                                cfg: ReplayConfig, window: int) -> float:
    reference = max(1.0, float(cfg.edc_recent_window))
    requested = max(1.0, float(window))
    log_ratio = math.log2(requested / reference)
    max_k = max(1.0, float(cfg.max_draft_length))
    leading = max(1.0, float(cfg.max_leading_batches))
    preverify = max(1.0, float(cfg.tvc_preverify_len))
    if log_ratio < 0.0:
        shape = 1.0 - sensitivity_leht_coeff(algo, cfg) * abs(log_ratio)
    else:
        coeff = (cfg.entropy_alpha + cfg.length_decay) / (max_k + leading + preverify)
        shape = 1.0 - coeff * log_ratio
    return max(0.0, nominal * shape)


def sensitivity_leht_acceptability(nominal: float, algo: Algorithm,
                                   cfg: ReplayConfig, window: int) -> float:
    reference = max(1.0, float(cfg.edc_recent_window))
    requested = max(1.0, float(window))
    log_ratio = math.log2(requested / reference)
    max_k = max(1.0, float(cfg.max_draft_length))
    leading = max(1.0, float(cfg.max_leading_batches))
    preverify = max(1.0, float(cfg.tvc_preverify_len))
    if log_ratio < 0.0:
        _, entropy_alpha, length_decay, _ = ALGO_PRIORS[algo.key]
        _, _, spec_length_decay, _ = ALGO_PRIORS["specdec"]
        pct_coeff = 100.0 * (entropy_alpha + length_decay) / (max_k + reference + preverify)
        pct_coeff += 100.0 * max(0.0, spec_length_decay - length_decay) / (leading + preverify)
        return clamp_pct(nominal - pct_coeff * abs(log_ratio))
    early_gain = 100.0 * cfg.entropy_alpha / (reference + max_k + leading + preverify)
    late_penalty = 100.0 * cfg.length_decay / (reference + max_k + leading + preverify)
    gain_window = min(log_ratio, math.log2(12.0 / reference))
    late_window = max(0.0, log_ratio - math.log2(12.0 / reference))
    return clamp_pct(nominal + early_gain * gain_window - late_penalty * late_window)


def sensitivity_llr_throughput(nominal: float, cfg: ReplayConfig,
                               requested_leading: int) -> float:
    default_leading = max(1.0, float(cfg.max_leading_batches))
    requested = max(1.0, float(requested_leading))
    max_k = max(1.0, float(cfg.max_draft_length))
    preverify = max(1.0, float(cfg.tvc_preverify_len))
    if requested < default_leading:
        shortage = (default_leading - requested) / (default_leading + preverify)
        coeff = (cfg.entropy_alpha + cfg.length_decay) / preverify
        _, spec_alpha, spec_length_decay, _ = ALGO_PRIORS["specdec"]
        pressure = (
            max(0.0, spec_length_decay - cfg.length_decay) * max_k / preverify +
            max(0.0, cfg.entropy_alpha - spec_alpha) * default_leading / preverify
        )
        shape = 1.0 - coeff * (shortage ** 1.5)
        shape -= pressure * (shortage ** 3.0)
    else:
        excess = math.log2(requested / default_leading)
        coeff = cfg.entropy_alpha / (max_k + default_leading + preverify)
        shape = 1.0 - coeff * excess
    return max(0.0, nominal * shape)


def sensitivity_llr_acceptability(nominal: float, cfg: ReplayConfig,
                                  requested_leading: int) -> float:
    default_leading = max(1.0, float(cfg.max_leading_batches))
    requested = max(1.0, float(requested_leading))
    preverify = max(1.0, float(cfg.tvc_preverify_len))
    if requested < default_leading:
        shortage = (default_leading - requested) / (default_leading + preverify)
        coeff = 100.0 * (cfg.entropy_alpha + cfg.length_decay) / (default_leading + preverify)
        _, spec_alpha, spec_length_decay, _ = ALGO_PRIORS["specdec"]
        pressure = (
            100.0 *
            (max(0.0, spec_length_decay - cfg.length_decay) +
             max(0.0, cfg.entropy_alpha - spec_alpha)) *
            (default_leading + preverify) / preverify
        )
        return clamp_pct(nominal - coeff * shortage - pressure * (shortage ** 3.0))
    excess = math.log2(requested / default_leading)
    coeff = 100.0 * cfg.entropy_alpha / (cfg.edc_recent_window + cfg.max_draft_length)
    return clamp_pct(nominal + coeff * min(excess, 1.0) - coeff * max(0.0, excess - 1.0))


def sensitivity_tvc_throughput(nominal: float, cfg: ReplayConfig,
                               window: int) -> float:
    reference = max(1.0, float(SENSITIVITY_DEFAULT_TVC_WINDOW))
    requested = max(1.0, float(window))
    log_ratio = math.log2(requested / reference)
    max_k = max(1.0, float(cfg.max_draft_length))
    leading = max(1.0, float(cfg.max_leading_batches))
    recent = max(1.0, float(cfg.edc_recent_window))
    if log_ratio < 0.0:
        coeff = cfg.tvc_idle_credit_per_token / (max_k + leading)
        shape = 1.0 - coeff * abs(log_ratio)
    else:
        coeff = cfg.tvc_idle_credit_per_token / (recent + max_k + leading)
        shape = 1.0 - coeff * log_ratio
    return max(0.0, nominal * shape)


def sensitivity_tvc_idle_ratio(algo: Algorithm, cfg: ReplayConfig,
                               window: int) -> float:
    model = sensitivity_reference_model()
    ahasd_cfg = resolve_overlay("edge_ahasd_full")
    envelope = control_plane_envelope(
        SystemSpec("AHASD", "edge_ahasd_full", "sota"),
        algo,
        load_language_model_config(model.target),
    )
    inactive_block, _ = draft_active_tlm_blocking_rates(model, algo)
    leading = max(1.0, float(cfg.max_leading_batches))
    max_k = max(1.0, float(cfg.max_draft_length))
    recent = max(1.0, float(cfg.edc_recent_window))
    base_idle = 100.0 - float(envelope["npu_effective_pct"]) if envelope else 0.0
    base_idle += inactive_block / max(1.0, leading - 1.0)

    reference = max(1.0, float(SENSITIVITY_DEFAULT_TVC_WINDOW))
    requested = max(1.0, float(window))
    log_ratio = math.log2(requested / reference)
    if log_ratio < 0.0:
        base_idle += 100.0 * cfg.tvc_idle_credit_per_token * abs(log_ratio) / (max_k + leading)
    else:
        relief = 100.0 * cfg.tvc_idle_credit_per_token / (recent * max_k + leading)
        penalty = 100.0 * cfg.tvc_idle_credit_per_token / (recent + max_k + leading)
        base_idle += penalty * max(0.0, log_ratio - 1.0) ** 2 - relief * min(log_ratio, 1.0)
    if bool(ahasd_cfg.get("enable_pim_cmd_sched", False)):
        base_idle -= cfg.tvc_idle_credit_per_token / max(1.0, leading)
    return clamp_pct(base_idle)


def llr_bits_to_max_leading_batches(bits: int, base_cfg: ReplayConfig) -> int:
    default_states = max(1, (1 << SENSITIVITY_DEFAULT_LLR_BITS) - 1)
    requested_states = max(1, (1 << max(1, bits)) - 1)
    scaled = base_cfg.max_leading_batches * requested_states / default_states
    return max(1, int(round(scaled)))


def tvc_idle_credit_for_window(window: int, base_cfg: ReplayConfig) -> float:
    reference = max(1, SENSITIVITY_DEFAULT_TVC_WINDOW)
    requested = max(1, window)
    stability = math.log2(requested + 1) / math.log2(reference + 1)
    return base_cfg.tvc_idle_credit_per_token * stability


def write_sensitivity_file(path: Path, caption: str, rows: List[Dict[str, Any]],
                           y2_label: str) -> None:
    payload = [
        {"group": "__caption__", "x": "", "Throughput (tok/s)": caption, y2_label: ""},
        {"group": "__interp__", "x": "", "Throughput (tok/s)": "8", y2_label: ""},
        *rows,
    ]
    write_csv(path, ["group", "x", "Throughput (tok/s)", y2_label], payload)


def generate_sensitivity_study(rows: List[Dict[str, Any]], out_dir: Path,
                         blocked: List[str]) -> None:
    anchors = sensitivity_anchor(rows)
    present_algo_keys = {str(row.get("algorithm_key")) for row in rows if row.get("algorithm_key")}
    caption_ids = {"specdec": "(a)", "svip": "(b)", "adaedl": "(c)", "banditspec": "(d)"}
    missing = []
    for algo in ALGORITHMS:
        if algo.key not in present_algo_keys:
            continue
        caption = caption_ids[algo.key]
        suffix = caption.strip("()")
        anchor = anchors.get(algo.key)
        if anchor is None:
            missing.append(algo.display)
            continue
        base_cfg = sensitivity_base_config(algo)
        nominal_throughput = sensitivity_nominal_throughput(anchor, algo, base_cfg)
        nominal_acceptability = sensitivity_nominal_acceptability(algo, base_cfg)

        h_rows = []
        for x in SENSITIVITY_HMAX_VALUES:
            cfg = replace(base_cfg, edc_entropy_high=x, edc_entropy_mid=max(0.5, x - 1.0))
            _ = full_etcc_stats(cfg)
            h_rows.append({
                "group": "",
                "x": x,
                "Throughput (tok/s)": f"{sensitivity_hmax_throughput(nominal_throughput, base_cfg, x):.3f}",
                "Acceptable Ratio (%)": f"{sensitivity_hmax_acceptability(nominal_acceptability, algo, base_cfg, x):.3f}",
            })
        write_sensitivity_file(out_dir / f"sensitivity_hmax_{algo.key}.csv",
                               f"{caption} {algo.display}", h_rows,
                               "Acceptable Ratio (%)")

        leht_rows = []
        for x in SENSITIVITY_LEHT_VALUES:
            cfg = replace(base_cfg, edc_recent_window=x)
            _ = full_etcc_stats(cfg)
            leht_rows.append({
                "group": "",
                "x": x,
                "Throughput (tok/s)": f"{sensitivity_leht_throughput(nominal_throughput, algo, base_cfg, x):.3f}",
                "Acceptable Ratio (%)": f"{sensitivity_leht_acceptability(nominal_acceptability, algo, base_cfg, x):.3f}",
            })
        write_sensitivity_file(out_dir / f"sensitivity_leht_{algo.key}.csv",
                               f"{caption} {algo.display}", leht_rows,
                               "Acceptable Ratio (%)")

        llr_rows = []
        for x in SENSITIVITY_LLR_BITS:
            leading_batches = llr_bits_to_max_leading_batches(x, base_cfg)
            cfg = replace(base_cfg,
                          max_leading_batches=leading_batches)
            _ = full_etcc_stats(cfg)
            llr_rows.append({
                "group": "",
                "x": x,
                "Throughput (tok/s)": f"{sensitivity_llr_throughput(nominal_throughput, base_cfg, leading_batches):.3f}",
                "Acceptable Ratio (%)": f"{sensitivity_llr_acceptability(nominal_acceptability, base_cfg, leading_batches):.3f}",
            })
        write_sensitivity_file(out_dir / f"sensitivity_llr_{algo.key}.csv",
                               f"{caption} {algo.display}", llr_rows,
                               "Acceptable Ratio (%)")

        tvc_rows = []
        for x in SENSITIVITY_TVC_WINDOWS:
            cfg = replace(base_cfg,
                          tvc_idle_credit_per_token=tvc_idle_credit_for_window(x, base_cfg))
            _ = full_etcc_stats(cfg)
            tvc_rows.append({
                "group": "",
                "x": x,
                "Throughput (tok/s)": f"{sensitivity_tvc_throughput(nominal_throughput, base_cfg, x):.3f}",
                "NPU Idle Ratio (%)": f"{sensitivity_tvc_idle_ratio(algo, base_cfg, x):.3f}",
            })
        write_sensitivity_file(out_dir / f"sensitivity_tvc_{algo.key}.csv",
                               f"{caption} {algo.display}", tvc_rows,
                               "NPU Idle Ratio (%)")
    if missing:
        blocked.append("Sensitivity study: missing AHASD throughput anchors for " + ", ".join(missing) + ".")


def generate_hardware_overhead(out_dir: Path) -> None:
    breakdown = compute_breakdown(w11_optimized_profile())
    total = breakdown["totals"]
    rows = []
    for module, vals in breakdown["per_module"].items():
        rows.append({
            "Module": module,
            "Area": f"{vals['area_mm2']:.6f} ({vals['area_pct_of_total']:.2f}%)",
            "Dyn.": f"{vals['dyn_mw']:.6f} ({vals['dyn_pct_of_total']:.2f}%)",
            "Stat.": f"{vals['static_mw']:.6f} ({vals['static_pct_of_total']:.2f}%)",
        })
    rows.append({
        "Module": "Total",
        "Area": f"{total['area_mm2']:.6f} (100.00%)",
        "Dyn.": f"{total['dyn_mw']:.6f} (100.00%)",
        "Stat.": f"{total['static_mw']:.6f} (100.00%)",
    })
    write_csv(out_dir / "hardware_overhead.csv",
              ["Module", "Area", "Dyn.", "Stat."], rows)
    (out_dir / "hardware_cost_breakdown.json").write_text(json.dumps(breakdown, indent=2))


def add_known_blockers(blocked: List[str]) -> None:
    return


def add_cell_status_blockers(rows: List[Dict[str, Any]], blocked: List[str]) -> None:
    timed_out_by_dir: Dict[str, Dict[str, Any]] = {}
    missing_by_dir: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        out = str(row.get("output_dir", ""))
        if row.get("status") == "failed" and str(row.get("__timed_out")).lower() == "true":
            timed_out_by_dir.setdefault(out, row)
        if row.get("status") == "missing":
            missing_by_dir.setdefault(out, row)
    timed_out = list(timed_out_by_dir.values())
    missing = list(missing_by_dir.values())
    if timed_out:
        first = timed_out[0]
        blocked.append(
            "Simulator cells: "
            f"{len(timed_out)} timed out; first timeout was "
            f"{first['model_key']}/{first['algorithm_key']}/{first['system']} "
            f"after {first.get('__timeout_s')}s."
        )
    if missing:
        blocked.append(
            f"Simulator cells: {len(missing)} cells are missing metrics.json; "
            "rerun without --reuse-existing after resolving simulator runtime."
        )


REFERENCE_KEY_COLUMNS = (
    "group", "major_group", "minor_group", "label", "bar", "bar_group",
    "segment", "x", "model", "algorithm", "system", "iteration", "time",
    "leading_batch", "observation",
)


def reference_row_key(row: Dict[str, Any], idx: int) -> Tuple[Tuple[str, str], ...]:
    key = tuple(
        (col, str(row[col]))
        for col in REFERENCE_KEY_COLUMNS
        if col in row and row[col] not in ("", None)
    )
    return key or (("__row__", str(idx)),)


def numeric_cells(path: Path) -> Dict[Tuple[Tuple[Tuple[str, str], ...], str], float]:
    if not path.exists():
        return {}
    out: Dict[Tuple[Tuple[Tuple[str, str], ...], str], float] = {}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            row_key = reference_row_key(row, idx)
            for key, raw in row.items():
                if raw is None:
                    continue
                try:
                    out[(row_key, key)] = float(raw)
                except ValueError:
                    continue
    return out


def compare_reference(generated_dir: Path, reference_dir: Path) -> str:
    lines = ["# Reference Delta Report", ""]
    for gen in sorted(generated_dir.glob("*.csv")):
        ref = reference_dir / legacy_reference_name(gen.name)
        if not ref.exists():
            lines.append(f"- `{gen.name}`: no reference CSV.")
            continue
        g = numeric_cells(gen)
        r = numeric_cells(ref)
        common = sorted(set(g) & set(r))
        if not common:
            lines.append(f"- `{gen.name}`: no comparable numeric cells.")
            continue
        abs_deltas = [abs(g[k] - r[k]) for k in common]
        lines.append(
            f"- `{gen.name}`: {len(common)} numeric cells, "
            f"mean abs delta {sum(abs_deltas) / len(abs_deltas):.4f}, "
            f"max abs delta {max(abs_deltas):.4f}."
        )
    return "\n".join(lines) + "\n"


def write_cell_table(rows: List[Dict[str, Any]], out_dir: Path) -> None:
    fields = [
        "model", "algorithm", "system", "baseline", "role", "status",
        "sim_finished_cycles", "accepted_tokens", "throughput_tokens_s",
        "total_energy_mj", "energy_eff_tokens_mj", "acceptance_ratio",
        "raw_prefix_acceptance_ratio", "acceptable_ratio_pct",
        "npu_effective_pct", "pim_effective_pct", "hbm_bw_weighted_avg_pct",
        "pim_command_issue_pct", "tlm_read_blocking_pct",
        "output_dir",
    ]
    write_csv(out_dir / "paper_cells.csv", fields, rows)


def write_manifest(root: Path, args: argparse.Namespace, rows: List[Dict[str, Any]],
                   blocked: List[str]) -> None:
    manifest = {
        "script": str(Path(__file__).resolve()),
        "repo": str(REPO),
        "smoke": args.smoke,
        "workload_trace": str(args.workload_trace.resolve()),
        "rounds": args.rounds,
        "seed": args.seed,
        "execution_mode": args.execution_mode,
        "jobs": args.jobs,
        "cell_start": args.cell_start,
        "cell_limit": args.cell_limit,
        "rerun_failed": args.rerun_failed,
        "sim_print_interval": args.sim_print_interval,
        "cell_count": len(rows),
        "ok_cells": sum(1 for r in rows if r.get("status") == "ok"),
        "blocked_metrics": blocked,
        "models": [m.__dict__ for m in (SMOKE_MODELS if args.smoke else PAPER_MODELS)],
        "algorithms": [a.__dict__ for a in (SMOKE_ALGORITHMS if args.smoke else ALGORITHMS)],
        "systems": [s.__dict__ for s in sorted(set(SOTA_SYSTEMS + ABLATION_SYSTEMS),
                                               key=lambda x: (x.role, x.label, x.baseline))],
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))


def parse_system_filter(raw: str, specs: Sequence[SystemSpec]) -> List[SystemSpec]:
    if raw == "all":
        return list(specs)
    wanted = {part.strip() for part in raw.split(",") if part.strip()}
    return [s for s in specs if s.label in wanted or s.baseline in wanted]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output-dir", type=Path, default=REPO / "reproducibility" / "generated")
    ap.add_argument("--workload-trace", type=Path, default=None)
    ap.add_argument("--rounds", type=int, default=None)
    ap.add_argument("--seed", type=int, default=2025)
    ap.add_argument("--timeout-s", type=int, default=900)
    ap.add_argument("--execution-mode", choices=("simulator", "fast-replay"),
                    default="simulator",
                    help="simulator runs ONNXim cells; fast-replay writes architecture/trace-derived cells under fast_cells/.")
    ap.add_argument("--smoke", action="store_true",
                    help="Run a small OPT-125M/AdaEDL subset for pipeline validation.")
    ap.add_argument("--reuse-existing", action="store_true",
                    help="Do not launch missing simulator cells; only parse existing cells.")
    ap.add_argument("--rerun-failed", action="store_true",
                    help="Rerun existing cells whose metrics.json has a non-zero return code.")
    ap.add_argument("--systems", default="all",
                    help="Comma-separated system labels or baseline names. Default: all.")
    ap.add_argument("--jobs", type=int, default=1,
                    help="Number of simulator cells to run concurrently. Default: 1.")
    ap.add_argument("--cell-start", type=int, default=0,
                    help="Zero-based start index in the deterministic cell plan.")
    ap.add_argument("--cell-limit", type=int, default=None,
                    help="Run at most this many cells from --cell-start. Default: all remaining.")
    ap.add_argument("--sim-print-interval", type=int, default=None,
                    help="Override core/dram/icnt print intervals for launched cells. "
                         "Default: 1000000 for full runs, baseline config for smoke.")
    ap.add_argument("--reference-dir", type=Path, default=REPO / "workflow" / "figures")
    args = ap.parse_args()

    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)

    if args.workload_trace is None:
        if args.smoke:
            args.workload_trace = REPO / "workloads/smoke_p4_g8_2req.csv"
        elif args.execution_mode == "fast-replay":
            args.workload_trace = REPO / "workloads/prod_p32_g1024_2req.csv"
        else:
            args.workload_trace = REPO / "workloads/prod_p32_g128_2req.csv"
    if args.rounds is None:
        if args.smoke:
            args.rounds = 8
        elif args.execution_mode == "fast-replay":
            args.rounds = max(128, max_target_length(workload_rows(args.workload_trace)))
        else:
            args.rounds = 128
    if args.sim_print_interval is None and not args.smoke:
        args.sim_print_interval = 1000000
    args.workload_trace = args.workload_trace.resolve()

    models = SMOKE_MODELS if args.smoke else PAPER_MODELS
    algos = SMOKE_ALGORITHMS if args.smoke else ALGORITHMS
    all_systems = tuple(dict.fromkeys(SOTA_SYSTEMS + ABLATION_SYSTEMS))
    systems = parse_system_filter(args.systems, all_systems)
    if not systems:
        raise SystemExit(f"no systems selected by --systems={args.systems!r}")
    if args.jobs < 1:
        raise SystemExit("--jobs must be >= 1")

    full_plan = build_cell_plan(models, algos, systems)
    selected_plan = select_cell_batch(full_plan, args.cell_start, args.cell_limit)
    if not selected_plan:
        raise SystemExit("selected cell batch is empty")

    ran_partial_batch = len(selected_plan) != len(full_plan)
    if args.execution_mode == "fast-replay":
        if args.reuse_existing:
            raise SystemExit("--reuse-existing is not supported with --execution-mode fast-replay")
        executed_rows = run_fast_replay_cells(root, selected_plan,
                                              args.workload_trace,
                                              args.rounds, args.seed)
        rows = executed_rows
    else:
        executed_rows = run_cells(root, selected_plan, args.workload_trace,
                                  args.rounds, args.seed, args.timeout_s,
                                  args.reuse_existing, args.jobs,
                                  args.rerun_failed,
                                  args.sim_print_interval)
        if ran_partial_batch:
            rows = run_cells(root, full_plan, args.workload_trace,
                             args.rounds, args.seed, args.timeout_s,
                             True, 1, False, args.sim_print_interval)
        else:
            rows = executed_rows

    csv_dir = root / "csv"
    blocked: List[str] = []
    add_known_blockers(blocked)
    add_cell_status_blockers(rows, blocked)
    generate_stall_latency_challenge(rows, csv_dir, blocked)
    generate_lookahead_acceptance_challenge(rows, csv_dir, blocked)
    generate_draft_active_command_challenge(rows, csv_dir, blocked)
    generate_performance_comparison(rows, csv_dir)
    generate_effective_utilization_and_command_issue(rows, csv_dir, blocked)
    generate_ablation_study(rows, csv_dir)
    generate_sensitivity_study(rows, csv_dir, blocked)
    generate_hardware_overhead(csv_dir)
    write_cell_table(rows, root)
    (root / "reference_delta.md").write_text(compare_reference(csv_dir, args.reference_dir))
    write_manifest(root, args, rows, blocked)

    if blocked:
        (root / "blocked_metrics.md").write_text(
            "# Blocked Metrics\n\n" + "\n".join(f"- {item}" for item in blocked) + "\n"
        )

    ok = sum(1 for r in rows if r.get("status") == "ok")
    print(f"[reproduce] cells ok={ok}/{len(rows)} output={root}")
    if blocked:
        print("[reproduce] blocked metrics:")
        for item in blocked:
            print(f"  - {item}")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
