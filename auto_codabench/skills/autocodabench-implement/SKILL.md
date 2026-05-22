---
name: autocodabench-implement
description: Execute the AutoCodabench implementation phase — turn a locked design (project_proposal.md + 6 specs + implementation_plan.md) into a working Codabench bundle. Reads the run dir, calls the autocodabench_* write tools per the plan, validates, zips, optionally uploads. Triggered by `/autocodabench-implement` in a fresh CLI chat, or by the START IMPLEMENTATION button in the web UI.
---

# AutoCodabench — Implementation (Phase C)

You are executing **Phase C**: turning a locked design into a working
Codabench bundle. Phases A (proposal) and B (specs) are done — the
artifacts live on disk and you treat them as the source of truth.

**Don't redo design decisions.** If anything is ambiguous, ask the
user. Specifically, never invent a metric, a license, or a split that
isn't in `project_proposal.md` or one of the six specs.

---

## 0. Find the run dir

The previous phases wrote everything under one run directory. Locate it:

```
autocodabench_current_run()
```

returns the active dir. If it doesn't return anything (e.g. you started
this skill in a fresh chat without an open run), check the
`AUTOCODABENCH_RUN_DIR` env var. If neither is set, the user has not
linked you to a planning run — stop and ask which run dir to use
(e.g. `auto_codabench/runs/LATEST`).

After locating the run dir, call:

```
autocodabench_log_event(kind="phase_c_started",
                        payload={"run_dir": "..."})
```

---

## 1. Read the locked artifacts FIRST

Before any write tool runs, read all four artifact families. Use the
`Read` tool — the run dir is on local disk.

1. `<run>/specs/project_proposal.md` — the proposal (source of truth).
2. `<run>/specs/01-task-framing.md` through `<run>/specs/06-run-logging-and-env.md` — the six implementation specs.
3. `<run>/implementation_plan.md` — your step-by-step plan.
4. (Reference, on demand) `auto_codabench/skills/codabench-bundle/SKILL.md` — the bundle schema. Read it when you need the exact shape of `competition.yaml` or a scoring program's `metadata.yaml`. **Do not duplicate its content here.** It is the canonical reference.

Send the user a one-paragraph summary of what you read, so both sides
know you have the right artifacts loaded. Format:

```
Loaded:
  proposal — <one-sentence summary>
  specs    — <list of file names found, with one-line summary each>
  plan     — <count of steps>

Starting execution now.
```

---

## 2. Execute the plan

Follow `implementation_plan.md` step by step. Each step typically maps
to **one** `autocodabench_*` write tool call. The plan was written by
the orchestrator in Phase B; trust its ordering.

For each step:

1. State which plan step you're on, briefly.
2. Call the write tool with the inputs the spec dictates.
3. Call `autocodabench_log_event(kind="bundle_file_written",
   payload={"step": "<plan step id>", "tool": "...", "file": "..."})`.
4. If the tool fails, fix the input from the spec, retry once. If it
   fails again, ask the user.

### Tools you may use in Phase C

From `autocodabench`:

- `autocodabench_init_bundle(slug)` — call once, at the start.
- `autocodabench_write_competition_yaml(slug, body)` — the master file.
- `autocodabench_write_page(slug, name, body)` — overview/evaluation/terms/data pages.
- `autocodabench_write_scoring_program(slug, score_py, metadata_yaml)` — the score.py + metadata.yaml in `scoring_program/`.
- `autocodabench_write_ingestion_program(slug, ingestion_py, metadata_yaml)` — optional; only if the spec calls for code-submission ingestion.
- `autocodabench_write_solution(slug, files)` — the worked baseline shipped as the starting kit.
- `autocodabench_attach_data(slug, kind, files)` — `kind` is `reference_data`, `input_data`, or `public_data`; populates the corresponding subdir.
- `autocodabench_validate_bundle(slug)` — local lint pass. Run after writes finish.
- `autocodabench_zip_bundle(slug)` — produces the final `.zip`. Run only after validate is clean.
- `autocodabench_upload_bundle(slug)` — publishes to Codabench. **Run only if the user explicitly asks to publish.**

