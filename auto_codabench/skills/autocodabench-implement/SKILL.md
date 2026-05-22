---
name: autocodabench-implement
description: Execute Stage 8 of an AutoCodabench session — package the executed `starting_kit.ipynb` (plus per-stage decisions logged in events.jsonl) into a Codabench bundle. Reads the run dir, generates competition.yaml + scoring_program/ + solution/ + pages/, validates, zips, and optionally uploads. Triggered automatically by the UI when stage 7's Approve is clicked, or manually by `/autocodabench-implement` in a fresh CLI chat.
---

# AutoCodabench — Stage 8: Bundle packaging

You arrive here in one of two ways:

1. **Web UI** — the user clicked Approve on stage 7 (Diagnostics).
   The web layer rebuilt the agent with bundle-write tools and a
   Phase-C system prompt, then auto-prompted "Begin stage 8: bundle
   packaging." You're under that prompt right now.

2. **CLI** — the user typed `/autocodabench-implement` in a fresh
   Claude Code chat after an earlier session built the notebook.

In both cases the *design* is locked: it lives in the executed
`starting_kit.ipynb` and the `events.jsonl` events the orchestrator
logged. **Your job is to package, not to redesign.**

---

## 0. Hard rules

1. **Read first, write second.** Read `meta.json`, the executed
   `starting_kit.ipynb`, and `events.jsonl` BEFORE calling any write
   tool. The notebook tells you the chosen task, data, metric,
   baseline. The events log tells you the decisions the user
   approved at each stage. If anything is unclear, ASK the user.
2. **No design decisions.** Don't pick a different metric, change
   the splits, add a baseline the user didn't ask for. If something
   is missing, surface it and ask.
3. **Validate before zipping.** `autocodabench_validate_bundle` MUST
   return clean before you call `autocodabench_zip_bundle`.
4. **Upload only on explicit user request.** Uploading creates a
   public Codabench competition; the user must explicitly say
   "publish" / "upload" / "push to Codabench". A silent successful
   zip is the default success state.
5. **Log progress.** `autocodabench_log_event(kind="stage_started",
   payload={"stage": "8.bundle"})` at the very start; intermediate
   `bundle_file_written` events; `stage_done` at the end.

---

## 1. Find the run

```
result = autocodabench_current_run()
```

If `result["opened"]` is False, ask the user which run dir to use.
Otherwise `result["path"]` is your working directory.

Log:
```
autocodabench_log_event(kind="stage_started",
                        payload={"stage": "8.bundle"})
```

---

## 2. Read the locked artifacts

Use the `Read` tool — all on local disk.

1. `<run>/starting_kit.ipynb` — the executed notebook. The model
   class, scoring function, baseline training, predict/score loop
   are all here. This is the SOURCE OF TRUTH for stage 8 packaging.

2. `<run>/events.jsonl` — every `stage_done` event the user approved.
   Lookup the `stage`/`payload` pairs to confirm what decisions are
   in scope.

3. `<run>/meta.json` — session metadata (slug, branch, started_at).

4. **Reference, on demand**:
   `auto_codabench/skills/codabench-bundle/SKILL.md` — the bundle
   schema (competition.yaml shape, scoring program metadata.yaml,
   pages, phases). Read it when you need a specific YAML key — don't
   redefine schema details here.

Send the user a one-paragraph summary of what you found in the
notebook (task, metric, baseline, data shape) so both sides know
you have the right artifacts loaded.

---

## 3. Generate the bundle

A Codabench bundle is the contents of a directory zipped at the root.
Generate the files in this order — each one corresponds to one or
two MCP tool calls. The bundle slug should match `<run>/meta.json
→ slug` (or `<run>/meta.json → branch_id`-derived if slug is empty).

### 3.1 `autocodabench_init_bundle(slug)`
Creates the bundle directory tree under
`auto_codabench/bundles/<slug>/`. Idempotent.

### 3.2 Scoring program — `autocodabench_write_scoring_program(slug, score_py, metadata_yaml)`
Extract the `score(...)` function from the notebook's stage-4 cells.
The `score_py` argument is the full Python source of a `score.py`
that:
- Reads `prediction.txt` (or `predictions.csv`) from the input dir
  Codabench will populate.
- Reads the held-out labels from `reference_data/`.
- Writes a JSON object to `scores.json` with the metric value(s).

`metadata_yaml` is the scoring program's `metadata.yaml` — see
codabench-bundle SKILL.md §3 for the exact shape (one line:
`command: python score.py`).

