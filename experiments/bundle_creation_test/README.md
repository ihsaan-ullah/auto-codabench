# bundle_creation_test

End-to-end test harness for AutoCodabench: feed it a paper/proposal,
watch it plan → build → self-validate → score known submissions → check
whether the resulting score matches a pre-recorded ground truth (within
tolerance).

This is a **wrapper** around the `autocodabench` package. The experiment side
orchestrates; the heavy lifting (writing the bundle, running its
baseline, executing the starting-kit notebook, reformatting external
submissions to the bundle's interface, scoring them) lives in
the packaged skills and MCP tools. Both sides share the same
on-disk run dir via the `AUTOCODABENCH_RUN_DIR` environment variable.

Future experiments (latency, cost, robustness, etc.) live in sibling
`experiments/<other_name>/` folders.

---

## Architecture in one paragraph

The orchestrator skill (this folder's `SKILL.md`) is loaded into the
top-level Claude session and drives five phases. Phases 2/3/4a are
**shell-outs** via `claude --print` to fresh Claude sessions running
the packaged skills (`autocodabench-plan`,
`autocodabench-implement`, `autocodabench-reformat-and-run`). Each
shell-out is its own root-level session, so it can spawn subagents
and run its own internal iteration loops without hitting Claude
Code's depth-1 subagent limit. Phase 4b (per ground-truth submission)
spawns ONE in-process subagent (`submission-log-auditor`) that
verdicts the produced score against `expected_result.json`. Phases
5/6/7 stay inside the orchestrator (missing-info aggregation,
finalize, run_report.md).

---

## Layout

```
experiments/bundle_creation_test/
├── README.md                            # this file
├── MISSING_INFO.md                      # schema for the missing-info inventory
├── setup.sh                             # one-time: symlinks skills+agents into .claude/
├── scripts/
│   └── aggregate_missing_info.py        # cross-run meta-analysis over missing_info_report.json files
├── skills/
│   └── bundle-creation-test/
│       └── SKILL.md                     # ORCHESTRATOR — loaded into top-level conversation
├── agents/
│   └── submission-log-auditor.md        # spawned via Task per ground-truth sub_N (phase 4b)
└── competitions/
    └── <competition_sample_name>/       # e.g. style-trans-fair/
        ├── input/                       # planner-only — orchestrator can ls but not read
        │   ├── report.pdf
        │   └── sample_data/             # planner / implementer / reformat-and-run can read
        ├── ground_truth/
        │   ├── bundle/                  # GOLDEN reference bundle — OFF-LIMITS to ALL agents
        │   └── sample_submissions/
        │       └── sub_<N>/
        │           ├── submission/      # reformat-and-run reads; orchestrator/auditor do NOT
        │           └── expected_result.json   # orchestrator reads, hands to auditor
        └── <branch_sha>_<utc_ts>/       # one folder per experiment RUN
            ├── manifest.json            # orchestrator's structured log
            ├── meta.json                # makes the dir AUTOCODABENCH_RUN_DIR-adoptable
            ├── events.jsonl             # MCP tool-call timeline (written by the MCP server)
            ├── tool_calls/              # full MCP request/response snapshots
            ├── specs/                   # plan-phase output
            │   └── implementation_plan.md
            ├── plan_session.jsonl         # claude --print stdout for phase 2
            ├── bundles/<slug>/          # implementer's bundle (validates + zips here)
            │   ├── competition.yaml
            │   ├── scoring_program/    (with requirements.txt)
            │   ├── ingestion_program/  (if γ-style; with requirements.txt)
            │   ├── solutions/solution_baseline/   # the implementer's own baseline
            │   ├── pages/
            │   ├── reference_data/  input_data/  public_data/
            │   ├── README.ipynb         # the starting-kit notebook
            │   └── <slug>.zip           # produced only if validate_runtime=true
            ├── implement_session.jsonl    # claude --print stdout for phase 3
            ├── run_logs/<slug>/         # runner_io output
            │   ├── env/                 # conda clone + install logs
            │   │   ├── clone.stdout/stderr
            │   │   ├── requirements.txt
            │   │   └── install.stdout/stderr
            │   ├── baseline/            # bundle's OWN baseline run (implement-phase 5a)
            │   │   ├── sandbox/
            │   │   ├── stdout.txt / stderr.txt
            │   │   ├── ingestion_stdout.txt / ingestion_stderr.txt
            │   │   ├── scoring_stdout.txt / scoring_stderr.txt
            │   │   └── output/scores.json
            │   ├── starting_kit/        # README.ipynb execution (implement-phase 5b)
            │   │   ├── executed.ipynb
            │   │   └── stdout.txt / stderr.txt
            │   └── sub_<N>.attempt_<K>/ # reformat-and-run-driven user-submission scoring
            │       └── (same shape as baseline/)
            ├── reformat_run/<sub_N>/    # phase 4a per-sub shell-out
            │   ├── session.jsonl
            │   ├── env_probe.txt
            │   ├── attempt_<K>/         # per-attempt adapted code
            │   │   ├── model.py (or whatever the bundle interface expects)
            │   │   └── adapter_notes.md
            │   └── final.json           # status + scores + extras_installed + adapter_notes
            ├── log_audit/<sub_N>/       # phase 4b in-process subagent verdict
            │   └── verdict.json
            ├── missing_info_report.json # phase 5 aggregated inventory
            └── run_report.md            # phase 7 human-readable summary
```

---

## Five-phase pipeline (per experiment run)

| # | Phase | Mechanism | Reads | Writes |
|---|-------|-----------|-------|--------|
| 1 | Preconditions | _(orchestrator)_ | `<comp>/input/` exists; per-sub `expected_result.json` parses | `manifest.expected_results` |
| 2 | Plan | shell-out `claude -p "/autocodabench-plan ..."` | `<comp>/input/**` (the proposal + sample_data) | `<run>/specs/implementation_plan.md` |
| 3 | Implement + self-validate | shell-out `claude -p "/autocodabench-implement ..."` | `<run>/specs/implementation_plan.md` + `<comp>/input/sample_data/` only — BLIND to ground_truth | `<run>/bundles/<slug>/**` + per-program `requirements.txt` + `run_logs/<slug>/{env,baseline,starting_kit}/**` + zip (only if `validate_runtime=true`) |
| 4a | Reformat + run (per `sub_N`) | shell-out `claude -p "/autocodabench-reformat-and-run ..."` | `<run>/bundles/<slug>/**` + `<comp>/ground_truth/sample_submissions/<N>/submission/**` — BLIND to `expected_result.json` | `<run>/reformat_run/<N>/attempt_<K>/**` + `final.json` + `run_logs/<slug>/<N>.attempt_<K>/**` |
| 4b | Log audit (per `sub_N`) | Task → `submission-log-auditor` | `<run>/reformat_run/<N>/final.json` + `<run>/run_logs/<slug>/<N>.attempt_<K>/**` + `expected_result.json` | `<run>/log_audit/<N>/verdict.json` |
| 5 | Aggregate missing-info | _(orchestrator)_ | per-stage `missing_info_inventory.json` files | `<run>/missing_info_report.json` |
| 6 | Finalize | _(orchestrator)_ | manifest + audits | `manifest.json` final, `conda env remove` |
| 7 | run_report.md | _(orchestrator)_ | everything above | `<run>/run_report.md` |

Phases 3–4a run their own internal iteration loops (the implementer
retries baseline + notebook runs up to 5/4 times; reformat-and-run
retries up to 4 times). The orchestrator does NOT retry phases —
each shell-out gets one shot. This keeps failure attribution clean:
an implementer that exhausts its inner attempts is a different
class of failure than an orchestrator that hit an unrecoverable
state, and the manifest distinguishes them.

---

## Why shell-outs (and not Task subagents) for phases 2/3/4a

Claude Code's `Task` tool can spawn a subagent (depth 1), but that
subagent cannot itself spawn another subagent (depth 2 is blocked).

The implementer's inner loop needs to call MCP tools (write the
bundle), then `prepare_run_env`, then `run_baseline_submission`,
then potentially `install_env_extras`, then re-run baseline, then
`run_starting_kit`, etc. — those are all MCP calls inside one
session, fine at any depth.

But the orchestrator itself wants to delegate to the implementer
AS its own conversational unit (fresh context, focused prompt). If
we used `Task` for that, we'd burn the depth budget; phase 4b's
log auditor couldn't spawn. By shell-outing the phases that need
their own runtime loop, we keep `Task` available for the cheap
single-shot auditor.

The shell-outs share state with the parent orchestrator only
through:
- the on-disk run dir (`AUTOCODABENCH_RUN_DIR` env var),
- the JSON object the shell-out emits as its last assistant message
  (captured in the `*_session.jsonl` and parsed by the orchestrator).

That's the entire inter-phase contract. Each phase is reproducible
in isolation by re-running `claude --print` with the same prompt.

---

## Data-leakage rules (preserved from the prior architecture)

| Agent / phase | May read | May NOT read |
|---|---|---|
| Orchestrator (top-level) | `<comp>/ground_truth/sample_submissions/*/expected_result.json` | `<comp>/input/**`, `<comp>/ground_truth/bundle/**`, `<comp>/ground_truth/sample_submissions/*/submission/**` |
| Plan shell-out | `<comp>/input/**` (incl. report.pdf + sample_data) | ground_truth/** |
| Implement shell-out | `<run>/specs/implementation_plan.md` + `<comp>/input/sample_data/**` | report.pdf, ground_truth/** |
| Reformat-and-run shell-out (per sub) | `<run>/bundles/<slug>/**` + `<comp>/ground_truth/sample_submissions/<N>/submission/**` | `expected_result.json`, `ground_truth/bundle/**`, report.pdf, plan |
| Log auditor (subagent, per sub) | `<run>/reformat_run/<N>/**` + `<run>/run_logs/<slug>/<N>.*` + `expected_result.json` | the submission's original code, ground_truth/bundle/, report.pdf, plan |

The expected-score never leaves the orchestrator-or-auditor pair.
The submission's code never reaches the implementer (so it can't
shape the bundle interface to match GT code it just read). The
golden reference bundle is human-only.

---

## One-time setup

```bash
./experiments/bundle_creation_test/setup.sh
```

Symlinks the orchestrator skill + the packaged skills
(`autocodabench-plan`, `autocodabench-implement`,
`autocodabench-reformat-and-run`, `codabench-bundle`,
`competition-design`) into `.claude/skills/`, and the
`submission-log-auditor` agent definition into `.claude/agents/`.

`.claude/` is gitignored — the source of truth lives in this folder
and in `src/autocodabench/skills/`.

---

## Running an experiment

In a top-level Claude Code session:

> Run the bundle-creation experiment on `<competition_sample_name>`

Claude will load `bundle-creation-test` and execute the seven
phases. Total wall-clock depends on the proposal complexity but is
typically dominated by the conda env clone (~30s) + bundle baseline
training (varies) + each reformat-and-run attempt (varies).

To inspect a finished run:
- **Start with `run_report.md`** — one-screen human summary.
- For machine analysis: `manifest.json` (structured) +
  `missing_info_report.json`.
- For deeper digging into a phase failure: the corresponding
  `*_session.jsonl` (one JSON event per line — type=system, user,
  assistant, tool_use, tool_result, result) + the run_logs/ subdir
  for the artifact that broke. `jq -c 'select(.type=="result")'
  session.jsonl | tail -1` gives the final result blob.

---

## Cross-run analysis

```bash
python experiments/bundle_creation_test/scripts/aggregate_missing_info.py
```

Walks every `runs/<comp>/<run_id>/missing_info_report.json`, reports
counts by section / severity / impact, surfaces the most-missed
fields across runs. See the script docstring for filter flags.

---

## Host runtime expectations

The implementer's `prepare_run_env` clones the **active conda env**
(named `base` by default in `autocodabench/runner/execution.py`)
into a per-run scratch env. The clone inherits whatever's installed
in your base env; per-program `requirements.txt` files are then
installed on top via `uv pip install` (or `pip` if `uv` isn't on
PATH).

For competitions that need GPU (e.g. TF/PyTorch CNN baselines), the
base env needs the GPU stack pre-installed — `uv pip install` won't
materialize CUDA libraries that aren't already there. If you're
testing on CPU and the proposal calls for GPU, expect the
implementer's baseline run to be slow but functional, or to fail at
the env layer (TF builds without CUDA support, etc.).

The implementer DOES NOT downgrade or substitute when the host
can't service the plan's compute requirements — it reports
`validate_runtime: false` and lets the orchestrator log the failure.
That's intentional: shrinking the baseline to fit the host
invalidates the experiment by silently making the bundle solve a
different problem than the proposal specified.

---

## Known limitations

- **No retries between phases.** If the implementer's inner loop
  exhausts its baseline attempts, the orchestrator records
  `fail_at_implement` and stops phase 4 + 4a — but still writes
  `missing_info_report.json` + `run_report.md`. Reviewing the
  implementer's stderr is the human's job, not the orchestrator's.
- **Single competition per invocation.** To test against N
  competitions, invoke the skill N times.
- **`claude --print` cost.** Each shell-out is a full fresh Claude
  session. A run with K ground-truth submissions makes 2 + K
  shell-outs. Budget accordingly.
- **No native-library deadlock recovery.** The implementer's retry
  table can patch Python-level errors (ModuleNotFoundError, Keras
  API breaks). It cannot patch native-side issues like the abseil
  ABI deadlock between TF and pyarrow — those manifest as `SIGTERM`
  with no traceback and are upstream of any code edit the
  implementer can do. When it sees that shape, it falls through to
  `validate_runtime: false` and the experiment fails honestly.

---

## Migration note (2026-06-12, branch `jmlr-oss-direction`)

The `auto_codabench/` package was restructured into the pip-installable
`src/autocodabench/` library (core / runner / checks / backends / agent /
mcp / cli). For this harness:

- `setup.sh` symlink sources now point at `src/autocodabench/skills/` —
  re-run it once per checkout.
- The MCP server module is `python -m autocodabench.mcp.server` (the old
  `auto_codabench.mcp_server.server` path is gone).
- Default artifact roots moved from `auto_codabench/{runs,bundles}/` to
  `./.autocodabench/{runs,bundles}/` (override with `AUTOCODABENCH_HOME`).
- The per-bundle deterministic checks that used to live only in
  `validate_bundle` are now the `codabench-validate` CLI / check registry —
  future harness phases should call that instead of re-implementing lint.

Recorded artifacts inside old runs still reference the old layout; that's
expected and harmless.
