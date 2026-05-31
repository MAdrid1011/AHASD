# AHASD Release Reproducibility Checklist

## Public Contract

- [x] Public reproduction entry point lives in `reproducibility/README.md`.
- [x] Generated data is written under `reproducibility/generated/` and ignored by git.
- [x] Canonical CSV names are semantic and listed in `reproducibility/expected_outputs.json`.
- [x] Optional local reference deltas use an alias map and do not act as generation inputs.

## Required Inputs

- [x] Model architecture JSON files are read from `ONNXim/models/language_models/`.
- [x] Baseline overlays are read from `configs/baselines/`.
- [x] Workload trace defaults to `workloads/prod_p32_g1024_2req.csv` in fast-replay mode.
- [x] Acceptance traces are generated from algorithm priors, family bumps, workload, seed, and rounds.
- [x] Hardware overhead is generated from `scripts/hardware_cost_model.py`.

## Generator

- [x] `scripts/reproduce_paper_data.py` supports the full 108-cell fast-replay release path.
- [x] Output CSVs cover challenge metrics, performance, utilization, command issue, ablation, sensitivity, and hardware overhead.
- [x] Sensitivity sweeps use existing `ReplayConfig` fields and do not rely on nonexistent replay parameters.
- [x] Fast-replay control metadata is recorded as `control_plane_replay_model_v1`.
- [x] The generator does not read reference CSVs as inputs.

## Latest Validation

- [x] Python compile check passed for the release scripts and moved development tools.
- [x] Full fast-replay run completed with `ok_cells=108` and `cell_count=108`.
- [x] `blocked_metrics` is empty.
- [x] All semantic CSVs in `expected_outputs.json` exist.
- [x] Generated CSV headers match `expected_outputs.json`.
- [x] Sensitivity coverage is complete: 16 semantic sensitivity CSVs.
- [x] Hardware total is `0.901000 / 12.100000 / 3.838000`.

## Remaining Limitation

- [ ] The complete 108-cell cycle-accurate ONNXim sweep is still runtime-blocked. The fast-replay path is the current full release reproduction path, while the full simulator sweep remains a longer validation target.
