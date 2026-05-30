---
name: bundle-creation-test
description: End-to-end bundle-creation test experiment runner. Load this skill when the user says something like "run the bundle-creation experiment on <competition_sample_name>" or "test the autocodabench bundle pipeline against <comp>". You orchestrate a 5-step pipeline (plan → implement → validate → reformat → run+compare) by spawning 5 isolated stage subagents via the Task tool and writing a per-step manifest under `experiments/bundle_creation_test/runs/<comp>/<run_id>/`. This skill MUST run in the top-level Claude Code session (it spawns subagents — subagents themselves cannot spawn further subagents).
---

You are running the bundle-creation-test experiment harness defined in
[`experiments/bundle_creation_test/README.md`](../../README.md). Read that
file first if you have not already — it has the full layout, agent
topology, and manifest schema.

## What this skill does (and why it's a skill, not an agent)

You — the top-level Claude Code session, with this skill loaded — are the
orchestrator. You receive a `competition_sample_name` from the user's
message (e.g. `style-trans-fair`), compute a `run_id`, create the run
dir, and sequence five subagents via the Task tool. The five subagents
ARE agents (in `.claude/agents/`) because each one needs an isolated
context with scoped permissions. The orchestrator is NOT an agent
because:

- the orchestrator needs the `Task` tool to spawn the five subagents
- Claude Code's `Task` is **unavailable inside subagents** (one level
  down) — so an "orchestrator agent" can only ever sit at the top level
- skills, by contrast, are loaded into the top-level conversation by
  design — they are instructions Claude follows, not isolated contexts.
  When this skill is loaded, the Task tool stays available, the
  isolation chain works, and the architecture composes.

If you ever find yourself in a context where `Task` is missing, you are
not at the top level — stop, report `fail_at_preconditions` with the
error "must be invoked at top-level Claude Code session", and let the
human re-invoke from the right place.

## Hard rules — data leakage prevention

These exist because the whole experiment is only valid if the
isolation chain holds. Violating them invalidates the comparison
between the agent-generated bundle's score and the expected_result.

- **You MUST NOT read `<comp>/input/**`** — not even to "summarise for a
  subagent". The `bundle-planner` subagent reads it; you pass only its
  path. Top-level reading would leak the paper's design intent into the
  prompt you craft for downstream subagents.
- **You MUST NOT read `<comp>/ground_truth/bundle/**`** — that's the
  golden reference bundle, reserved for human comparison.
- **You MUST NOT read `<comp>/ground_truth/sample_submissions/*/submission/**`** —
  the `submission-reformatter` subagent reads it. Only its sibling
  `expected_result.json` is readable by you (for recording in the
  manifest).
- **You MUST NOT pass content from one subagent into another** as part
  of the prompt. Pass file paths; let each subagent read what its own
  `allowedTools` permit. This is the whole point of the isolation
  design.
- **Write only inside `runs/<comp>/<run_id>/`.** Source materials under
  `competitions/<comp>/` are immutable from your perspective.
- **Single-invocation rule**: one skill activation = one experiment run.
  Compute one `run_id`, create one dir, run all steps. If the user
  wants 3 runs, they ask 3 times.
- **No retries inside a step.** If a subagent fails in steps 1–4,
  record the failure in `manifest.json` and stop with
  `overall_status = "fail_at_<step>"`. Step 5 is special — see below.

## What you receive

A `competition_sample_name` (the subdir name under
`experiments/bundle_creation_test/competitions/`). Example:
`style-trans-fair`.

## Pipeline

### 0. Compute run_id and create the run dir

```bash
SHORT_SHA=$(git rev-parse --short=8 HEAD)
UTC_TS=$(date -u +%Y%m%d_%H%M%S)
RUN_ID="${SHORT_SHA}_${UTC_TS}"
BRANCH=$(git branch --show-current)
mkdir -p experiments/bundle_creation_test/runs/<comp>/${RUN_ID}/{plan,bundle,validation,reformatted_submission,submission_run}
```

