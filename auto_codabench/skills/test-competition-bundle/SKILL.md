---
name: test-competition-bundle
description: Phase 3 of an AutoCodabench session — validate the generated competition bundle from Phase 2 by running the structural validator, inventorying bundle components (detecting dirs vs zips and extracting as needed), and executing the ingestion and scoring programs locally to confirm an end-to-end working bundle before upload.
---

# AutoCodabench — Phase 3: Validation & Local Testing

You are running **Phase 3** of an AutoCodabench session. Phase 2 produced
a Codabench bundle folder (and a zip alongside it). Your job is to verify
it works end-to-end: structural validation, component inventory, and a
dry-run of ingestion (if present) and scoring against the bundle's own data.

---

## 0. Hard rules

1. **First two operations, in order:**
   ```
   autocodabench_current_run()
   autocodabench_log_event(kind="stage_started", payload={"stage": "9.test"})
   ```
2. **Read-and-run only.** Don't call any `autocodabench_write_*` or
   `autocodabench_zip_bundle` tool. The only outputs written to disk
   are those produced by the ingestion/scoring programs themselves
   (e.g. `scores.json`).
3. **Don't create directories.** Use only paths already present in
   the bundle. If a component is a zip file, extract it in-place;
   otherwise use the directory as-is.
4. **Surface errors verbatim.** If any step fails, paste the full
   stderr/traceback into the report. Don't silently skip a failed step.
5. **Log progress.** `stage_started` at the top, `stage_done` at the end.

---

## 1. Locate the bundle

```python
run = autocodabench_current_run()
```

**If `run.opened` is `True`**: the run dir is `run.path`. Skip the fallback below.

**If `run.opened` is `False`** (no active run in this session — common when
Phase 3 is invoked standalone rather than chained from Phase 2): resolve the
`LATEST` symlink, which always points at the most recently opened run:

```bash
# Resolve LATEST symlink to get the run directory name
readlink auto_codabench/runs/LATEST
# → e.g. master_20260609T194004-1

# Full run dir path
ls auto_codabench/runs/$(readlink auto_codabench/runs/LATEST)/bundles/
```

Use `auto_codabench/runs/<LATEST>/` as the run dir for all subsequent steps.
If LATEST does not exist, list `auto_codabench/runs/` and pick the most
recently modified folder — or ask the user which run to test.

---

Once the run dir is known, find the bundle zip:

Phase 2 always writes the bundle as **both** a folder and a zip:
```
<run_dir>/bundles/<slug>/          ← unzipped folder
<run_dir>/bundles/<slug>/<slug>.zip    ← USE THIS
```

```bash
# List available bundle zips under this run
ls <run_dir>/bundles/*.zip 2>/dev/null || ls <run_dir>/bundles/*/
```

If there is only one zip, use it. If there are multiple, use the most
recently modified one (or ask the user to confirm).

Extract the zip into a new folder `_temp_test_bundle` inside the run's
bundles directory. Use this extracted folder as `<bundle_path>` for all
subsequent steps:

```bash
mkdir -p <run_dir>/bundles/_temp_test_bundle
unzip <run_dir>/bundles/<slug>.zip -d <run_dir>/bundles/_temp_test_bundle/
```


---

## 2. Run the structural validator

The project ships a validator at `scripts/competition_bundle_validator.py`
(relative to the project root). Run it:

```bash
python3 scripts/competition_bundle_validator.py <bundle_path>
```

Surface the full output. Possible outcomes:

- `[+] Bundle is valid!` → proceed.
- `[-] Validation Error: <message>` → report the exact error and stop.
  Don't run programs against a structurally invalid bundle.

---

## 3. Inventory bundle components

Read `competition.yaml` with the `Read` tool. For each component path
referenced in the yaml (`tasks[*].scoring_program`,
`tasks[*].ingestion_program`, `tasks[*].input_data`,
`tasks[*].reference_data`, `phases[*].public_data`), check whether it
is a **directory** or a **zip file**:

```bash
# check type
file <bundle_path>/<component_path>
# or
ls -la <bundle_path>/<component_path>
```

Build a summary table:

| Component         | Path                     | Present | Type       |
|-------------------|--------------------------|---------|------------|
| scoring_program   | scoring_program/         | ✓ / ✗  | dir / zip  |
| ingestion_program | ingestion_program/       | ✓ / ✗  | dir / zip  |
| input_data        | input_data/              | ✓ / ✗  | dir / zip  |
| reference_data    | reference_data/          | ✓ / ✗  | dir / zip  |
| public_data       | public_data/             | ✓ / ✗  | dir / zip  |

**If any component is a zip**, extract it in-place before continuing:
```bash
unzip <bundle_path>/<component>.zip -d <bundle_path>/<component_name>/
```
Then use the extracted directory for all subsequent steps.

Flag any component listed in `competition.yaml` that is absent entirely —
the structural validator (§2) should have caught this, but note it explicitly.

---

## 4. Run ingestion program (if present)

**Skip this step** if:
- No `ingestion_program` key appears in any task in `competition.yaml`, OR
- The `ingestion_program` directory exists but its Python files contain
  only `NotImplementedError` stubs (grep for `raise NotImplementedError`).

