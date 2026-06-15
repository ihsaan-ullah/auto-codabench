# The `autocodabench create` pipeline and per-phase testing

This document describes the execution of

```bash
autocodabench create "<competition idea>" [--data <sample-data>]
```

in full: the phases it comprises, **which part of each phase is an LLM session
and which part is deterministic code**, the precise inputs and outputs of every
step, the artifacts each phase produces, and the procedure for exercising any
single phase in isolation. The last point supports developing or debugging a
single stage without driving the whole pipeline. Phases that can be exercised
without Claude credentials are identified as *keyless*.

The following invariant governs the runtime behaviour of every phase and should
be kept in mind throughout:

> autocodabench executes every program inside Docker, under the same conditions
> as the Codabench compute worker. The worker runs a bundle's scoring,
> ingestion, and notebook programs inside the competition's declared
> `docker_image` and installs no additional dependencies. A successful local run
> is therefore evidence that the bundle will execute on the platform;
> conversely, a platform failure following a successful local run implicates the
> server environment rather than the bundle. Docker is a hard prerequisite for
> every runtime phase (see `docs/architecture.md` and the runner module
> docstring).

---

## A. The two kinds of work: LLM-with-tools versus deterministic code

Every phase is built from two clearly separated kinds of work, and the
separation is the single most important thing to understand about the pipeline.

**1. LLM-with-tools sessions.** An *agent session* is one call to
`AgentBackend.run(task)` (`backends/base.py`). The backend drives a model in an
agentic loop: the model receives a system prompt, a user prompt, and a
*capability surface* (an allow-list of tools plus the MCP servers that
implement them); it then alternates between emitting text and emitting
`tool_use` requests; the backend executes each requested tool and feeds the
`tool_result` back; the loop repeats until the model stops. The model itself
**writes no files and runs no programs** — it only decides *what* to do and
calls a tool to do it. The inputs and outputs of a session are fully specified
by two dataclasses:

