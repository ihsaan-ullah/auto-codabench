# bundle_creation_test

End-to-end test harness for AutoCodabench: feed it a paper/proposal, watch
it plan → build → validate → submit a known-good solution, and check whether
the resulting score matches a pre-recorded ground truth (within tolerance).

This is a **wrapper** around `auto_codabench/`. We do not modify the
package or the skills here — we orchestrate Claude subagents that use them,
copy logs out into the experiment dir, and add a final
"does-a-known-submission-score-correctly" gate that doesn't exist in the
production web flow.

Future experiments (latency, cost, robustness, etc.) live in sibling
`experiments/<other_name>/` folders. They can reuse the same agent topology
or define their own.

---

## Five-step pipeline (per experiment run)

| # | Step | Agent | Reads | Writes |
|---|------|-------|-------|--------|
| 1 | Input | _(orchestrator)_ | `<comp>/input/` exists check | manifest precondition |
| 2 | Plan | `bundle-planner` | `<comp>/input/**` | `<run>/plan/implementation_plan.md` |
| 3 | Implement | `bundle-implementer` | `<run>/plan/implementation_plan.md` only | `<run>/bundle/<slug>/...` + `.zip` |
| 4 | Validate | `bundle-validator-runner` | `<run>/bundle/**` + `bundle_validator.py` | `<run>/validation/report.txt` |
| 5a | Reformat submission | `submission-reformatter` | `<comp>/sample_submission.py` + bundle's interface contract | `<run>/reformatted_submission/submission.py` |
| 5b | Run + compare | `submission-runner` | reformatted submission + bundle + `<comp>/expected_result.json` | `<run>/submission_run/score.json` + tolerance check |

Every step is a **fresh subagent** spawned by `bundle-experiment-runner` via
the Task tool. No two subagents share chat context, and each one is locked
down by `tools` / `allowedTools` / `permissionMode: dontAsk` to **only** see
the slice of disk relevant to its job. The motivating constraint:

- **Planner and implementer must not see the test submission** (would let
  them overfit the bundle to it).
- **Reformatter must not see the plan or planning chat** (would let it
  smuggle ground-truth labels into the submission).
- **Runner must not see the plan** for the same reason.

The orchestrator is the only agent with broad filesystem access inside
`experiments/bundle_creation_test/`; it strictly passes file paths to
subagents and never reads their forbidden inputs itself.

---

## Layout

```
experiments/bundle_creation_test/
├── README.md                        # this file
├── bundle_validator.py              # validator script (vendored, used by step 4)
├── setup.sh                         # one-time: symlinks agents into .claude/agents/
├── agents/                          # source of truth for the 6 subagent definitions
│   ├── bundle-experiment-runner.md
│   ├── bundle-planner.md
│   ├── bundle-implementer.md
│   ├── bundle-validator-runner.md
│   ├── submission-reformatter.md
│   └── submission-runner.md
└── <competition_sample_name>/       # one folder per competition you're testing
    ├── input/                       # paper/proposal PDF + supplementary text
    ├── sample_submission.py         # ground-truth submission (any working version)
    ├── expected_result.json         # {"score": float, "tolerance": float, "metric": "..."}
    └── <branch_short_sha>_<utc_ts>/ # one folder per experiment RUN, created by the orchestrator
        ├── manifest.json            # step-by-step result log
        ├── plan/                    # bundle-planner output
        │   ├── implementation_plan.md
        │   └── auto_codabench_run/  # full MCP audit trail (events.jsonl, tool_calls/, specs/)
        ├── bundle/                  # bundle-implementer output
        │   └── <slug>/
        │       ├── competition.yaml
        │       ├── scoring_program/
        │       ├── solutions/sample_code_submission/model.py   # ← interface contract for step 5a
        │       └── ... (everything Codabench needs)
        ├── validation/
        │   └── report.txt           # validator stdout + exit code
        ├── reformatted_submission/
        │   └── submission.py        # ground-truth logic rewrapped to bundle's interface
        └── submission_run/
            ├── sandbox/             # ephemeral workspace for the score program
            ├── stdout.txt
            ├── stderr.txt
            └── score.json           # parsed scores + delta-vs-expected
```

---

## One-time setup

```bash
bash experiments/bundle_creation_test/setup.sh
```

This creates relative symlinks `.claude/agents/<name>.md →
../../experiments/bundle_creation_test/agents/<name>.md` so Claude Code
picks them up under their standard discovery path. It also makes sure
`.claude/skills/autocodabench-plan` is symlinked to
`auto_codabench/skills/plan/` (the skill name and dir name differ).

`.claude/` stays gitignored apart from the symlinks pointing back here.

---

## Adding a new competition sample

```bash
mkdir -p experiments/bundle_creation_test/my-competition/input
# put your paper / proposal PDF + any supporting text under input/
cp /path/to/my_solution.py experiments/bundle_creation_test/my-competition/sample_submission.py
cat > experiments/bundle_creation_test/my-competition/expected_result.json <<'JSON'
{ "score": 0.873, "tolerance": 0.01, "metric": "accuracy" }
JSON
```

`expected_result.json` is **optional but recommended**. Without it,
step 5b only checks "did the submission execute and produce a valid
scores.json"; with it, the run is marked `pass` only if
`|actual - expected| ≤ tolerance`.