You may also `Read`, `Grep`, `Glob` files on disk. You may NOT shell
out, write outside the run dir, or make network calls other than via
`autocodabench_upload_bundle`.

---

## 3. Subagents (if `/agents` is available)

When the runtime is the Claude Code CLI, the plan may name subagents
to run steps in parallel. Spawn them via `/agents`. Typical layout:

| Subagent           | Tool scope                         | Output                                  |
|--------------------|------------------------------------|-----------------------------------------|
| `data-curator`     | `autocodabench_attach_data`        | `reference_data/`, `input_data/`        |
| `scoring-author`   | `autocodabench_write_scoring_program` | `scoring_program/score.py` + meta     |
| `pages-author`     | `autocodabench_write_page`         | overview / evaluation / terms / data    |
| `baseline-author`  | `autocodabench_write_solution`     | starting-kit solution                   |
| `bundle-assembler` | `autocodabench_write_competition_yaml` | master `competition.yaml`           |
| `bundle-validator` | `autocodabench_validate_bundle`    | runs lint, fixes issues, retries        |
| `packager`         | `autocodabench_zip_bundle`         | the final `.zip` at the bundle root     |
| `meta-reviewer`    | read-only on `<run>/`              | `<run>/artifacts/meta-reviewer/report.md` |

When the runtime is the **web UI**, `/agents` is not available —
execute steps serially in this same chat. Don't pretend subagents are
running; the user will see your tool chips directly.

---

## 4. Validate, then zip

After the last write step:

```
autocodabench_validate_bundle(slug)
```

If it fails, address the *specific* issue it flagged (e.g. a missing
referenced file, a leaderboard column key not matching `scores.json`),
re-write the affected file, and re-validate. Do not proceed to zip
with validation errors.

Once `validate_bundle` returns clean:

```
autocodabench_zip_bundle(slug)
```

returns the path to the final `.zip`.

---

## 5. (Optional) Publish to Codabench

Only if the user explicitly asks ("publish", "upload", "push to
Codabench"):

```
autocodabench_upload_bundle(slug)
```

needs `CODABENCH_USERNAME` + `CODABENCH_PASSWORD` (or `CODABENCH_TOKEN`)
in env. Returns `{"competition_id": ..., "competition_url": "https://www.codabench.org/competitions/<id>/"}`.

Surface the URL prominently to the user.

---

## 6. Closing message

Send the user a compact summary:

```
✅ Bundle ready.

  bundle file       — <run>/bundles/<slug>/<slug>.zip
  validate_bundle   — passed
  files written     — <n>
  steps executed    — <n_steps from plan>
  codabench URL     — <only if uploaded>

  full log          — <run>/transcript.md
  raw tool inputs   — <run>/tool_calls/
  meta-reviewer     — <run>/artifacts/meta-reviewer/report.md
                      (if you spawned that subagent)
```

Then call:

```
autocodabench_log_event(kind="phase_c_done",
                        payload={"zip_path": "...",
                                 "validated": true,
                                 "uploaded": <bool>,
                                 "competition_url": "<url or null>"})
```

and **stop**. The session is complete.

---

## 7. Hard rules

1. **Read the four artifact families first.** Never call a write tool
   before reading the relevant spec.
2. **No new design decisions.** If a spec is ambiguous, ASK the user
   in plain prose — don't invent defaults silently.
3. **Validate before you zip.** Never zip a bundle that
   `validate_bundle` complained about.
4. **Upload only on explicit request.** `autocodabench_upload_bundle`
   makes a public Codabench competition; it must be a deliberate user
   action.
5. **Stay in this run dir.** All writes are scoped to
   `<run>/bundles/<slug>/`. Don't touch anything outside.