### 3.3 Solution / starting kit — `autocodabench_write_solution(slug, files)`
Bundle the notebook + the baseline model class. `files` is a dict
mapping relative path → file content. Recommended layout:

```
solution/
├── Starting_kit.ipynb        # the executed notebook from this session
├── sample_code_submission/
│   └── model.py               # the model class extracted from notebook stage 5
└── sample_data/
    └── ...                    # tiny example data from notebook stage 2
```

Extract the model class verbatim from the notebook's stage-5 cells.
Don't reformat; the participant should see the same code that worked
on the user's screen.

### 3.4 Pages — `autocodabench_write_page(slug, name, body)`
Four standard pages, each a short markdown:
- `overview.md` — competition motivation, derived from stage-0
  citations and the user's roadmap.
- `evaluation.md` — the metric (from stage 4) and the success
  criterion.
- `terms.md` — license, citation requirement, IRB posture.
- `data.md` — data sources, split protocol (from stage 2's design
  summary), download instructions.

Reuse OpenAlex / Pavão citations from the notebook's stage summaries.

### 3.5 Data — `autocodabench_attach_data(slug, kind, files)`
Three calls, one per `kind`:
- `reference_data` — held-out labels Codabench uses for scoring.
- `input_data` — what participants see (features without labels).
- `public_data` — the sample data shipped in the starting kit.

For toy / proof-of-concept competitions these can mirror the small
data the notebook used, with the train-vs-test partition the user
chose at stage 2.

### 3.6 Master file — `autocodabench_write_competition_yaml(slug, body)`
The `competition.yaml` ties everything together. See codabench-bundle
SKILL.md §1 for the full schema. Key fields to fill from this session:
- `title`: slug-derived or from the user's first message.
- `version: 2`.
- `phases`: feedback + final, with start/end placeholders the user
  fills before upload (we don't lock dates here).
- `tasks`: one task per phase, pointing at the scoring program / data
  / submission template.
- `leaderboards`: one column per metric the user approved at stage 4.
- `pages`: list the four pages from §3.4.

---

## 4. Validate

```
result = autocodabench_validate_bundle(slug)
```

If `result["ok"]` is False, fix the specific issues it flagged
(missing referenced files, leaderboard column not matching
`scores.json` keys, wrong YAML key, …) and re-validate. Don't move
on to zipping with validation errors.

---

## 5. Zip

```
result = autocodabench_zip_bundle(slug)
```

Returns `{"zip_path": "<run>/bundles/<slug>/<slug>.zip"}`.

---

## 6. Optional: publish

Only if the user explicitly asked ("publish", "upload", "push to
Codabench"):

```
result = autocodabench_upload_bundle(slug)
```

Requires `CODABENCH_USERNAME` + `CODABENCH_PASSWORD` (or
`CODABENCH_TOKEN`) in env. Returns
`{"competition_id": <int>, "competition_url": "https://www.codabench.org/competitions/<id>/"}`.

Surface the URL prominently in your closing message.

---

## 7. Closing message + log

```
✅ Bundle ready.

  bundle zip       — <run>/bundles/<slug>/<slug>.zip
  validate_bundle  — passed
  files written    — <n>
  codabench URL    — <url if uploaded; "(not uploaded)" otherwise>

  notebook         — <run>/starting_kit.ipynb (executed)
  full transcript  — <run>/transcript.md
```

Then:

```
autocodabench_log_event(kind="stage_done",
                        payload={"stage": "8.bundle",
                                 "zip_path": "...",
                                 "validated": true,
                                 "uploaded": <bool>,
                                 "competition_url": "<url or null>"})
```

Stage 8 marked DONE → the TaskList's title flips to "All stages done"
and the session naturally winds down. STOP.

---

## 8. If things go sideways

- **`current_run()` returns `opened: False`** → ASK which run dir.
  Don't open a new one (that would orphan the user's notebook).
- **The notebook is missing or empty** → the user came in via CLI
  without a prior planning session. ASK them what to build; this
  is not your skill to drive — point them at
  `/autocodabench-orchestrator`.
- **A scoring `score.py` won't validate locally** → READ the
  notebook's metric cell verbatim; copy the function signature
  EXACTLY. Most lint failures are a renamed argument or a missing
  import.
- **The zip is >100 MB** → the user is shipping real data in
  `solution/sample_data/`. Reduce to ~10 examples per class; the
  full data goes in `reference_data` / `input_data` not in the
  starting kit zip.