(The run_id starts with a hex character — this matches the
`runs/*/[0-9a-f]*/...` glob each stage agent's `allowedTools` uses.)

Write `experiments/bundle_creation_test/runs/<comp>/<run_id>/manifest.json`:

```json
{
  "competition_sample_name": "<comp>",
  "run_id": "<run_id>",
  "branch": "<branch>",
  "started_at": "<iso-utc>",
  "finished_at": null,
  "expected_results": {},
  "steps": [],
  "overall_status": "in_progress"
}
```

### 1. Preconditions

- `<comp>/input/` exists and is non-empty:
  `ls experiments/bundle_creation_test/competitions/<comp>/input/`
  returns at least one entry. You can ls but **NOT read** those entries.
- Discover ground-truth submissions:
  `ls experiments/bundle_creation_test/competitions/<comp>/ground_truth/sample_submissions/`
  returns at least one `sub_N` dir.
- For each `sub_N`, read `sub_N/expected_result.json`, validate it has
  the keys `metric` / `score` / `tolerance`, and populate
  `manifest.expected_results[sub_N]`. If a sub_N is missing its
  expected_result.json or it's malformed: precondition failure for
  that sub.
- On any precondition failure: write
  `overall_status = "fail_at_preconditions"`, add a step entry with
  the error, exit.

### 2. Spawn `bundle-planner` via Task

Prompt (substitute `<comp>` and `<run_id>` literally):

> Run AutoCodabench Phase 1.
>
> input_dir: `./experiments/bundle_creation_test/competitions/<comp>/input/`
> plan_dir:  `./experiments/bundle_creation_test/runs/<comp>/<run_id>/plan/`
>
> Use `run_dir=./experiments/bundle_creation_test/runs/<comp>/<run_id>/plan/auto_codabench_run`
> when calling `autocodabench_open_run`. Write the final plan as
> `./experiments/bundle_creation_test/runs/<comp>/<run_id>/plan/implementation_plan.md`.
> Your final message MUST be the JSON object specified in your skill body.

When it returns, parse its JSON final message. Append a `steps` entry:
`{name: "plan", status, started_at, finished_at, agent_summary, artifacts}`.
If `status == "fail"`, set `overall_status = "fail_at_plan"` and stop.

### 3. Spawn `bundle-implementer` via Task

Prompt:

> Run AutoCodabench Phase 2.
>
> plan_path:  `./experiments/bundle_creation_test/runs/<comp>/<run_id>/plan/implementation_plan.md`
> sample_data_dir: `./experiments/bundle_creation_test/competitions/<comp>/input/sample_data/` (read-only reference for dataset shape)
> bundle_dir: `./experiments/bundle_creation_test/runs/<comp>/<run_id>/bundle/`
>
> Use `run_dir=./experiments/bundle_creation_test/runs/<comp>/<run_id>/bundle/auto_codabench_run`
> for the MCP open_run call. Final message: the JSON object specified
> in your skill body.

Stop on fail.

### 4. Spawn `bundle-validator-runner` via Task

Prompt:

> Run `bundle_validator.py` against the bundle at
> `./experiments/bundle_creation_test/runs/<comp>/<run_id>/bundle/<slug>/`
> (you'll find the slug by listing `<run>/bundle/`). Write report to
> `./experiments/bundle_creation_test/runs/<comp>/<run_id>/validation/report.txt`.

Stop on fail.

### 5. Per-submission reformat + run (loop over every sub_N)

For each `sub_N` directory under
`<comp>/ground_truth/sample_submissions/`:

#### 5a. Spawn `submission-reformatter` via Task

Prompt:

> Reformat the ground-truth submission code under
> `./experiments/bundle_creation_test/competitions/<comp>/ground_truth/sample_submissions/<sub_N>/submission/`
> to match the interface at
> `./experiments/bundle_creation_test/runs/<comp>/<run_id>/bundle/<slug>/solutions/sample_code_submission/model.py`
> (or whatever the bundle's submission interface is — read the bundle).
> Output to `./experiments/bundle_creation_test/runs/<comp>/<run_id>/reformatted_submission/<sub_N>/`.

#### 5b. Spawn `submission-runner` via Task

Prompt:

> Execute the reformatted submission at
> `./experiments/bundle_creation_test/runs/<comp>/<run_id>/reformatted_submission/<sub_N>/`
> through the scoring program in
> `./experiments/bundle_creation_test/runs/<comp>/<run_id>/bundle/<slug>/scoring_program/`.
> Compare against
> `./experiments/bundle_creation_test/competitions/<comp>/ground_truth/sample_submissions/<sub_N>/expected_result.json`.
> Write artifacts to
> `./experiments/bundle_creation_test/runs/<comp>/<run_id>/submission_run/<sub_N>/`.

Aggregate into a single `steps` entry:

```json
{
  "name": "reformat_and_run",
  "status": "pass" | "fail",
  "submissions": [
    {
      "sub": "sub_1",
      "reformat_status": "...", "interface_summary": "...",
      "run_status": "...", "score": ..., "expected": ..., "delta": ..., "within_tolerance": ...,
      "artifacts": ["reformatted_submission/sub_1/...", "submission_run/sub_1/score.json"]
    }
  ]
}
```

The top-level `status` is `pass` iff every sub_N's
`run_status == "pass"` AND every `within_tolerance == true`. Otherwise
`fail`. **Run all subs before deciding** — partial failure should not
skip the remaining subs; the user wants to see the full pattern.

### 6. Fallback log copy (only if needed)

If a step's `auto_codabench_run/` subdir is empty (the MCP server fell
back to the default `auto_codabench/runs/<id>/` location), find run
dirs in `auto_codabench/runs/` whose mtime is between `started_at` and
`now` and `cp -r` them into the step's dir. Use `stat -f %m` on macOS
or `stat -c %Y` on Linux.

### 7. Aggregate the missing-info inventories

This step turns per-stage inventories into one run-level report that
downstream meta-analysis consumes. The schema is defined in
[`MISSING_INFO.md`](../../MISSING_INFO.md); read it first if you have
not already — it specifies the controlled vocabulary, per-item shape,
and aggregated-report shape.

Process:

1. Read both stage inventories (if they exist):
   - `runs/<comp>/<run_id>/plan/missing_info_inventory.json`
     (always present unless the planner stage hard-failed before
     emitting it).
   - `runs/<comp>/<run_id>/bundle/missing_info_inventory.json`
     (present if the implementer stage ran).
2. If neither exists (e.g., plan stage hard-failed pre-emit), write a
   stub `missing_info_report.json` with an empty `items: []` and a
   `narrative_summary` explaining why the data is missing. Do NOT
   skip this step — the meta-analysis pipeline needs the file to
   exist for every run (it can group runs by "had inventory" vs
   "didn't" to surface pre-emit failure patterns).
3. Concatenate the items from both stages into a single `items`
   array. Re-tag each item with its `stage` field (the per-stage
   inventories already do this, but double-check). Re-ID items so
   ids are unique across the merged list (e.g.
   `planner_miss_001`, `implementer_miss_001`).
4. Compute the totals block per the schema. The totals are what most
   meta-analysis queries hit first; they MUST match the items array's
   actual contents (no silent fudging).
5. Write a `narrative_summary` (1–3 sentences). Lead with the count
   of critical / high-stakes items. Call out any
   `would_block_correct_scoring == true` items by name. Mention
   overall_proposal_completeness if available.
6. Write `runs/<comp>/<run_id>/missing_info_report.json` per the
   aggregated-report shape in MISSING_INFO.md.
7. Add a `missing_info_summary` block to `manifest.json` with the
   top-line numbers (just `totals` from the report — keeps manifest
   compact while the full report sits alongside).

### 8. Finalize

- Set `finished_at` to current ISO-UTC.
- Set `overall_status = "pass"` if every step (incl. every sub_N in
  step 5) passed, else `fail_at_<first_failed_step>`.
- Write the final `manifest.json`.
- Write `run_report.md` (next section) — this is the human-readable
  twin of `manifest.json` + `missing_info_report.json` and is the
  single file a reviewer opens to understand the run.
- Print the one-paragraph summary + the table from "Output format to
  the user" below.

### 9. Write `run_report.md` (human-readable run summary)

This file is the primary deliverable for human reviewers. The
structured forms (`manifest.json`, `missing_info_report.json`) are for
machines and meta-analysis; `run_report.md` is for a person who wants
to understand one run in one screen without parsing JSON.

Path: `runs/<comp>/<run_id>/run_report.md`. Write it EVERY run, even
on failure (especially on failure — the report is more useful when
the manifest's `overall_status` is non-pass).

The content is sourced entirely from data you already have:
- the manifest you just wrote (steps + status + timing)
- the missing_info_report.json you wrote in step 7
- each subagent's verbatim JSON final message (from Task results)
- any environment notes you noticed across the subagent reports
  (e.g., "implementer reported MCP unavailable and fell back to X")

Use this template — fill in everything in braces, preserve section
headings verbatim so meta-analysis tools can grep across reports:

```markdown
# Run report — bundle-creation-test

**Competition:** {comp}
**Run ID:** {run_id}
**Branch:** {branch}
**Started:** {started_at}
**Finished:** {finished_at} ({duration_human, e.g. "6m 4s"})
**Overall status:** {overall_status}

---

## Summary table

| step       | status | notes |
|------------|--------|-------|
| plan       | {pass|fail|—} | {one-line: sections covered, citation count, info-gap counts (X critical, Y would-block-scoring), completeness} |
| implement  | {pass|fail|—} | {one-line: slug, bundle size, validator-clean=Y/N, plan-gap count} |
| validate   | {pass|fail|—} | {one-line: exit code, first error if any} |
| sub_<N>    | {pass|fail|—} | {one-line per sub_N: actual vs expected, delta, within_tolerance} |
| ...        | ...    | ... |

(Rows for stages that never ran show status `—` and a "not reached"
note. Don't omit them — the table's row pattern is part of the
contract for cross-run rendering.)

---

## What happened

{1–3 paragraphs of orchestrator's analysis. What each step did, what
passed, what failed and why. If status is `fail_at_<step>`, explicitly
state what the failure means and why no recovery was attempted (per
the skill's no-retry-inside-a-step rule). Be concrete about the defect
(e.g. "leaderboard at position 0 missing 'index'") rather than
hand-wavy ("validator failed").}

---

## Environment notes

{Anything subagents reported in their JSON `notes` or `error` fields
that looks like environment / configuration issues worth a human's
attention. Examples: "MCP server absent from subagent sandbox",
"Skill() call returned no body", "Bash blocked by permissionMode".
If everything was nominal, write: "No environment anomalies reported."}

---

## Missing-info summary

**Total:** {N} items ({P} from planner, {I} from implementer)

- by impact_area: bundle_functionality={A}, deployment_polish={B}, participant_experience={C}
- by severity: critical={X}, important={Y}, nice_to_have={Z}, best_practice={W}
- by resolution.action: inferred={inf}, default_applied={da}, deferred={def}, omitted={om}
- would_block_correct_scoring: {K} — high-stakes inferences worth a human pass
- would_have_asked_user_if_interactive: {Q}

### Highest-stakes items (would_block_correct_scoring == true)

(Pulled directly from missing_info_report.json. Cap at the top 10;
if more, add "and N more — see missing_info_report.json". If zero,
write "None — all inferences were judged low-stakes.")

1. **{section}.{field}** ({severity}, confidence={conf})
   - Missing: {what_was_missing}
   - Filled: {resolution.choice}
   - Rationale: {resolution.rationale}
2. ...

---

## Headline inferences (highest-impact non-blocking)

(Top 3–5 items where `would_block_correct_scoring=false` but the
choice still meaningfully shaped the bundle — e.g., the GPU/CNN
→ CPU/sklearn re-casting in the 5/30 run. Cap at 5; quote the
planner's rationale verbatim.)

1. **{section}.{field}**: {choice} — {short rationale}

---

## Artifacts

- Plan: `plan/implementation_plan.md`
- Plan audit trail: `plan/auto_codabench_run/` ({"populated" | "empty — MCP unavailable to planner subagent"})
- Bundle: `bundle/{slug}/` ({size_kb} KB)
- Bundle audit trail: `bundle/auto_codabench_run/` ({"populated" | "empty — MCP unavailable to implementer subagent"})
- Bundle zip: `bundle/{slug}/{slug}.zip` ({"produced by implementer" | "produced by orchestrator fallback" | "not produced"})
- Validation report: `validation/report.txt`
- Reformatted submissions: `reformatted_submission/` ({K} subs)
- Submission runs: `submission_run/` ({K} subs)
- Missing-info report: `missing_info_report.json` ({N} items)
- Manifest: `manifest.json`

---

## Run dir

`./experiments/bundle_creation_test/runs/{comp}/{run_id}/`
```

Write the final report to disk, THEN print the summary table to the
user. The summary table to the user is essentially the same content
as the report's "Summary table" + "Missing-info summary" sections —
keeping them in sync lets reviewers cross-reference what they saw in
the chat against what landed on disk.

## Output format to the user

```
Experiment: <comp> · run_id: <run_id> · status: pass | fail_at_<step>

| step       | status | notes                                                          |
|------------|--------|----------------------------------------------------------------|
| plan       | pass   | 7 sections, N citations, M info gaps (X critical)              |
| implement  | pass   | slug: <slug>, bundle <N> KB, validator-clean=true, K plan-gaps |
| validate   | pass   | exit 0                                                         |
| sub_1      | pass   | actual 0.000, expected 0.000, Δ 0.000 (within 0.001 tolerance) |
| sub_2      | pass   | actual 0.303, expected 0.303, Δ 0.000 (within 0.001 tolerance) |
| ...        | ...    |                                                                |

Missing-info report: <M+K> items total
  by impact:    bundle_functionality=A, deployment_polish=B, participant_experience=C
  by severity:  critical=X, important=Y, nice_to_have=Z, best_practice=W
  would_block_correct_scoring: <count> ← high-stakes inferences worth a human pass
Full report: runs/<comp>/<run_id>/missing_info_report.json

run dir: ./experiments/bundle_creation_test/runs/<comp>/<run_id>/
```
