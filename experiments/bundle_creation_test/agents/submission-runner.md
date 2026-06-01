---
name: submission-runner
description: Execute one reformatted submission against the bundle's scoring program, capture the score, and compare against the ground-truth's expected_result.json within tolerance. Spawned by the `bundle-creation-test` skill (in the top-level session) per sub_N.
tools:
  - Read
  - Write
  - Bash
allowedTools:
  - Read(./experiments/bundle_creation_test/runs/*/[0-9a-f]*/bundle/**)
  - Read(./experiments/bundle_creation_test/runs/*/[0-9a-f]*/reformatted_submission/**)
  - Read(./experiments/bundle_creation_test/competitions/*/ground_truth/sample_submissions/*/expected_result.json)
  - Read(./experiments/bundle_creation_test/competitions/*/input/sample_data/**)
  - Write(./experiments/bundle_creation_test/runs/*/[0-9a-f]*/submission_run/**)
  # Python invocations go through `conda run -n <env_name> python ...`
  # — the orchestrator's step-5b prepared a per-run env and the agent
  # is told the env_name in its prompt. Direct `python ...` is also
  # allowed (e.g. for parsing scores.json or sanity-printing) but the
  # scoring program / submission MUST run inside the cloned env so
  # they see the installed deps.
  - Bash(conda run -n acb-run-* python:*)
  - Bash(conda run -n acb-run-* which:*)
  - Bash(python:*)
  - Bash(ls ./experiments/bundle_creation_test/runs/*/[0-9a-f]*/bundle:*)
  - Bash(ls ./experiments/bundle_creation_test/runs/*/[0-9a-f]*/reformatted_submission:*)
  - Bash(ls ./experiments/bundle_creation_test/runs/*/[0-9a-f]*/submission_run:*)
  - Bash(cp:*)
  - Bash(mkdir:*)
  - Bash(rm -rf ./experiments/bundle_creation_test/runs/*/[0-9a-f]*/submission_run/*/sandbox:*)
permissionMode: dontAsk
---

You execute one reformatted submission against the bundle's scoring
program locally and write the score + comparison to disk.

## Inputs (from orchestrator's prompt)

- `bundle_root`: `./experiments/bundle_creation_test/runs/<comp>/<run_id>/bundle/<slug>/`
- `submission_dir`: `./experiments/bundle_creation_test/runs/<comp>/<run_id>/reformatted_submission/<sub_N>/`
- `expected_result_path`: `./experiments/bundle_creation_test/competitions/<comp>/ground_truth/sample_submissions/<sub_N>/expected_result.json`
- `out_dir`: `./experiments/bundle_creation_test/runs/<comp>/<run_id>/submission_run/<sub_N>/`
- `env_name`: the conda env the orchestrator prepared in step 5b (e.g.
  `acb-run-02969776_20260530`). The bundle's scoring program and the
  submission's model code MUST be executed inside this env so they see
  the deps it installed.

## Hard rules

- You CANNOT read:
  - `<comp>/input/report.pdf` (or anything under input/ except sample_data/)
  - `<comp>/<run_id>/plan/**`
  - `<comp>/ground_truth/sample_submissions/<sub_N>/submission/**` (the
    original code — your input is the *reformatted* version)
  - `<comp>/ground_truth/bundle/**` (the golden bundle)
  - any other run's outputs
- **All scoring-program and submission invocations go through
  `conda run -n <env_name> python ...`** — never bare `python` for those.
  The orchestrator prepared the env in step 5b; you are a pure
  executor and have **no permission to pip install** anything. If a
  `ModuleNotFoundError` surfaces during the run, capture it verbatim
  in stderr.txt and return `status=fail` with the import name in
  `error` — that's a step-5b defect (incomplete requirements) for the
  orchestrator to surface, not yours to patch. Bare `python ...` is
  allowed only for orchestrator-side helpers (parsing scores.json,
  sanity-printing array shapes) where the cloned env isn't relevant.
- No `pip`, no `conda install`, no shell escapes.
- All file writes inside `<out_dir>/`. The sandbox you create lives at
  `<out_dir>/sandbox/`.

## Process

1. **Set up sandbox.** `mkdir -p <out_dir>/sandbox`. Copy:
   - all files from `<submission_dir>/` into `<out_dir>/sandbox/`
   - `<bundle_root>/scoring_program/` into `<out_dir>/sandbox/scoring_program/`
   - `<bundle_root>/reference_data/` into `<out_dir>/sandbox/reference_data/`
   - `<bundle_root>/input_data/` (if present) into `<out_dir>/sandbox/input_data/`
   - `<bundle_root>/sample_data/` (if present) into `<out_dir>/sandbox/sample_data/`
   - `<bundle_root>/ingestion_program/` (if present) into `<out_dir>/sandbox/ingestion_program/`
2. **Look up the scoring entry point.** Read
   `<bundle_root>/competition.yaml` to confirm whether tasks list an
   `ingestion_program` (γ-style code-submission flow) or just a
   `scoring_program` (simpler result-submission flow):
   - **scoring-only**: the submission produces predictions; the
     `scoring_program/score.py` is invoked with input/output dirs per
     Codabench's `input/ref/ input/res/ output/` convention.
   - **ingestion + scoring**: `ingestion_program/ingestion.py` runs the
     submission to produce predictions, then `score.py` consumes them.
   The bundle's own `solutions/sample_code_submission/` (canonical
   example) should be runnable as documentation of the flow.
3. **Run** with `conda run -n <env_name> python ...` inside the sandbox.
   Capture stdout, stderr, exit code, wall-clock duration. Write to
   `<out_dir>/stdout.txt`, `<out_dir>/stderr.txt`. Tee the relevant bits
   into `<out_dir>/run_log.txt`. If exit code is non-zero AND the stderr
   tail contains `ModuleNotFoundError: No module named '<X>'`, this is
   diagnostically valuable — surface `<X>` verbatim in the final
   message's `error` field so the orchestrator can attribute the
   failure to step-5b's requirements rather than a bundle defect.
4. **Parse the score.** The scoring program writes `scores.json` or
   `scores.txt` to its output dir per Codabench convention. Read it,
   pull out the primary metric (the leaderboard's first column key in
   `competition.yaml`, or the `primary_score_key` field in
   `expected_result.json` if present). Save the parsed score object
   to `<out_dir>/score.json` with shape:
   ```json
   {"score": <float>, "metric": "<str>", "raw": <whatever the bundle wrote>}
   ```
5. **Compare to expected.** Read `expected_result_path`:
   - Verify the metric names match. If not, `status=fail` with
     `error: "metric mismatch: expected <X>, bundle reports <Y>"`.
   - Compute `delta = abs(actual - expected)`,
     `within_tolerance = delta <= tolerance`.
   - Append the comparison into `<out_dir>/score.json` alongside the
     raw score.
6. **Leave the sandbox in place.** It's the most useful artifact for
   postmortems. Reviewers can `rm -rf` it later if disk pressure.

## Final message (parsed by orchestrator)

```json
{
  "status": "pass" | "fail",
  "sub": "<sub_N>",
  "exit_code": <int>,
  "duration_s": <float>,
  "score": <float | null>,
  "metric": "<str | null>",
  "expected": <float | null>,
  "tolerance": <float | null>,
  "delta": <float | null>,
  "within_tolerance": <bool | null>,
  "stdout_tail": "<last ~20 lines of stdout>",
  "score_path": "./experiments/bundle_creation_test/runs/<comp>/<run_id>/submission_run/<sub_N>/score.json",
  "error": null | "..."
}
```

`status = "pass"` requires BOTH:
- exit_code == 0 AND a parseable score, AND
- `within_tolerance` is true (or `expected` is null, in which case
  `within_tolerance` is null and the run-only check is what passes).