- **Input — `AgentTask`** (`backends/base.py`): `prompt` (the user message),
  `system_prompt` (the phase's behavioural contract — see below), `allowed_tools`
  (the capability allow-list), `mcp_servers` (the stdio MCP subprocess scoped to
  this phase's run directory), `env` (notably `AUTOCODABENCH_RUN_DIR`), `model`,
  `max_budget_usd`, and `trace_path` (where to record the message-by-message
  JSONL trace).
- **Output — `AgentRunResult`**: `status` (`"success"`/`"error"`/
  `"error_max_turns"`/…), `final_text` (the model's last message),
  `num_turns`, `total_cost_usd`, `usage`, `session_id`, `trace_path`, `error`.
  The *durable* output is not in this object: it is the set of side effects the
  tool calls produced on disk (files written, programs run), plus the audit
  trail of those calls.

  The system prompt for each phase is **not** a Python string; it is the body
  of a packaged *skill* (`autocodabench/skills/<name>/SKILL.md`, frontmatter
  stripped) with a short runtime footer appended for the headless CLI surface
  (`agent/prompts.py`). The skill is the versioned, reviewable contract for the
  phase.

**2. Deterministic code.** Everything a tool *does* is ordinary Python with no
model in it. The tools fall into two groups:

- **Core file I/O** (`core/bundle_io.py`, exposed as the MCP `write_*` /
  `init_bundle` / `attach_data` / `validate_bundle` / `zip_bundle` tools, and
  the `snapshot_spec` tool in `run_log.py`). These read and write files in the
  run directory. No network, no Docker, no LLM. Each is a one-shot function
  returning a small result dict.
- **Runner execution** (`runner/execution.py`, exposed as
  `prepare_run_env` / `run_baseline_submission` / `run_user_submission` /
  `run_starting_kit`). These stage the Codabench sandbox and run programs inside
  Docker. No LLM. Each is a one-shot function: it performs exactly one operation
  and returns; it never loops or retries internally — iteration is the calling
  *session's* job, because only a model session can read a traceback and decide
  the next move.

The MCP layer is the bridge: it wraps each deterministic function as a tool the
model can call, and the `logged_tool` decorator snapshots **every** call to
`<run>/tool_calls/NNNN_<tool>.json` (full args + result) and appends an event to
`<run>/events.jsonl`. That audit trail is also the replay-fixture format, which
is why the keyless `demo` can re-run a recorded session against the real core
with no model involved.

Concretely, then: **Phase 1 and Phase 2 are LLM sessions that call deterministic
tools. Phase 3 is deterministic code with no LLM at all (unless the optional
judged tier is explicitly enabled).** The rest of this document makes each
phase's split, inputs, and outputs explicit.

---

## 0. Preflight checks performed before any cost is incurred

**Kind: deterministic code. No LLM.** Before opening the first agent session,
`create` runs three checks so that configuration or environment problems surface
immediately rather than after an idle period:

1. **Authentication preflight** — confirms a working Claude authentication path
   (subscription login or `ANTHROPIC_API_KEY`) and prints an `INFO:` banner
   naming the resolved path. Input: the environment and the persisted auth
   preference. Output: a banner; an early, clear refusal if no path exists.
2. **Configuration banner** — prints the effective model, output directory,
   sample data, cost cap, and output verbosity. Input: the parsed CLI args and
   the constructed backend. Output: a banner.
3. **Docker runtime preflight** — reports the starting `docker_image`, its CPU
   architecture relative to the host (native execution versus QEMU emulation),
   and whether the Docker daemon is installed and running. Input: the daemon
   status and the image's manifest; Output: the `docker_preflight()` dict. The
   same banner precedes `validate`.

Each check can be exercised independently without credentials:

```bash
autocodabench auth status --no-probe          # static auth detection (no live turn)
autocodabench validate <bundle>        # prints the Docker preflight banner
python - <<'PY'                               # the preflight result directly
from autocodabench.runner import docker_preflight
import json; print(json.dumps(docker_preflight("codalab/codalab-legacy:py312"), indent=2))
PY
```

On Apple silicon hosts, a native `arm64` image is preferable for local testing.
The `codalab/codalab-legacy:py312` tag is multi-architecture (amd64 and arm64),
so Docker resolves it to arm64 and it runs without emulation:

```bash
export AUTOCODABENCH_DOCKER_IMAGE=codalab/codalab-legacy:py312
```

An amd64-only image (for example `codalab/codalab-legacy:py39`) also runs, but
under emulation. The preflight flags this case with a warning, and the
associated slowdown is substantial.

---

## Pipeline overview

| # | Step | LLM or code? | Input | Output |
|---|------|--------------|-------|--------|
| 0 | Preflight | code | env, args, Docker daemon | banners; early refusal on bad config |
| 1 | **Plan** | **LLM session** (`PLAN_TOOLS`) | idea text, optional `--data` | `specs/implementation_plan.md` |
| 2 | **Build** | **LLM session** (`BUILD_TOOLS`) driving code tools | the locked plan | `bundles/<slug>/`, `<slug>.zip`, run logs, execution cache |
| 2a | ↳ prepare image | code (Docker) | `docker_image` from `competition.yaml` | image present locally |
| 2b | ↳ schema lint | code | bundle files | lint report (`ok`, `issues`) |
| 2c | ↳ run baseline | code (Docker) | bundle + its baseline | `scores.json` + run logs |
| 2d | ↳ run notebook | code (Docker) | bundle + its notebook | executed notebook + logs |
| 3 | **Validate** | **code** (LLM only with `--judged`) | the built bundle | `ValidationReport` + `validation_report.md/.json` |
| — | **Upload** (manual) | code (Codabench worker) | `<slug>.zip` | leaderboard score |

The live Plan and Build sessions require Claude authentication. The keyless
**replay demo** (`autocodabench demo`) re-executes a *recorded* plan+build
session against the real core with no model and no credentials. The runtime
steps (2a–2d) and the entire Phase 3 (except the optional judged tier) are
independently keyless code.

---

## 1. Phase 1 — Plan

**Kind: one LLM-with-tools session, plus one deterministic file-write tool.**

### 1.1 The LLM session

| Field | Value |
|-------|-------|
| `system_prompt` | the `plan` skill body + the non-interactive CLI footer (`prompts.plan_system_prompt()`) |
| `prompt` | "Open the run … then produce the implementation plan for this competition idea:\n\n`<idea>`" — with an appended line pointing at `--data` if provided |
| `allowed_tools` | `PLAN_TOOLS`: `open_run`, `current_run`, `log_event`, `snapshot_spec`, and read-only `Read`, `Grep`, `Glob` |
| `mcp_servers` | the autocodabench stdio MCP server, scoped to `phase1_plan/` via `AUTOCODABENCH_RUN_DIR` |
| `trace_path` | `phase1_plan/agent_trace/plan.jsonl` |

**What the model does (and does not do).** It reads the idea string and, if
`--data` was given, inspects the sample data with `Read`/`Glob`. It reasons
about the seven design sections of a Codabench competition — task, data, metric,
baseline, rules, ethics, schedule — and makes conservative, explicitly-stated
assumptions for anything the idea leaves open (there is no user to ask in the
headless CLI). It **cannot author bundle files**: the only writing tool in
`PLAN_TOOLS` is `snapshot_spec`, which writes a spec document, not bundle code.
That capability gap is deliberate — authoring is withheld until Phase 2.

**Inputs to the session:** the `idea` string; optionally the files under
`--data` (read-only). **Outputs of the session:** an `AgentRunResult` (status,
`num_turns`, `total_cost_usd`, …) and, as the load-bearing side effect, the plan
file on disk.

### 1.2 The deterministic tools it calls

| Tool | Kind | Input | Output / effect |
|------|------|-------|-----------------|
| `autocodabench_open_run` / `current_run` | code | — | confirms/joins the active run directory |
| `Read` / `Glob` / `Grep` | code | a path or pattern | file contents / matches (used to read `--data`) |
| `autocodabench_log_event` | code | a `kind` + `message` | appends one line to `events.jsonl` (user-facing progress/milestone/deviation notices) |
| `autocodabench_snapshot_spec` | code | `filename="implementation_plan.md"`, `body=<markdown>` | writes `phase1_plan/specs/implementation_plan.md` **and** a timestamped copy under `specs_history/`; returns `{path, history}` |

The plan file is the *entire* interface between Phase 1 and Phase 2: the build
session starts with no conversation history and reads only this file. The
isolation is intentional — it makes "was the plan wrong, or the implementation?"
answerable from artifacts alone (see `docs/design-rationale.md`, §10).

### 1.3 Testing Phase 1

- Keyless, full authoring path: `autocodabench demo --out /tmp/demo` replays a
  recorded plan+build session, then validates the rebuilt bundle.
- Live, plan only: run `create` and inspect
  `phase1_plan/specs/implementation_plan.md` under the session directory; the
  `--debug` flag prints every tool call.

---

## 2. Phase 2 — Build (authoring, then self-validation)

**Kind: one LLM-with-tools session that drives many deterministic tools.** This
is the phase where the LLM/code split matters most: the model decides the
*content* of every bundle file and the *sequence* of operations, but each file
is written and each program is run by deterministic code invoked through a tool
call. The model writes nothing and runs nothing directly.

### 2.1 The LLM session

| Field | Value |
|-------|-------|
| `system_prompt` | the `autocodabench-implement` skill body + the build CLI footer (`prompts.build_system_prompt()`) |
| `prompt` | "The locked implementation plan is at `<…>/phase1_plan/specs/implementation_plan.md`. Read it and build the bundle now." |
| `allowed_tools` | `BUILD_TOOLS`: the **full** `mcp__autocodabench__*` surface plus read-only `Read`, `Grep`, `Glob` |
| `mcp_servers` | the autocodabench stdio MCP server, scoped to `phase2_build/` via `AUTOCODABENCH_RUN_DIR` |
| `trace_path` | `phase2_build/agent_trace/build.jsonl` |

**Input to the session:** the locked plan file (read via `Read`). **Outputs of
the session:** the bundle directory and zip, the run logs, the execution cache,
optionally an updated plan, and the `AgentRunResult`.

The session has two stages — *authoring* then *self-validation* — both expressed
as tool calls.

### 2.2 Authoring — deterministic file-writer tools (no Docker, no LLM)

The model calls these `core/bundle_io.py`-backed tools to materialize the
bundle. Each is pure file I/O; the *contents* are the model's; the *writing* is
code.

| Tool | Input (from the model) | Output / effect (deterministic) |
|------|------------------------|---------------------------------|
| `autocodabench_init_bundle` | `slug` | creates `bundles/<slug>/` with the standard subdirectory skeleton; returns `{created}` |
| `autocodabench_write_competition_yaml` | `slug`, the YAML dict | validates required/unknown top-level keys, writes `competition.yaml`; raises on a bad schema |
| `autocodabench_write_page` | `slug`, page filename, markdown | writes `pages/<file>` (path-traversal rejected) |
| `autocodabench_write_scoring_program` | `slug`, scorer source (+ optional metadata) | writes `scoring_program/score.py` (+ `metadata.yaml`) |
| `autocodabench_write_ingestion_program` | `slug`, ingestion source | writes `ingestion_program/…` (γ-style competitions only) |
| `autocodabench_write_solution` | `slug`, baseline files | writes `solutions/solution_baseline/…` |
| `autocodabench_attach_data` | `slug`, `target` (`reference_data`/`input_data`/…), files | writes the data files into the bundle |
| `autocodabench_snapshot_spec` | `filename="updated_implementation_plan.md"`, body | records build-time deviations from the locked plan, if any |

### 2.3 Self-validation — the deterministic run loop (Docker; no LLM)

After writing the bundle the model **runs it** and iterates on real runtime
errors. The decision to retry, and how to fix the error, is the model's; the
linting and the runs themselves are deterministic code. The loop, in order:

**2a. Ensure the image is present — `prepare_run_env(slug)`**
Pure code. Reads the bundle's `docker_image` (defaulting to the autocodabench
CPU base image), confirms it is in the local image store, and pulls it once if
absent. Installs nothing — dependencies belong in the image.

- Input: the bundle's `docker_image`. Output:
  `{ok, image, env_name, present_locally, pulled, logs_dir, note, error}`.

```python
from autocodabench.runner import prepare_run_env
print(prepare_run_env("<slug>"))
```

**2b. Schema lint — `validate_bundle(slug)`**
Pure code, no execution. Parses `competition.yaml`, checks every referenced file
exists, checks programs carry runnable `metadata`, and statically scans the
scorer so that each declared leaderboard key is actually written.

- Input: the bundle files. Output:
  `{ok, issues:[{severity, message, where}], leaderboard_keys_expected}`.
- The model reads `issues` and fixes the bundle, then re-lints.

```bash
autocodabench validate bundles/<slug>/ --no-execute
```

**2c. Run the baseline through scoring — `run_baseline_submission(slug)`**
Pure code orchestrating Docker. Stages the Codabench sandbox (program at
`/app/program`, data/output at `/app/input` & `/app/output`), then runs
ingestion (γ-style) + scoring inside `docker_image`, exactly as the worker
would. On success it also writes a `baseline` entry into the execution cache
(see §3.3).

- Input: the bundle and its baseline under `solutions/`. Output:
  `{ok, stage, engine, docker_image, ingestion, scoring, scores, scores_format,
  duration_s, data, sandbox_dir, logs_dir, error}` (with the full stdout/stderr
  tee'd to `run_logs/<slug>/baseline/`).

```python
from autocodabench.runner import run_baseline_submission
r = run_baseline_submission("<slug>")
print(r["ok"], r["docker_image"], r["scores"], r["duration_s"])
```

The model iterates on failures here — for example, an API incompatibility
between the library version the plan assumed and the version the image ships. A
`ModuleNotFoundError` is **not** fixed by installing a package (the platform
installs nothing); it is fixed by declaring a `docker_image` that already ships
the dependency. When a fix deviates from the locked plan, the model records it
in `updated_implementation_plan.md` (§2.2) and emits a user-facing
`log_event(kind="deviation", …)`.

**2d. Run the starting-kit notebook — `run_starting_kit(slug)`**
Pure code orchestrating Docker. Executes `README.ipynb` / `starting_kit/*.ipynb`
with `jupyter nbconvert --to notebook --execute --inplace` inside `docker_image`,
the bundle mounted at `/app` as the working directory so relative paths resolve.
nbconvert stops at the first cell error. On success it writes a `starting_kit`
entry into the execution cache.

- Input: the bundle and its notebook. Output:
  `{ok, notebook_source, executed_notebook, cells_executed, exit_code,
  duration_s, timed_out, stdout_tail, stderr_tail, logs_dir, error}`.

```python
from autocodabench.runner import run_starting_kit
r = run_starting_kit("<slug>")
print(r["ok"], r["cells_executed"], r["executed_notebook"])
```

**Strict exit.** Both 2c and 2d must succeed before the model calls
`autocodabench_zip_bundle` (pure code → writes `bundles/<slug>.zip`). If the
session cannot get its own bundle to run within the attempt budget, the build
fails here rather than shipping a bundle that is merely well-formed. The final,
working `docker_image` is whatever `competition.yaml` declares at the end — the
image the baseline actually passed under, and the one Codabench will use.

### 2.4 Testing Phase 2's code in isolation (keyless)

Steps 2a–2d are pure functions over a bundle on disk — no model required:

```bash
autocodabench demo --out /tmp/acb-demo                 # materialize a real bundle
export AUTOCODABENCH_BUNDLES_ROOT=/tmp/acb-demo         # let resolve_bundle_dir find it
python - <<'PY'
from autocodabench.runner import prepare_run_env, run_baseline_submission, run_starting_kit
slug = "demo-ai-text-detection"
print("prepare:", prepare_run_env(slug)["note"])
b = run_baseline_submission(slug);  print("baseline:", b["ok"], b["scores"])
k = run_starting_kit(slug);         print("notebook:", k["ok"], k["cells_executed"])
PY
```

The shipped demo declares an amd64-only image; override it by editing
`docker_image` in its `competition.yaml`, or by exporting
`AUTOCODABENCH_DOCKER_IMAGE` before the run. The same functions are exposed as
MCP tools (`autocodabench_prepare_run_env`,
`autocodabench_run_baseline_submission`, `autocodabench_run_starting_kit`);
the build session calls them over the stdio MCP server, and every call is
snapshotted to `phase2_build/tool_calls/`.

---

## 3. Phase 3 — Validate

**Kind: deterministic code. No LLM by default.** Phase 3 is *not* an agent
session — `create` calls `validate_bundle_path_async(bundle_dir, execute=True)`
directly. The same function backs the standalone `validate` command,
which is the entry point for a user validating a bundle they wrote or obtained
rather than generated. The only place a model can enter Phase 3 is the optional
*judged* tier, which `create` never enables and which the CLI enables only with
`--judged`.

The check framework organizes checks into tiers with distinct epistemic standing
(`checks/`). Inputs to the whole pass: the bundle directory, an auto-discovered
`competition_facts.yaml` (or `--facts`), and the `execute` flag. Output: a
`ValidationReport` whose `ok` is **true iff no deterministic check FAILed**, plus
`validation_report.md` and `validation_report.json` written into
`phase3_validate/`.

### 3.1 Static checks — deterministic code

Inspect `competition.yaml` and the bundle's files; no Docker, no model, no keys.

| Tier | Examples | Verdict semantics |
|------|----------|-------------------|
| deterministic (static) | `bundle-schema` (the structural gate), `two-phase-structure`, `dev-phase-duration`, `daily-submission-cap`, `final-phase-submission-limit`, `leaderboard-sorting`, `starting-kit`, `baseline-solutions`, `docker-image-pinned`, `test-set-size`, `external-data-rule` | `bundle-schema` is the one **static** gate (FAIL blocks); the design checks emit advisory FINDINGs; facts-gated checks SKIP with instructions when their fact is absent |
| attestation | external review, datasheet, leakage probe, data persistence, game-of-skill | surfaced as explicit unchecked boxes a human must certify; never assumed |

- Input: the bundle files (+ facts). Output: one or more `CheckResult`s per
  check (`status`, `severity`, `message`, `where`, `citation`).

```bash
autocodabench validate bundles/<slug>/ --no-execute          # static only
autocodabench validate bundles/<slug>/ --no-execute --json   # machine-readable
autocodabench checks list                                           # the live inventory by tier
```

### 3.2 Execution checks — deterministic code that runs the bundle (Docker)

By default, validation does more than inspect the bundle: it **runs** it. Two
additional deterministic checks execute the bundle inside its declared
`docker_image`, exactly as the worker will. There is no model here — they call
the same `runner/execution.py` functions Phase 2 used.

| Check | What it executes | Input | Output / verdict |
|-------|------------------|-------|------------------|
| `baseline-execution` | the baseline through ingestion+scoring | the bundle + its baseline | **gates (FAIL)** if a baseline is present and no score is produced; SKIPPED if no Docker; FINDING if no baseline present |
| `starting-kit-execution` | the starting-kit notebook | the bundle + its notebook | advisory (FINDING) on failure — onboarding, not the scoring path |

Each records structured evidence — which `docker_image` ran, its architecture
fit against the host (native or QEMU-emulated), the wall-clock duration, the
scores produced, and which data the run consumed — carried in the `CheckResult`'s
`details` and rendered under the report's **Execution** section. This is the
per-run, literal answer to "which run succeeded, on what data, in which image,
for how long, under which condition."

The library default keeps execution **off** (`validate_bundle_path(...,
execute=False)`) so programmatic and keyless use stays static and fast; the CLI
turns it on:

```bash
autocodabench validate bundles/<slug>/            # static + execution (default)
autocodabench validate bundles/<slug>/ --execute  # explicit
autocodabench validate bundles/<slug>/ --no-execute  # disable execution
```

### 3.3 Reusing the build phase's runs — the execution cache (deterministic)

When `create` reaches Phase 3, Phase 2 has already run the baseline and notebook
in Docker. Re-running them would waste minutes, so each successful run in §2.3
wrote a small **execution cache** next to the bundle
(`bundles/.acb_execution_cache.json`), keyed by a content hash over the bundle's
files. Phase 3's execution checks consult it: if the bundle is byte-for-byte
unchanged, they reuse the recorded result and label it as reused from the build
phase rather than re-executing. **Any edit to a bundle file changes the hash and
forces a fresh run**, so the cache can never mask a change. This is what makes
the common workflow safe — run plan+build, hand-edit the generated scoring
program or data, then run `validate` separately: the validator detects
the edit (hash mismatch) and re-executes rather than trusting a stale pass.

- Input to a reuse decision: the bundle's current content hash. Output: either a
  cached result dict (re-used) or a fresh `runner` execution.

### 3.4 The judged tier — the only LLM in validation (opt-in)

`judged-docs-config-consistency` asks a model whether the human-readable pages
contradict the machine-readable configuration (e.g. submission limits stated in
prose versus the declared caps, metric direction, phase dates). It runs **only**
with `--judged` and an authenticated backend; its verdicts are FINDINGs, never
gates, and an unparseable response degrades to SKIPPED. `create` does not enable
it, so a `create` Phase 3 is 100% deterministic.

```bash
autocodabench validate bundles/<slug>/ --judged      # adds the LLM tier (needs a backend)
```

---

## 4. Run artifacts and platform execution

A `create` invocation writes its output as one **session directory** whose name
is the shared prefix `<branch>_<timestamp>`, with one subdirectory per phase.
Grouping the phases under a single prefix keeps a full run together and
self-describing, while separating them makes "which phase produced this
artifact" unambiguous:

```
<session>/                              # <branch>_<timestamp> — the shared prefix
  manifest.json                         # per-phase status + key artifact paths
  phase1_plan/                          # LLM session output
    specs/implementation_plan.md        # the locked plan (the Phase 1→2 interface)
    specs_history/                       # timestamped versions of each spec write
    tool_calls/ + events.jsonl          # full audit trail (also the replay format)
    agent_trace/plan.jsonl              # message-by-message session trace
  phase2_build/                         # LLM session output + the bundle it built
    bundles/<slug>/                     # the bundle (competition.yaml + programs + data)
    bundles/<slug>.zip                  # the uploadable artifact
    bundles/.acb_execution_cache.json   # baseline/notebook run records (reused by phase 3)
    specs/updated_implementation_plan.md # build-time deviations, if any
    run_logs/<slug>/                    # sandbox + stdout/stderr for the build's runs (2c/2d)
    tool_calls/ + events.jsonl
    agent_trace/build.jsonl
  phase3_validate/                      # deterministic validation output
    validation_report.md / .json        # the full report, static + execution
    run_logs/<slug>/                    # only if phase 3 had to re-execute anything
```

A standalone `autocodabench validate` instead creates its own session
directory (a different prefix) containing only a `phase3_validate/` folder, so a
validation run and a generation run never share a prefix and cannot be confused.
With `--no-execute` the command performs static checks only and writes no session
directory.

The `Done.` summary names the session directory, the plan, the bundle, the zip,
the validation report, the final `docker_image`, any
`updated_implementation_plan.md`, and the cost.

**On upload (deterministic, on Codabench's side).** When `<slug>.zip` is
uploaded, the compute worker runs the scoring (and ingestion) programs inside
the bundle's `docker_image`, mounting the active program directory at
`/app/program` and the data/output trees at `/app/input` & `/app/output` — the
exact layout `run_baseline_submission` staged locally. To rehearse a
*participant* submission against the finished bundle (the path the
`reformat-and-run` skill drives):

```python
from autocodabench.runner import run_user_submission
r = run_user_submission("<slug>", submission_dir="/path/to/a/submission")
print(r["ok"], r["scores"])
```

---

## 5. Where the LLM is, and where it is not

A single table summarizing the split, because it is the crux of the design:

| Work | LLM? | Module / tool |
|------|------|---------------|
| Deciding the competition design (the plan) | **yes** — Phase 1 session | `agent/pipeline.py`, `skills/plan` |
| Writing the plan file | no — code | `snapshot_spec` (`run_log.py`) |
| Deciding bundle contents + the build sequence + how to fix runtime errors | **yes** — Phase 2 session | `agent/pipeline.py`, `skills/autocodabench-implement` |
| Writing every bundle file | no — code | `core/bundle_io.py` (`write_*`, `init_bundle`, `attach_data`, `zip_bundle`) |
| Linting the bundle | no — code | `core/bundle_io.py::validate_bundle` |
| Pulling the image, running the baseline / notebook / a submission | no — code (Docker) | `runner/execution.py` |
| Static design + structural + attestation checks | no — code | `checks/deterministic.py`, `checks/attestations.py` |
| Execution checks (running the bundle during validation) | no — code (Docker) | `checks/execution.py` → `runner/execution.py` |
| Reusing or invalidating cached runs | no — code | `runner/execution.py` (content hash) |
| Judging pages-vs-config consistency | **yes, only with `--judged`** | `checks/judged.py` |
| Recording every tool call as audit + replay fixture | no — code | `run_log.py::logged_tool` |

The implication for cost and reproducibility: the only metered, model-dependent
work in the whole pipeline is the two authoring sessions (Phases 1–2) and the
opt-in judged check. Everything downstream of "a bundle exists on disk" — image
preparation, baseline scoring, notebook execution, and the entire deterministic
validation framework — is keyless, Docker-backed code that produces the same
result on the same inputs every time.

---

## Reference — keyless smoke tests by layer

```bash
python -m pytest tests/                      # unit suite (fast, fully keyless)
python -m autocodabench.core.bundle_io       # core authoring smoke (demo bundle in a tempdir)
autocodabench demo --out /tmp/demo           # replay authoring + validate (no LLM, no keys)
autocodabench validate <bundle> --no-execute   # static schema validation, keyless
autocodabench validate <bundle>       # static + execution (runs the bundle; needs Docker)
autocodabench checks list                    # registered checks by tier
python -m autocodabench.mcp.server           # MCP stdio server (blocks on stdin — expected)
python -c "from autocodabench.runner import docker_preflight; print(docker_preflight())"
```

The only steps that require Claude authentication are the live Phase 1 (plan)
and Phase 2 (build) agent sessions, and the opt-in judged validation tier.
Every other step — image preparation, baseline scoring, notebook execution, and
the deterministic validation framework — is keyless and Docker-backed code, and
can be developed and tested in isolation with the snippets above.
```
