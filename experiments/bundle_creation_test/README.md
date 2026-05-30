# bundle_creation_test

End-to-end test harness for AutoCodabench: feed it a paper/proposal, watch
it plan → build → validate → submit a known-good solution, and check whether
the resulting score matches a pre-recorded ground truth (within tolerance).

This is a **wrapper** around `auto_codabench/`. We do not modify the
package or the skills here — we orchestrate Claude subagents that use them,
co-locate logs in the experiment dir, and add a final
"does-a-known-submission-score-correctly" gate that doesn't exist in the
production web flow.

Future experiments (latency, cost, robustness, etc.) live in sibling
`experiments/<other_name>/` folders. They can reuse the same agent topology
or define their own.

---

## Layout

```
experiments/bundle_creation_test/
├── README.md                            # this file
├── MISSING_INFO.md                      # schema + conventions for the missing-info inventory
│                                        #   logged by planner/implementer and aggregated by the skill;
│                                        #   read this before changing any of the inventory shapes.
├── bundle_validator.py                  # validator script (vendored, used by step 4)
├── setup.sh                             # one-time: symlinks agents+skill into .claude/
├── scripts/
│   └── aggregate_missing_info.py        # cross-run meta-analysis over missing_info_report.json files
│                                        #   (see MISSING_INFO.md §"Meta-analysis pattern" for jq alternatives)
├── skills/
│   └── bundle-creation-test/
│       └── SKILL.md                     # ORCHESTRATOR — loaded into top-level conversation;
│                                        #   it drives the 5-step pipeline and spawns the
│                                        #   5 subagents below via the Task tool.
│                                        #   Has to be a skill (not an agent) because the
│                                        #   Task tool is unavailable inside subagents.
├── agents/                              # the 5 stage subagent definitions
│   ├── bundle-planner.md                #   Phase 1
│   ├── bundle-implementer.md            #   Phase 2
│   ├── bundle-validator-runner.md       #   step 4
│   ├── submission-reformatter.md        #   step 5a
│   └── submission-runner.md             #   step 5b
└── competitions/                        # one subdir per competition sample
    └── <competition_sample_name>/       # e.g. style-trans-fair/
        ├── input/                       # accessible to planner; sample_data/ also to implementer + runner
        │   ├── report.pdf               # the proposal paper — planner reads only
        │   └── sample_data/             # public dataset — planner / implementer / runner can read
        │       ├── content/
        │       ├── styles/
        │       ├── stylized/
        │       ├── tasks/
        │       └── info.json
        ├── ground_truth/                # OFF-LIMITS to planner & implementer
        │   ├── bundle/                  # GOLDEN reference bundle — OFF-LIMITS to ALL agents
        │   │   ├── competition.yaml     #   (lives here so a human can verify the agents'
        │   │   ├── scoring_program/     #    output against the canonical Codabench bundle)
        │   │   ├── ingestion_program/
        │   │   ├── reference_data/
        │   │   └── ...
        │   └── sample_submissions/      # ground-truth submissions to score the generated bundle
        │       └── sub_<N>/             # one folder per ground-truth submission
        │           ├── submission/      # the actual submission code — reformatter reads only
        │           │   ├── model.py
        │           │   └── ...
        │           └── expected_result.json   # the score this submission produced on the
        │                                      # real Codabench — runner reads only
        └── <branch_short_sha>_<utc_ts>/ # one folder per experiment RUN, created by orchestrator
            ├── manifest.json
            ├── plan/                    # bundle-planner output
            │   ├── implementation_plan.md
            │   └── auto_codabench_run/  # full MCP audit trail
            ├── bundle/
            │   └── <slug>/
            │       ├── competition.yaml
            │       ├── scoring_program/
            │       ├── solutions/sample_code_submission/model.py   # interface contract for reformatter
            │       └── ...
            ├── validation/
            │   └── report.txt
            ├── reformatted_submission/
            │   └── sub_<N>/             # one subdir per ground-truth submission
            │       └── submission.py
            └── submission_run/
                └── sub_<N>/             # one subdir per ground-truth submission
                    ├── sandbox/         # ephemeral execution workspace
                    ├── stdout.txt
                    ├── stderr.txt
                    └── score.json       # parsed scores + delta-vs-expected
```

---

## Five-step pipeline (per experiment run)

