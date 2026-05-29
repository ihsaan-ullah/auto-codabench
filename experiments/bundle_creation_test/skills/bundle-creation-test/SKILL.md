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

### 7. Finalize

- Set `finished_at` to current ISO-UTC.
- Set `overall_status = "pass"` if every step (incl. every sub_N in
  step 5) passed, else `fail_at_<first_failed_step>`.
- Write the final manifest.json.
- Print a one-paragraph summary + the table below.

## Output format to the user

```
Experiment: <comp> · run_id: <run_id> · status: pass | fail_at_<step>

| step       | status | notes                                                          |
|------------|--------|----------------------------------------------------------------|
| plan       | pass   | sections: task, data, metric, baseline, rules, ethics, schedule|
| implement  | pass   | slug: <slug>, bundle <N> KB, validator-clean=true              |
| validate   | pass   | exit 0                                                         |
| sub_1      | pass   | actual 0.000, expected 0.000, Δ 0.000 (within 0.001 tolerance) |
| sub_2      | pass   | actual 0.303, expected 0.303, Δ 0.000 (within 0.001 tolerance) |
| ...        | ...    |                                                                |

run dir: ./experiments/bundle_creation_test/runs/<comp>/<run_id>/
```
