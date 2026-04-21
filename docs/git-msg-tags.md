# Git / Issue / PR Tags

This file defines the tag set used in issue titles, PR titles, and commit
messages. Every issue/PR should include exactly one tag from the list below
(combined with the appropriate prefix per the `open-issue` / `open-pr` skills,
e.g. `[plan][feat]: ...` or `[bugfix]: ...`).

## Tags

| Tag         | Meaning                                                                 |
|-------------|-------------------------------------------------------------------------|
| `feat`      | New feature or capability (new simulator module, new analysis, new baseline). |
| `refactor`  | Pure restructuring with no behavioural change (interface reshape, code reorg). |
| `bugfix`    | Fix for a defect that produces wrong results, crashes, or wrong semantics. |
| `perf`      | Performance / runtime / memory optimisation, without changing semantics. |
| `docs`      | Documentation-only change (paper body `AHASPro.md`, READMEs, design notes). |
| `test`      | Test / smoke / CI / validation harness change only.                      |
| `chore`     | Repository housekeeping (gitignore, build infra, dependency pinning).    |
| `paper`     | Academic manuscript edits (AHASPro.md, AHASDFix.md, AHASDExtend.md).    |
| `workflow`  | Progress tracking, plan files, internal meta (`workflow/*.md`).         |

## Prefix Rules (summary, see `open-issue` / `open-pr` skills)

- `[plan][<tag>]`: issues that ship a full implementation plan (files to touch).
- `[<tag>]`: straight feature / bug / chore without a plan.
- `[bug report]`, `[feature request]`, `[improvement]`: high-level requests
  that do not map cleanly to a single tag above.

## Examples

- `[plan][feat]: Multi-model speculative decoding scheduler`
- `[bugfix]: AHASD sidecar coupling log line persists when PIM co-sim is on`
- `[docs]: Section 5.3 SOTA comparison table update`
- `[chore]: populate extern/ from ref build tree`
