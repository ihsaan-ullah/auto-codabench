---
name: autocodabench-reformat-and-run
description: Adapt one external submission's code to match a previously-built bundle's interface AND the libraries its Docker image ships, then run it through the bundle's scoring pipeline. Iterates on runtime errors (missing packages, API breaks, wrapper-shape mismatches) and returns parsed scores + full logs. Used by the bundle-creation-test experiment harness AFTER `autocodabench-implement` has finished and the bundle is runtime-validated. Strictly blind to any expected_result.json or other ground-truth metadata — only sees the submission code and the bundle's public surface.
---

# AutoCodabench — Reformat & Run

You are given:

- a Codabench `bundle_dir` (already runtime-validated by an earlier
  `autocodabench-implement` invocation: its baseline runs cleanly,
  its notebook executes cleanly),
- a `submission_dir` containing one external submission's code (a
  ground-truth `sub_N/submission/` directory),
- an `env_name` (accepted for compatibility; ignored — execution is Docker-only),
- an `out_dir` where you must write the adapted submission, logs, and
  parsed score JSON.

Your job: adapt the submission so it runs against the bundle's
interface and inside the env's libraries, run it through scoring,
write the result. **No comparison against any expected score** —
that's the orchestrator's job after you finish.

---

## 0. Hard rules

1. **API adaptation only — never re-scoping.** You may:
   - rename `tf.keras.optimizers.legacy.Adam` → `tf.keras.optimizers.Adam`,
   - swap `from keras.preprocessing import X` → `from tensorflow.keras.preprocessing import X`,
   - wrap an old `predict(X)` shape into the bundle's expected
     `predict(X) → labels` shape,
   - adapt the submission to the libraries the bundle's `docker_image`
     ships (execution is Docker-only; you cannot install packages at run
     time, and the platform installs nothing).

   You MUST NOT:
   - swap the model class to a smaller one because GPU isn't available,
   - change hyperparameters, loss, metric, seed, epoch count,
   - generate synthetic data,
   - read the bundle's reference_data labels and hard-code predictions
     against them. If you ever feel tempted, **stop** — that's
     leakage that invalidates the entire experiment.

2. **No access to expected_result.json, plan, or input/report.pdf.**
   Your inputs are the four arguments above. Any other file under
   the experiment run dir is off-limits.

   Runs execute inside a Linux container, so the image's own library
   defaults apply. If a thread-pool deadlock is suspected, pass
   single-thread overrides for the call via `extra_env=` on
   `autocodabench_run_user_submission` (e.g.
   `{"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}`); they are
   applied as `-e` flags before the container's python starts. Do NOT
   add `os.environ.setdefault(...)` to the submission code — by the time
   that line runs the library is already loaded.

3. **Bounded attempts.** `MAX_ATTEMPTS = 4`. Initial reformat counts
   as attempt 1; up to 3 retries on runtime errors. Per attempt:
   write to `<out_dir>/attempt_<K>/`. Each retry reads the prior
   attempt's stderr_tail + adapted code so you can refine the patch.

4. **Probe the image, don't guess.** Scoring runs execute inside the
   bundle's declared `docker_image` (Docker-only execution), so probe the
   image — not any host environment. Read the image from the bundle's
   `competition.yaml`, then use Bash patterns in your `allowedTools`:
   - `docker run --rm <docker_image> pip list --format=freeze`
     to learn what is installed,
   - `docker run --rm <docker_image> python3 -c "import X; print(X.__version__)"`
     to confirm a specific package's version,
   - `docker run --rm <docker_image> python3 -c "from X import Y"`
     to test an import in isolation.

   Adapt the submission to what the image ships. You cannot install
   packages at run time — the platform installs nothing, so a run-time
   install would pass here and fail on Codabench. If a dependency is
   genuinely missing and the submission cannot be adapted without it,
   that is a bundle-level image-choice limitation to record, not
   something to patch around.

---

## 1. Inputs (parsed from the orchestrator's prompt)

```
bundle_dir:       <abs path to runtime-validated bundle>
submission_dir:   <abs path to ground-truth submission code>
env_name:         <accepted for compatibility; ignored — Docker-only>
out_dir:          <abs path; write attempt_<K>/ + final.json under here>
```

If the orchestrator also passes a `prior_attempts` list (on retry),
each entry has shape:
```
{
  "attempt_n": <int>,
  "out_dir":   "<path>",
  "code_path": "<path to the prior attempt's adapted submission>",
  "error":     "<one-line summary>",
  "stderr_tail": "<last ~80 lines of the runner's stderr>",
}
```

---

## 2. Process

### 2.1 Probe the image (once, on attempt 1 only)

Read the bundle's `docker_image` from `competition.yaml`, then run a small
set of `docker run --rm <docker_image> pip list` /
`docker run --rm <docker_image> python3 -c "import X; print(X.__version__)"`
commands to confirm what the image ships. Save the summary to
`<out_dir>/env_probe.txt` for forensics.