| # | Step | Agent | Reads | Writes |
|---|------|-------|-------|--------|
| 1 | Input | _(orchestrator)_ | `<comp>/input/` exists check | manifest precondition |
| 2 | Plan | `bundle-planner` | `<comp>/input/**` (incl. sample_data) | `<run>/plan/implementation_plan.md` |
| 3 | Implement | `bundle-implementer` | `<run>/plan/implementation_plan.md` + `<comp>/input/sample_data/**` only | `<run>/bundle/<slug>/...` + `.zip` |
| 4 | Validate | `bundle-validator-runner` | `<run>/bundle/**` + `bundle_validator.py` | `<run>/validation/report.txt` |
| 5 | Reformat + run per submission | `submission-reformatter` then `submission-runner`, **looped over every `<comp>/ground_truth/sample_submissions/sub_*/`** | reformatter: `sub_N/submission/**` + bundle interface; runner: reformatted submission + bundle + `sub_N/expected_result.json` | `<run>/reformatted_submission/sub_N/`, `<run>/submission_run/sub_N/score.json` |

Every step is a **fresh subagent** spawned by the `bundle-creation-test`
skill (loaded into the top-level Claude Code session) via the Task tool.
No two subagents share chat context, and each one is locked down by
`tools` / `allowedTools` / `permissionMode: dontAsk` so it can **only**
see the slice of disk relevant to its job. The motivating constraint:

- **Planner can read the paper AND sample_data**, but cannot read any
  ground-truth submission or its expected score (would let it overfit the
  plan to the test).
- **Implementer reads only `implementation_plan.md` and `sample_data/`** —
  no paper, no test submission. This forces the bundle to be built from
  the locked plan, not from re-reading the user's intent.
- **Reformatter reads only the bundle's interface and the ground-truth
  submission's code**. It has no view into the plan, the paper, or the
  expected score — so it cannot smuggle answers into the submission.
- **Runner reads the reformatted submission, the bundle, and the
  expected_result.json** — but not the ground-truth submission's source
  code (it's already been adapted by the reformatter).
- **The golden bundle under `ground_truth/bundle/` is off-limits to
  every agent** — it exists for a human reviewer to compare the agents'
  output against a known-good reference.

The orchestrator (the `bundle-creation-test` skill loaded into the
top-level conversation) has the broadest write access inside `<run>/`
since it inherits the top-level session's tools; it strictly passes
file paths to subagents and never reads any forbidden inputs itself.
The hard rules at the top of `skills/bundle-creation-test/SKILL.md`
codify that discipline.

---

## Permission model (TL;DR)

| Agent | Tools | Read | Write |
|---|---|---|---|
| `bundle-creation-test` (skill, runs in top-level session) | inherits top-level tools (Read, Write, Edit, Bash, Glob, Grep, Task, MCP) | broad — disciplined by the skill's hard rules to only `ls` paths in `input/`, only read `<run>/**` outputs + `ground_truth/sample_submissions/*/expected_result.json` for manifest | `runs/<comp>/<run_id>/**` only (per the skill's "write only inside run dir" rule) |
| `bundle-planner` | Read, Write, Edit, Glob, Grep, Skill, MCP autocodabench + alex-mcp, WebFetch, WebSearch | `<comp>/input/**` (paper + sample_data), `auto_codabench/skills/**`, own `plan/**` | own `plan/**` only |
| `bundle-implementer` | Read, Write, Edit, Glob, Grep, Skill, MCP autocodabench | `<run>/plan/implementation_plan.md` **only** from plan side; `<comp>/input/sample_data/**` (no paper); `auto_codabench/skills/**`; own `bundle/**` | own `bundle/**` only |
| `bundle-validator-runner` | Read, Write, Bash (validator only) | own `bundle/**`, the validator script | own `validation/**` only |
| `submission-reformatter` | Read, Write, Edit, Glob, Grep | `<comp>/ground_truth/sample_submissions/*/submission/**`, own `bundle/**` | own `reformatted_submission/sub_*/` only |
| `submission-runner` | Read, Write, Bash (narrow) | own `bundle/**`, own `reformatted_submission/**`, `<comp>/ground_truth/sample_submissions/*/expected_result.json`, `<comp>/input/sample_data/**` | own `submission_run/sub_*/` only |

`permissionMode: dontAsk` in every agent: anything outside the allowlist is
a **hard deny**, not a permission prompt — important for unattended runs.

The implementer's pattern `<comp>/input/sample_data/**` does **not** allow
reading `input/report.pdf` (different prefix), so the paper stays
out of Phase 2 by construction, not just by honor system.

Known limitation: agents with `Bash` access can in principle read any file
their shell can reach. We mitigate by:
- Giving Bash only to the three agents that genuinely need it
  (orchestrator, validator-runner, submission-runner).
- Scoping their Bash patterns narrowly (`Bash(python:*)`,
  `Bash(python ./experiments/bundle_creation_test/bundle_validator.py:*)`,
  `Bash(mkdir:*)`, etc.).
- The planner, implementer, and reformatter have **no Bash at all** —
  they operate purely through Read/Write/Edit and (for the planner +
  implementer) MCP tools.

