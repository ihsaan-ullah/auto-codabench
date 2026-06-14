# The `autocodabench create` pipeline and per-phase testing

This document describes the execution of

```bash
autocodabench create "<competition idea>" [--data <sample-data>]
```

in full: the phases it comprises, the artifacts each phase produces, and the
procedure for exercising any single phase in isolation. The latter is intended
to support development and debugging of an individual stage without driving the
complete pipeline. Phases that can be exercised without Claude credentials are
identified as *keyless*.

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

## 0. Preflight checks performed before any cost is incurred

`create` performs three preflight checks before initiating a live agent session,
so that configuration or environment problems surface immediately rather than
after an idle period:

1. **Authentication preflight** — confirms a working Claude authentication path
   (subscription login or `ANTHROPIC_API_KEY`) before the first live turn, and
   prints an `INFO:` banner naming the resolved path.
2. **Configuration banner** — reports the effective model, output directory,
   sample data, cost cap, and output verbosity.
3. **Docker runtime preflight** — reports the starting `docker_image`, its CPU
   architecture relative to the host (native execution versus QEMU emulation),
   and whether the Docker daemon is installed and running. The same banner
   precedes `validate-bundle`.

Each check can be exercised independently without credentials:

```bash
autocodabench auth status --no-probe          # static auth detection (no live turn)
autocodabench validate-bundle <bundle>        # prints the Docker preflight banner
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

| # | Step | Executes | Produces | Isolated test | Keyless? |
|---|------|-----------|----------|-------------------|----------|
| 1 | **Plan** | One agent session (`PLAN_TOOLS`) | `specs/implementation_plan.md` | replay demo; or live `create` | live only* |
| 2 | **Build** | One agent session (`BUILD_TOOLS`) that writes the bundle and self-validates it | `bundles/<slug>/`, `<slug>.zip`, optionally `specs/updated_implementation_plan.md` | replay demo; MCP tools directly | live only* |
| 2a | ↳ prepare image | `prepare_run_env(slug)` | image present locally | `prepare_run_env` | **keyless** |
| 2b | ↳ schema lint | `validate_bundle` | lint report | `validate-bundle` | **keyless** |
| 2c | ↳ run baseline | `run_baseline_submission(slug)` in Docker | `scores.json` + run logs | snippet below | **keyless** |
| 2d | ↳ run notebook | `run_starting_kit(slug)` in Docker | executed notebook + logs | snippet below | **keyless** |
| 3 | **Validate** | Registered checks | `ValidationReport` | `validate-bundle` | **keyless** |
| — | **Upload** (manual) | Codabench worker runs scoring in `docker_image` | leaderboard score | `run_user_submission` mirrors it | **keyless** |

\* The live plan and build phases require Claude authentication. The replay demo
(`autocodabench demo`) re-executes a recorded plan and build run against the
real core with no LLM and no credentials, and is the keyless means of exercising
the authoring path end to end. The runtime steps (2a–2d, 3) are independently
keyless.

---

## 1. Phase 1 — Plan

A single agent session runs with a deliberately restricted tool allowlist
(`PLAN_TOOLS` in `agent/pipeline.py`: `open_run`, `current_run`, `log_event`,
`snapshot_spec`, and the read-only `Read`, `Grep`, and `Glob` tools). The
session reads the competition idea and any `--data` argument, infers the seven
design sections (task, data, metric, baseline, rules, ethics, schedule), and
writes `specs/implementation_plan.md` via `autocodabench_snapshot_spec`. The
planning session has no capability to author bundle files; that capability is
withheld until Phase 2.

The isolation between phases is a deliberate design choice: the build session
begins with no conversation history, and the locked plan constitutes the entire
interface between deliberation and execution (see `docs/design-rationale.md`,
§10).

Testing procedures:

- Keyless, full authoring path: `autocodabench demo --out /tmp/demo` replays a
  recorded plan and build run, then validates the rebuilt bundle.
- Live, plan only: run `create` and inspect `specs/implementation_plan.md` under
  the run directory. The `--debug` flag traces each tool call.

---

## 2. Phase 2 — Build (authoring followed by self-validation)

A fresh agent session (`BUILD_TOOLS`: the complete `mcp__autocodabench__*`
surface together with the read-only file tools) reads the locked plan and writes
the bundle, comprising `competition.yaml`, the pages, the scoring program, the
baseline solution, the ingestion program (for γ-style competitions), and the
data. The session then executes its own bundle and iterates on observed runtime
errors until the bundle runs successfully. This self-validation step
distinguishes a bundle that is executable from one that is merely well-formed.

The self-validation loop proceeds in the following order.

### 2a. Ensure the Docker image is available — `prepare_run_env(slug)`

This function is the Docker-based replacement for the per-run conda environment
used in earlier versions. It reads the bundle's `docker_image` (defaulting to
the autocodabench CPU base image), confirms its presence in the local image
store, and pulls it once if absent. It installs no packages; dependencies are
expected to be provided by the image.

```python
from autocodabench.runner import prepare_run_env
print(prepare_run_env("<slug>"))   # {ok, image, present_locally, pulled, note, error}
```

### 2b. Schema lint — `validate_bundle`

A static structural check that performs no execution. It is reachable from the
CLI:

```bash
autocodabench validate-bundle bundles/<slug>/
```

### 2c. Run the baseline through scoring — `run_baseline_submission(slug)`

This function stages the Codabench sandbox layout and runs the bundle's own
baseline through ingestion (for γ-style competitions) and scoring inside
`docker_image`, under the same conditions the worker uses for a participant
submission. A run that completes and yields a parseable score is evidence of the
behaviour to be expected on the platform.

```python
from autocodabench.runner import run_baseline_submission
r = run_baseline_submission("<slug>")
print(r["ok"], r["engine"], r["docker_image"], r["scores"])
```

The build session iterates on failures observed here — for example, an API
incompatibility between the library version assumed by the plan and the version
shipped in the image. When such a fix deviates from the locked plan, the
deviation is recorded in `specs/updated_implementation_plan.md` (under a "what
changed versus what did not" header) and reported to the user via
`log_event(kind="deviation", ...)`. A `ModuleNotFoundError` is not resolved by
installing a package, since the platform installs nothing; it is resolved by
declaring a `docker_image` that already provides the dependency.

### 2d. Run the starting-kit notebook — `run_starting_kit(slug)`

This function executes `README.ipynb` or `starting_kit/*.ipynb` using
`jupyter nbconvert --to notebook --execute --inplace` inside `docker_image`. The
bundle is mounted at `/app` and serves as the working directory, so the
notebook's relative paths (for example `input_data/...`) resolve from the bundle
root. nbconvert halts at the first cell error and exits with a nonzero status;
the executed notebook, including cell outputs, is saved under the run logs for
inspection.

```python
from autocodabench.runner import run_starting_kit
r = run_starting_kit("<slug>")
print(r["ok"], r["cells_executed"], r["executed_notebook"])
```

Both 2c and 2d must complete successfully before the bundle is zipped. If the
build session cannot run its own bundle, the build fails at this point rather
than producing a bundle that is structurally valid but not executable.

At the conclusion of the loop, the final working `docker_image` is the one
declared in `competition.yaml`. The CLI reports it in the `Done.` summary (the
`docker:` line), since it is the image Codabench will use.

Steps 2a–2d can be tested in isolation, without credentials, against any bundle
on disk. The demo bundle is a convenient subject:

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

The shipped demo declares an amd64-only image. For a native run on Apple
silicon, override it by editing `docker_image` in its `competition.yaml`, or by
exporting `AUTOCODABENCH_DOCKER_IMAGE` before the run.

The same three functions are exposed as MCP tools
(`autocodabench_prepare_run_env`, `autocodabench_run_baseline_submission`,
`autocodabench_run_starting_kit`). The build session invokes them over the
stdio MCP server, and each call is snapshotted to `<run>/tool_calls/`.

---

## 3. Validation pass — registered checks

After the bundle is built, `create` runs the check framework
(`validate_bundle_path_async`). The framework organizes checks into three tiers
with distinct epistemic standing: **deterministic** checks, in which code
computes a PASS or FAIL verdict and which constitute the only gating tier;
**judged** checks, in which an LLM grades a rubric and emits advisory FINDINGs
that never gate; and **attestation** checks, which encode human-only criteria
and are surfaced as unchecked boxes. Each check carries a citation.

The deterministic and attestation tiers can be tested without credentials:

```bash
autocodabench validate-bundle bundles/<slug>/          # markdown report
autocodabench validate-bundle bundles/<slug>/ --json   # machine-readable
autocodabench checks list                              # registered checks by tier
```

The `--judged` flag adds the advisory LLM tier, which requires a backend and is
therefore not keyless.

---

## 4. Run artifacts and platform execution

The `Done.` summary names the run directory, the plan, the bundle, the zip, the
final `docker_image`, any `updated_implementation_plan.md`, the cost, and the
validation report. The run directory has the following structure:

```
<run>/
  specs/implementation_plan.md          # the locked plan (Phase 1)
  specs/updated_implementation_plan.md  # deviations, if the build changed anything
  bundles/<slug>/                       # the bundle (competition.yaml + programs + data)
  bundles/<slug>.zip                    # the uploadable artifact
  run_logs/<slug>/                      # sandbox + stdout/stderr for each run (2c/2d)
  tool_calls/ + events.jsonl            # full MCP audit trail (also the replay format)
  agent_trace/{plan,build}.jsonl        # per-phase agent traces
```

When `<slug>.zip` is uploaded to Codabench, the compute worker runs the scoring
(and ingestion) programs inside the bundle's `docker_image`, mounting the active
program directory at `/app/program` and the data and output trees at
`/app/input` and `/app/output` — the layout `run_baseline_submission` stages
locally. To rehearse a participant submission against the finished bundle (the
path the `reformat-and-run` skill drives):

```python
from autocodabench.runner import run_user_submission
r = run_user_submission("<slug>", submission_dir="/path/to/a/submission")
print(r["ok"], r["scores"])
```

---

## Reference — keyless smoke tests by layer

```bash
python -m pytest tests/                      # unit suite (fast, fully keyless)
python -m autocodabench.core.bundle_io       # core authoring smoke (demo bundle in a tempdir)
autocodabench demo --out /tmp/demo           # replay authoring + validate (no LLM, no keys)
autocodabench validate-bundle <bundle>       # schema validation + Docker preflight banner
autocodabench checks list                    # registered checks by tier
python -m autocodabench.mcp.server           # MCP stdio server (blocks on stdin — expected)
python -c "from autocodabench.runner import docker_preflight; print(docker_preflight())"
```

The only phases that require Claude authentication are the live Phase 1 (plan)
and Phase 2 (build) agent sessions. Every step downstream of an existing bundle
on disk — image preparation, baseline scoring, notebook execution, and the
validation framework in its entirety — is keyless and Docker-backed, and can be
developed and tested in isolation using the snippets above.
