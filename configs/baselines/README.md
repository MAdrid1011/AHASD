# `configs/baselines/` — simulator baseline presets

Each file here is one of:

- `_base_*.json` — complete simulator system model (cores / DRAM / ICNT /
  scheduler). Contains **no behavioural flags**; holds the knobs that
  determine the underlying hardware. Additional base configs (e.g. GPU-class
  NPU for C3) live beside this one as new `_base_*.json` files.
- `<baseline>.json` — thin behavioural overlay that declares its base via
  `_inherits` and then sets just the fields that matter for the baseline.
  `scripts/run_baseline.py` resolves `_inherits` by merging the base keys
  into the overlay (overlay wins on collision).

## Current presets

| file | phase | what it models |
|------|-------|----------------|
| `_base_systolic_c4_128x128_hbm2.json` | — | Mobile NPU: 4 cores × 128×128 systolic, HBM2 via Ramulator2, Booksim-fly ICNT |
| `npu_only.json` | C1 / W5 | DLM + TLM serial on ONNXim, LPDDR5 as plain memory, SpecDec standard (no AHASD) |
| `ahasd_full.json` | reference | AHASD + PIM co-sim + EDC + TVC + AAU + GTSU |

## How to run a baseline

```bash
scripts/run_baseline.py \
  --baseline npu_only \
  --model-pair opt-125m:opt-125m-t \
  --workload-trace workloads/smoke_p4_g8_2req.csv \
  --acceptance-csv workflow/b27/accept_trace.csv \
  --output-dir workflow/c1/npu_only
```

The runner writes `onnxim_config.json`, `models_list.json`, `log.txt`, and a
parsed `metrics.json` into `--output-dir`. It also copies the workload trace
into `ONNXim/traces/` under a stable name so the simulator can resolve it.

## Adding a new baseline

1. Drop `<new>.json` into this directory with an `_inherits` pointer and the
   override keys.
2. Make sure any new simulator flags it references are parsed in
   `ONNXim/src/Common.cc` first.
3. Add a row to the table above and to `workflow/PROGRESS.md` under the
   corresponding Phase C/D entry.