### 2.2 Learn the bundle's interface

Read:
- `<bundle_dir>/competition.yaml` — figure out λ vs γ submission
  protocol from whether `ingestion_program` is referenced.
- `<bundle_dir>/solutions/solution_baseline/` (or whichever
  `solutions/<subdir>/` is referenced) — this is the contract you're
  reformatting against. Match its shape exactly (file names, class
  name, method signatures).
- `<bundle_dir>/ingestion_program/ingestion.py` if present — this is
  what will actually invoke your code, so read it to learn precisely
  what entry point it calls.

### 2.3 Read the ground-truth submission

Read every file under `<submission_dir>/`. Identify:
- the entry-point class / function,
- imports it makes,
- the data shape it expects,
- the output shape it produces.

### 2.4 Write the adapted submission to `<out_dir>/attempt_<K>/`

Create `<out_dir>/attempt_<K>/` and write:
- the adapted code files (mirroring the bundle's baseline file
  layout — usually `model.py` + helpers),
- a short `adapter_notes.md` listing every old→new API substitution
  you made and why (one line each).

Adapt to what the image already ships (§2.1). You cannot install
packages at run time; if the submission genuinely cannot run against the
image's libraries, record that limitation in `adapter_notes.md` and let
the run fail honestly rather than patching around it.

### 2.5 Run via the bundle's pipeline

```
res = autocodabench_run_user_submission(
    slug=<bundle slug>,
    submission_dir="<out_dir>/attempt_<K>/",
    label="<sub_label>.attempt_<K>",
)
```

`res` is the same shape `run_baseline_submission` returns:
`ok`, `stage`, `ingestion`, `scoring`, `scores`, `sandbox_dir`,
`logs_dir`, `error`.

### 2.6 Decide

- `res["ok"]` is True → SUCCESS. Write `<out_dir>/final.json`:
  ```json
  {
    "ok": true,
    "attempt_n": <K>,
    "scores": <res["scores"] verbatim>,
    "logs_dir": "<res['logs_dir']>",
    "adapter_notes_path": "<out_dir>/attempt_<K>/adapter_notes.md",
    "env_probe_path": "<out_dir>/env_probe.txt",
    "extras_installed": [...]
  }
  ```
  Emit your final JSON message (see §3) and STOP.

- `res["ok"]` is False → diagnose `res["error"]` +
  `res["scoring"]["stderr_tail"]` (and `res["ingestion"]["stderr_tail"]`
  if γ-style). Decide which fix class applies (same table the
  implementer skill uses for its own baseline). If `K <
  MAX_ATTEMPTS`, increment K and loop to 2.4 with the diagnosis
  written into the next attempt's notes. If `K == MAX_ATTEMPTS`,
  write `<out_dir>/final.json` with `ok: false`, the last error,
  pointers to every attempt's dir, and STOP.

---

## 3. Final message (parsed by the orchestrator)

A single JSON object on the last line:

```json
{
  "status": "pass" | "fail",
  "attempts_used": <int>,
  "max_attempts": 4,
  "final_attempt_dir": "<out_dir>/attempt_<K>/",
  "logs_dir": "<bundle's run_logs dir for the final attempt>",
  "scores": <dict or null>,
  "stage_failed": "ingestion" | "scoring" | null,
  "error": null | "<one-line summary>",
  "extras_installed": [<pypi specs across all attempts>],
  "adapter_notes": [
    {"attempt_n": 1, "summary": "ported legacy.Adam; added tf_keras"},
    {"attempt_n": 2, "summary": "wrapper.predict() returned (N,1); flattened"}
  ]
}
```

The orchestrator never reads `expected_result.json` here — it does
so AFTER this skill returns, comparing your `scores` to its known
target. So a `status: pass` from you only means "the bundle scored
this submission to a parseable number"; it doesn't mean "the score
is correct."

---

## 4. Things to avoid

- ❌ Reading `<...>/ground_truth/sample_submissions/sub_N/expected_result.json`.
  It exists but you have no permission to open it. If you find
  yourself unsure how close you are to the right score, that's the
  signal that the experiment is doing its job — you're supposed to
  not know.
- ❌ Looking inside the golden `<...>/ground_truth/bundle/` for hints
  on what the metric "should" be. The bundle dir you were handed is
  the contract; anything else is leakage.
- ❌ Patching `score.py` to make the metric easier. You may not edit
  any file under `<bundle_dir>/scoring_program/` or
  `<bundle_dir>/ingestion_program/`. Your edits are entirely on the
  submission side.
- ❌ Skipping retries because "the error looks unrecoverable". The
  retry budget exists because some failures only become diagnosable
  after one attempt — e.g. an abseil deadlock only manifests with
  the right two libraries co-resident. Try the targeted fix; if it
  still fails, then stop.
