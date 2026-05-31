# AHASD Release Reproducibility Audit

## Current Release Path

The public release path is:

```bash
python3 scripts/reproduce_paper_data.py \
  --execution-mode fast-replay \
  --output-dir reproducibility/generated \
  --timeout-s 900
```

This command regenerates a 108-cell matrix from model JSON, baseline overlays,
workload rows, generated acceptance traces, replay counters, and hardware cost
model code. It writes canonical semantic CSVs under
`reproducibility/generated/csv`.

## Validation Result

Latest local validation:

- Cells: `108 / 108`
- Blocked metrics: `[]`
- Expected CSV coverage: complete
- Column contract: complete
- Sensitivity CSV count: `16`
- Hardware total: `0.901000 / 12.100000 / 3.838000`

The generated output directory is intentionally ignored and can be removed and
regenerated from the command above.

## Provenance Rules

- Reference CSVs under `workflow/figures/` are optional local delta references.
- Reference CSVs are never used as generation inputs.
- Public CSV names are semantic so manuscript figure numbering can change
  without changing the data contract.
- Development sweep and contract scripts live under `tools/dev/`; the release
  path is `scripts/reproduce_paper_data.py`.

## Known Limitation

The full cycle-accurate ONNXim sweep remains too slow for the full 108-cell
release matrix in the current environment. The fast-replay path is therefore
the complete reproducible release path. It does not claim that the full
cycle-accurate sweep has completed.