---

## Running an experiment

From a fresh Claude Code session in the repo root:

> Run the bundle-creation experiment on `my-competition`.

The main session will delegate to the `bundle-experiment-runner` agent (or
you can invoke it explicitly with `/agents` → run-as → bundle-experiment-runner).
The orchestrator:

1. Computes a `run_id` = `<short_sha>_<utc_ts>`.
2. Creates `experiments/bundle_creation_test/my-competition/<run_id>/` and
   writes an initial `manifest.json`.
3. Spawns the 5 subagents in order, passing **paths only** — never content.
4. After each subagent returns, parses its JSON final message into
   `manifest.steps[]` and updates `overall_status`.
5. On the first failure, records the failed step and stops.
6. On success, the experiment dir contains everything reviewable
   independently: plan, bundle, validator report, reformatted submission,
   and the score with its delta-from-expected.

You can have multiple experiment runs per competition sample (one per
`<run_id>` subdir) — they're keyed by branch SHA + timestamp so two runs
on the same commit are still distinguishable by time.

---

## Manifest schema

```json
{
  "competition_sample_name": "my-competition",
  "run_id": "abc1234_20260530_142233",
  "branch": "experiment_test-bundle-creation",
  "started_at": "2026-05-30T14:22:33Z",
  "finished_at": "2026-05-30T14:38:01Z",
  "expected_result": { "score": 0.873, "tolerance": 0.01, "metric": "accuracy" },
  "steps": [
    {
      "name": "plan", "status": "pass",
      "agent_summary": "...",
      "artifacts": ["plan/implementation_plan.md"]
    },
    {
      "name": "implement", "status": "pass",
      "artifacts": ["bundle/<slug>/", "bundle/<slug>/<slug>.zip"]
    },
    {
      "name": "validate", "status": "pass",
      "exit_code": 0,
      "artifacts": ["validation/report.txt"]
    },
    {
      "name": "reformat", "status": "pass",
      "interface_summary": "class Model: def fit(X, y) / def predict(X) → ndarray",
      "artifacts": ["reformatted_submission/submission.py"]
    },
    {
      "name": "run", "status": "pass",
      "score": 0.871, "expected": 0.873, "delta": 0.002,
      "within_tolerance": true,
      "artifacts": ["submission_run/score.json", "submission_run/stdout.txt"]
    }
  ],
  "overall_status": "pass"
}
```

On failure, `overall_status` becomes `fail_at_<step_name>` and the
failing step's entry includes the subagent's verbatim error message.

---

## Permission model (TL;DR)

| Agent | Tools | What it can read | What it can write |
|---|---|---|---|
| `bundle-experiment-runner` | Read, Write, Edit, Bash (narrow), Task | All of `experiments/bundle_creation_test/**`, `auto_codabench/runs/**` | `<run>/**` only |
| `bundle-planner` | Read, Write, Edit, Glob, Grep, Skill, MCP autocodabench + alex-mcp, WebFetch, WebSearch | `<comp>/input/**`, `auto_codabench/skills/**`, the current run's `plan/**` | `<run>/plan/**` only |
| `bundle-implementer` | Read, Write, Edit, Glob, Grep, Skill, MCP autocodabench | `<run>/plan/implementation_plan.md` (the **only** plan-side file), `auto_codabench/skills/**`, the current run's `bundle/**` | `<run>/bundle/**` only |
| `bundle-validator-runner` | Read, Write, Bash (`python ./experiments/bundle_creation_test/bundle_validator.py:*`) | `<run>/bundle/**`, the validator script | `<run>/validation/**` only |
| `submission-reformatter` | Read, Write, Edit, Glob, Grep | `<comp>/sample_submission.py`, `<run>/bundle/**` | `<run>/reformatted_submission/**` only |
| `submission-runner` | Read, Write, Bash (narrow) | `<run>/bundle/**`, `<run>/reformatted_submission/**`, `<comp>/expected_result.json` | `<run>/submission_run/**` only |

`permissionMode: dontAsk` in every agent: anything outside the allowlist is
a hard deny, **not** a permission prompt — important for unattended runs.

Known limitation: agents with `Bash` access can in principle read any file
their shell can reach. We mitigate by giving Bash only to the two agents
that genuinely need it (validator-runner, submission-runner) and scoping
their Bash patterns narrowly (`Bash(python:*)`, `Bash(python ./experiments/bundle_creation_test/bundle_validator.py:*)`). The
planner, implementer, and reformatter have **no Bash at all** — they
operate purely through Read/Write/Edit and MCP tools.

---

## Logs from the MCP server

When the planner/implementer call `autocodabench_open_run`, they pass
`run_dir=<run>/<step>/auto_codabench_run`, so the MCP server's full audit
trail (`events.jsonl`, `tool_calls/`, `specs/`) lands directly inside the
experiment dir. No post-hoc copying needed; the artifacts are already
co-located with the rest of the run.

If a future change to `auto_codabench/` breaks the `run_dir` parameter,
the orchestrator falls back to `cp -r auto_codabench/runs/<latest>
<run>/<step>/auto_codabench_run/` after the subagent returns. Both paths
are documented in the orchestrator's body.
