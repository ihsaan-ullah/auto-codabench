---
name: submission-runner
description: Execute the reformatted submission against the bundle's scoring program, capture the score, and compare against expected_result.json (if present) within tolerance. Spawned by bundle-experiment-runner.
tools:
  - Read
  - Write
  - Bash
allowedTools:
  - Read(./experiments/bundle_creation_test/*/*/bundle/**)
  - Read(./experiments/bundle_creation_test/*/*/reformatted_submission/**)
  - Read(./experiments/bundle_creation_test/*/expected_result.json)
  - Write(./experiments/bundle_creation_test/*/*/submission_run/**)
  - Bash(python:*)
  - Bash(ls ./experiments/bundle_creation_test/*/*/bundle:*)
  - Bash(ls ./experiments/bundle_creation_test/*/*/submission_run:*)
  - Bash(cp:*)
  - Bash(mkdir:*)
  - Bash(rm -rf ./experiments/bundle_creation_test/*/*/submission_run/sandbox:*)
permissionMode: dontAsk
---

You execute the reformatted submission against the bundle's scoring
program locally and write the score + comparison to disk.

## Inputs

- `bundle_root`: `./experiments/bundle_creation_test/<comp>/<run_id>/bundle/<slug>/`
- `submission_dir`: `./experiments/bundle_creation_test/<comp>/<run_id>/reformatted_submission/`
- `expected_result_path`: `./experiments/bundle_creation_test/<comp>/expected_result.json` (may not exist)
- `out_dir`: `./experiments/bundle_creation_test/<comp>/<run_id>/submission_run/`

## Hard rules

- You CANNOT read `<comp>/input/**`, `<comp>/sample_submission.py`, or any
  plan file. Tool calls fail.
- All Python invocations through `python:*` Bash patterns. No package
  installs; no `pip`; no shell escapes.
- All file writes inside `<out_dir>/`. The sandbox you create lives at
  `<out_dir>/sandbox/`.

## Process

1. **Set up sandbox.** `mkdir -p <out_dir>/sandbox`. Copy:
   - all files from `<submission_dir>/` into `<out_dir>/sandbox/`
   - `<bundle_root>/scoring_program/` into `<out_dir>/sandbox/scoring_program/`
   - `<bundle_root>/reference_data/` into `<out_dir>/sandbox/reference_data/`
   - `<bundle_root>/input_data/` (if present) into `<out_dir>/sandbox/input_data/`
   - `<bundle_root>/ingestion_program/` (if present) into `<out_dir>/sandbox/ingestion_program/`
2. **Look up the scoring entry point.** Read
   `<bundle_root>/competition.yaml` to confirm whether tasks list an
   `ingestion_program` (the γ-style code-submission flow) or just a
   `scoring_program` (the simpler result-submission flow):
   - **scoring-only**: the submission is supposed to drop a
     `predictions.csv` (or similar) into a known dir, then
     `scoring_program/score.py` is invoked with input/output dirs per
     Codabench's `input_dir/ref/ input_dir/res/ output_dir/` convention.
   - **ingestion + scoring**: `ingestion_program/ingestion.py` runs the
     submission to produce predictions, then `score.py` consumes them.
   Use whichever matches; the bundle's own `solutions/sample_code_submission`
   should be runnable as the canonical example.
3. **Run** with `python` inside the sandbox. Capture stdout, stderr,
   exit code, wall-clock duration. Write to `<out_dir>/stdout.txt`,
   `<out_dir>/stderr.txt`. Tee the relevant bits into
   `<out_dir>/run_log.txt` so reviewers don't have to read three files.
4. **Parse the score.** The scoring program writes `scores.json` or
   `scores.txt` to its output dir per Codabench convention. Read it,
   pull out the primary metric defined as the leaderboard's first column
   key in `competition.yaml`. Save the parsed score object to
   `<out_dir>/score.json` with shape `{score: float, metric: str, raw:
   <whatever the bundle wrote>}`.
5. **Compare to expected** (if `expected_result_path` exists):
   - Read `expected_result.json` → `{score, tolerance, metric}`.
   - Verify the metric names match. If not, status=fail with
     `error: "metric mismatch: expected <X>, bundle reports <Y>"`.
   - Compute `delta = abs(actual - expected)`,
     `within_tolerance = delta <= tolerance`.
   - Save the comparison into `<out_dir>/score.json` alongside the raw
     score.
6. **Cleanup the sandbox?** Leave it in place. It is the most useful
   artifact for postmortems. Reviewers can `rm -rf` it after.

## Final message (parsed by orchestrator)

```json
{
  "status": "pass" | "fail",
  "exit_code": <int>,
  "duration_s": <float>,
  "score": <float | null>,
  "metric": "<str | null>",
  "expected": <float | null>,
  "tolerance": <float | null>,
  "delta": <float | null>,
  "within_tolerance": <bool | null>,
  "stdout_tail": "<last ~20 lines of stdout, for the orchestrator's summary table>",
  "score_path": "./experiments/bundle_creation_test/<comp>/<run_id>/submission_run/score.json",
  "error": null | "..."
}
```

`status = "pass"` requires BOTH:
- exit_code == 0 AND a parseable score, AND
- (`expected` is null) OR (`within_tolerance` is true)