---

## Manifest schema

```json
{
  "competition_sample_name": "style-trans-fair",
  "run_id": "bf1c27b6_20260530_142233",
  "branch": "experiment_test-bundle-creation",
  "started_at": "2026-05-30T14:22:33Z",
  "finished_at": "2026-05-30T14:38:01Z",
  "expected_results": {
    "sub_1": { "metric": "geometric_mean_accuracy_metric", "score": 0.0, "tolerance": 0.001 }
  },
  "steps": [
    { "name": "plan",      "status": "pass", "agent_summary": "...", "artifacts": ["plan/implementation_plan.md"] },
    { "name": "implement", "status": "pass", "slug": "style-trans-fair", "artifacts": ["bundle/.../<slug>.zip"] },
    { "name": "validate",  "status": "pass", "exit_code": 0, "artifacts": ["validation/report.txt"] },
    {
      "name": "reformat_and_run", "status": "pass",
      "submissions": [
        {
          "sub": "sub_1",
          "reformat_status": "pass",
          "interface_summary": "class model: def fit(...), def predict(...)",
          "run_status": "pass",
          "score": 0.0, "expected": 0.0, "delta": 0.0, "within_tolerance": true,
          "artifacts": [
            "reformatted_submission/sub_1/submission.py",
            "submission_run/sub_1/score.json"
          ]
        }
      ]
    }
  ],
  "overall_status": "pass"
}
```

On any failure, `overall_status` becomes `fail_at_<step_name>` (or
`fail_at_reformat_and_run/sub_N` for a specific submission failure inside
step 5) and the failing entry includes the subagent's verbatim error
message. Step 5 fails as a whole if **any** submission fails — but the
orchestrator runs all submissions before deciding, so the manifest shows
per-sub results even on failure.

---

## One-time setup

```bash
bash experiments/bundle_creation_test/setup.sh
```

This creates relative symlinks `.claude/agents/<name>.md →
../../experiments/bundle_creation_test/agents/<name>.md` so Claude Code
picks them up under its standard discovery path. It also makes sure
`.claude/skills/autocodabench-plan` is symlinked to
`auto_codabench/skills/plan/` (the skill name and dir name differ).

`.claude/` stays gitignored apart from the symlinks pointing back here.

---

## Adding a new competition sample

```bash
COMP=my-competition
mkdir -p experiments/bundle_creation_test/competitions/$COMP/{input,ground_truth/sample_submissions/sub_1/submission,ground_truth/bundle}
# put your paper / proposal PDF under input/
# put any public dataset under input/sample_data/
# put the ground-truth Codabench bundle (if you have one) under ground_truth/bundle/  (off-limits to all agents — only for human comparison)
# put sub_1's working submission code under ground_truth/sample_submissions/sub_1/submission/
cat > experiments/bundle_creation_test/competitions/$COMP/ground_truth/sample_submissions/sub_1/expected_result.json <<'JSON'
{
  "metric": "<metric_name_the_bundle_uses>",
  "score": <expected_float>,
  "tolerance": 0.001,
  "details": { "source": "where this expected value came from" }
}
JSON
```

You can have multiple sub_N (sub_1, sub_2, sub_3, …) under
`sample_submissions/`. The orchestrator iterates all of them in step 5
and the manifest records a per-sub pass/fail.

`expected_result.json` is **required** (without it the runner can't decide
pass/fail). If the submission is non-deterministic, set a wider
`tolerance` to allow for that. The `details` block is free-form — use it
to record provenance: the raw Codabench stdout, predictions array, etc.

---

## Running an experiment

From a fresh Claude Code session in the repo root:

> Run the bundle-creation experiment on `style-trans-fair`.

Claude Code's top-level session auto-loads the `bundle-creation-test`
skill (because the user's wording matches its `description`), and the
top-level Claude then follows the skill's recipe. The orchestrator:

1. Computes a `run_id` = `<short_sha>_<utc_ts>`.
2. Creates `experiments/bundle_creation_test/runs/<comp>/<run_id>/`
   and writes an initial `manifest.json`.
3. Spawns the 5 step-agents in order. For step 5 it loops over every
   `<comp>/ground_truth/sample_submissions/sub_*/`, spawning a reformatter
   + runner pair per sub.
4. After each subagent returns, parses its JSON final message into
   `manifest.steps[]` and updates `overall_status`.
5. On the first failure in steps 1–4, records and stops. In step 5,
   continues through all subs but marks `overall_status = "fail_at_..."`
   if any sub fails.
6. Prints a one-screen summary table.

You can have multiple runs per competition sample (one per `<run_id>`
subdir) — they're keyed by branch SHA + timestamp so two runs on the
same commit are still distinguishable.

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
