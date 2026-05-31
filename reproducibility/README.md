# AHASD Reproducibility Package

This directory is the public entry point for regenerating AHASD paper data.
Generated outputs are written under `reproducibility/generated/` and are not
tracked. The canonical CSV contract is `expected_outputs.json`.

## Run

```bash
python3 -m py_compile \
  scripts/reproduce_paper_data.py \
  scripts/run_etcc_trace_replay.py \
  scripts/run_baseline.py \
  scripts/gen_acceptance_trace.py \
  scripts/hardware_cost_model.py

python3 scripts/reproduce_paper_data.py \
  --execution-mode fast-replay \
  --output-dir reproducibility/generated \
  --timeout-s 900
```

The fast-replay path executes the complete 108-cell paper matrix using
architecture configuration, model JSON, acceptance traces, and replay counters.
The cycle-accurate full ONNXim sweep remains the longer validation path and is
not required for the release package command above.

## Validate

```bash
python3 - <<'PY'
import csv, json, pathlib
root = pathlib.Path("reproducibility/generated")
expected = json.load(open("reproducibility/expected_outputs.json"))["outputs"]
csv_dir = root / "csv"
missing = [item["name"] for item in expected if not (csv_dir / item["name"]).exists()]
bad_columns = []
for item in expected:
    path = csv_dir / item["name"]
    if not path.exists():
        continue
    with path.open(newline="") as f:
        header = next(csv.reader(f))
    if header != item["columns"]:
        bad_columns.append((item["name"], header, item["columns"]))
manifest = json.load(open(root / "manifest.json"))
print(manifest["ok_cells"], "/", manifest["cell_count"])
print("missing:", missing)
print("bad_columns:", [name for name, _, _ in bad_columns])
print("blocked:", manifest.get("blocked_metrics", []))
PY
```

Expected release-package status is `108 / 108`, no missing CSVs, no column
mismatches, and an empty `blocked_metrics` list.

Optional local reference deltas may be produced when `workflow/figures/` exists.
Those files are not generation inputs and are not part of this release package.