If a real ingestion program exists, find its **entry point**:
1. Check `<bundle>/ingestion_program/metadata.yaml` for a `command:` line.
   Extract the **script filename only** — ignore the `/app/…` platform
   paths, they don't apply locally. E.g. `command: python3 /app/program/ingestion.py …`
   → entry script is `ingestion.py`.
2. If no `metadata.yaml`, look for `ingestion.py` inside the directory.

Find the **baseline submission** directory (participant code for the dry run):
- `<bundle>/solutions/solution_baseline/` (preferred — written by Phase 2)
- `<bundle>/sample_code_submission/` (fallback)
- `<bundle>/starting_kit/` (fallback)

Run ingestion with paths already present in the bundle. Check the
ingestion script's `argparse` or `sys.argv` setup first, then adapt:

```bash
python <bundle>/ingestion_program/<entry_script> \
    --input_dir      <bundle>/input_data/ \
    --output_dir     <bundle>/solutions/solution_baseline/ \
    --program_dir    <bundle>/ingestion_program/ \
    --submission_dir <bundle>/solutions/solution_baseline/
```

> Argument names vary. Read the script's argument parser and use the
> correct flag names.

Check the output path used in the ingestion, create it if it does not exist. 

Surface full stdout/stderr. Report ✓ pass or ✗ fail.

---

## 5. Run scoring program

Find the **entry point**:
1. Check `<bundle>/scoring_program/metadata.yaml` for `command:`. Extract
   the script filename only (e.g. `score.py`); ignore `/app/…` paths.
2. If no `metadata.yaml`, look for `score.py`.

Determine the **predictions source** (in priority order):
1. If ingestion ran (§4): predictions are in the ingestion output dir
   (e.g. `<bundle>/solutions/solution_baseline/`).
2. If no ingestion (λ / result-submission competition): look for
   `predictions.txt` or `predictions.npy` inside:
   - `<bundle>/solutions/solution_baseline/`
   - `<bundle>/starting_kit/`
   - `<bundle>/` (bundle root)

   If predictions are absent, inform the user — they need to run the
   baseline `model.py` to generate them first — then stop this step.

Run scoring using paths already present in the bundle. The generated
`score.py` from Phase 2 takes three positional arguments:

```bash
python <bundle>/scoring_program/<entry_script> \
    <predictions_dir> \
    <bundle>/ \
    <bundle>/reference_data/
```

Where:
- arg 1 (`input_dir`) — directory containing the predictions file
- arg 2 (`output_dir`) — directory where `scores.json` is written
  (use the bundle root so no new dir is needed)
- arg 3 (`reference_dir`) — `<bundle>/reference_data/`

After scoring, read the output:
```
Read("<bundle>/scores.json")
```

Display scores in a formatted table:
```
Metric              Score
────────────────────────────
<key>               <value>
```

Surface full stdout/stderr. Report ✓ pass or ✗ fail.

---

## 6. Closing report + log

Render this block verbatim (fill in each section):

```
## Phase 3 — Validation & Local Testing Report

### Structural validation
<✅ Passed | ❌ Failed: <error message>>

### Bundle components
<paste the inventory table from §3>

### Ingestion program
<✅ Ran successfully | ⚠ Skipped — <reason> | ❌ Failed: <error>>

### Scoring program
<✅ Ran successfully | ❌ Failed: <error>>

### Scores
| Metric | Score |
|--------|-------|
| <key>  | <value> |

### Issues to fix before uploading
<bulleted list of errors or warnings found, or "None — bundle is ready to upload.">
```

Then log:
```python
autocodabench_log_event(
    kind="stage_done",
    payload={
        "stage": "9.test",
        "validator_ok": <bool>,
        "ingestion_ok": <bool or null if skipped>,
        "scoring_ok": <bool>,
        "scores": {<key: value from scores.json>},
    },
)
```

---

## 7. Tools you may call

- `autocodabench_current_run()` — locate the run dir and slug.
- `autocodabench_log_event(kind, payload?)` — progress logging.
- `Read` — read `competition.yaml`, `metadata.yaml`, source files.
- `Bash` — run the validator, `unzip`, ingestion script, scoring script.

**Do NOT call**: any `autocodabench_write_*` tool,
`autocodabench_zip_bundle`, `autocodabench_validate_bundle` (the MCP
linter — Phase 3 uses the standalone `scripts/competition_bundle_validator.py`
instead), or `autocodabench_upload_bundle`.

---

## 8. If things go sideways

- **Bundle folder missing** → Phase 2 didn't complete. Point the user
  at the Phase 2 phase bar button and stop.
- **Validator fails** → report the exact `[-] Validation Error:` line.
  Common fixes: missing `docker_image` field, missing image file, empty
  terms page, leaderboard column key mismatch with `scores.json`.
- **Ingestion raises `NotImplementedError`** → the ingestion template
  was not filled in. Mark the step as ⚠ Skipped and proceed to scoring.
- **Scoring fails with `FileNotFoundError` on predictions** → no
  predictions file was found. Inform the user that they must run the
  baseline `model.py` first to generate predictions, then re-run Phase 3.
- **`scores.json` missing after scoring** → scoring ran but wrote to
  the wrong path. Re-read the scoring script's `output_dir` argument
  and check what directory it used.
