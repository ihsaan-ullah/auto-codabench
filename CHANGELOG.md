# Changelog

All notable changes to autocodabench. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow
[SemVer](https://semver.org/).

## [Unreleased]

### Added
- **Phase-1 research capability** (`autocodabench.agent.research`): the plan
  phase can now consult external knowledge instead of the backbone's training
  data alone, across three sources with deliberate diversity (web search is
  demoted to a last resort because it is single-source and easily biased):
  - **OpenAlex** — recent related competition/benchmark papers (NeurIPS
    Competition / Datasets & Benchmarks tracks), via the external
    [`openalex-research-mcp`](https://github.com/oksure/openalex-research-mcp)
    server (topic/keyword works search, related-works, `top_ai_conferences`
    venue preset). Launched with `npx`; keyless (a courtesy email is polite).
  - **Kaggle** — how similar competitions are actually hosted (metric,
    submission caps, team-size limits, phase deadlines, full description/rules
    pages), via **first-party** tools in the autocodabench MCP server
    (`autocodabench_search_kaggle_competitions` / `..._get_kaggle_competition`,
    wrapping the Kaggle SDK). Public competitions only — no private key required
    (a shared throw-away token is used unless you set `KAGGLE_API_TOKEN` or have
    `~/.kaggle/`). Needs the `kaggle` package: `pip install autocodabench[research]`.
  - **Web search** (`WebSearch`/`WebFetch`) — last resort, for narrow factual
    lookups the structured sources can't answer.

  On by default; the CLI shows each source's status in the pre-run config banner
  and exposes `--no-research` (all off) plus `--no-openalex` / `--no-kaggle` /
  `--no-web-search`. The OpenAlex launcher is overridable via
  `AUTOCODABENCH_OPENALEX_MCP_CMD`; a missing launcher/package degrades
  gracefully (source marked unavailable, the plan still runs). **Benchmark
  fairness:** only the Claude backend can host external MCP / web tools, so
  create-bench records, per run, which sources the backbone could actually use
  (`research.backend_supported` / `research.effective`) — the asymmetry is
  recorded, not hidden. The network tools (`WebSearch`/`WebFetch`) are gated
  past the filesystem sandbox only for a research-granted plan phase;
  shells/`Task` stay denied.
- **Provenance & coverage table at end of Phase 1**: the plan hand-off now
  leads with a table that, for each of the seven design dimensions, marks
  whether the decision was specified by the source material (**✓**), partially
  specified (**⚠**), or inferred by the planner (**✗**), naming the evidence
  consulted — so a reviewer sees how much of the design rests on their input
  versus planner inference. The CLI renderer colours the glyphs (green/yellow/
  red). Phase-1 hand-off text is now written in measured scientific prose.

### Changed
- **`create` renamed to `plan-build-validate`** — the all-three-phases command
  now has an intuitive name that says what it does (plan → build → validate).
  `create` remains as a backwards-compatible alias, but all docs and new
  development target `plan-build-validate`.

### Fixed
- **Phase read boundary is now code-enforced** (`backends.sandbox.FsSandbox`):
  the Claude backend runs under `bypassPermissions`, so the per-phase tool
  allowlist was an *auto-approve* list, not a deny-list — generic `Bash`/`Read`/
  `Glob` could roam the whole filesystem, and the planner was observed reading a
  ground-truth bundle elsewhere in the repo. Each agent phase now declares the
  roots it may touch (`AgentTask.fs_roots` — its run/session workspace plus any
  `--data` dir); the Claude backend enforces them with a `PreToolUse` hook (plus
  `disallowed_tools` as a backstop) and the OpenAI-compatible backend checks
  before executing a tool in-process. Shell/network/`Task` tools are denied
  outright; file tools are confined to the declared roots. Wired into `plan`,
  `build`, and `create` (the reformat phase keeps `Bash` and its existing
  path-based isolation).

### Added
- **Live CLI progress** (`autocodabench.cli.progress.ProgressUI`): the agentic
  commands (`create`/`plan`/`build`) now show an animated status line —
  `Composing…`, a white blob sweeping a dim track, and per-phase elapsed
  seconds — so a long phase never looks frozen. Above it, the SDK's per-step
  stream is rendered as a friendly narrative: the agent's own narration, each
  tool call as a short action with a change summary (e.g. `⏺ Write scoring
  program  +84 lines`, `⏺ Edit score.py  +4 -2 lines`), and the milestones the
  agent addresses to the user. The animation runs only on a TTY; redirected
  output (logs, pipes) falls back to plain, ANSI-free scrollable lines.
  `--debug` keeps the full developer trace (raw tool errors, raw tool ids,
  gutter-ruled narration); `--quiet` keeps the final-summary-only mode.
  Markdown **tables** in the agent's narration (e.g. the Phase-1 plan summary)
  are now drawn as aligned, box-bordered terminal tables with per-cell wrapping
  instead of mangled raw `| … |` rows — a display-only fix in the CLI renderer;
  the stored markdown (and the web UI's rendering of it) is unchanged.
- **validate-bench** (`benchmark/autocodabench_validate_bench/`): the second
  end-to-end benchmark — seeds known authoring defects into a clean bundle and
  measures the validator's catch rate per tier (precision/recall/F1), with a
  judged false-positive probe on the clean bundle. The **deterministic tier is
  keyless and Docker-free** (clean bundle rebuilt from the replay fixture), so
  anyone can run it offline and the unit suite asserts it. The reusable defect
  library + scoring live in `autocodabench.bench.defects`.
- **Benchmark leaderboard** (Stage 3): `autocodabench.bench.leaderboard` +
  `benchmark/scripts/aggregate.py` fold every contributed
  `<bench>/results/<backbone>/*.json` into a committed `benchmark/LEADERBOARD.md`
  / `.json`, grouped by benchmark and backbone. A CI job runs `aggregate.py
  --check` so a PR that adds a result must regenerate the leaderboard.
- **`plan --pdf`**: the standalone `plan` command (and `plan_async`) now accept
  a PDF proposal too — `idea` is optional when `--pdf` is given, matching
  `create`.
- **`create --pdf <proposal.pdf>`**: the plan phase can take a PDF proposal
  directly. The PDF is extracted to text at the orchestrator
  (`core.proposal.pdf_to_text`, via `pypdf`) so every backbone — including the
  OpenAI-compatible one whose file tool is UTF-8-only — receives the same
  proposal in the plan prompt. The `idea` argument is now optional when
  `--pdf` is given.
- **`benchmark/` — pure-SDK end-to-end benchmarks.** `autocodabench_create_bench`
  measures PDF-proposal → working-bundle translation fidelity (plan
  completeness, build, execution, and *score fidelity* — each ground-truth
  submission scored through the generated bundle and compared to
  `expected_result.json` within tolerance). It drives every phase through the
  backend seam (`--backend claude|ollama:…|openai:…|URL#model`), so the
  backbone is a measured variable and runs work offline (Ollama) and on GPU
  workers. Reusable logic ships in the package: `autocodabench.bench`
  (`results` canonical versioned record, `audit` deterministic score auditor,
  `missing_info` aggregation, `report`) and `autocodabench.agent.reformat`
  (the reformat-and-run SDK phase). Contributed results are append-only JSON
  under `benchmark/<bench>/results/<backbone>/` (endpoint host only, never
  keys).
- A generic `write_file` tool (`Write` alias) in `backends.local_tools`, so
  non-Claude backbones can author an adapted submission in the
  reformat-and-run phase — preserving tool-surface parity.
- **Execution-based validation**: `validate` (and `create`'s phase 3)
  now *runs* the bundle, not just inspects it. Two new deterministic checks
  execute the bundle inside its declared `docker_image` — `baseline-execution`
  (runs the baseline through ingestion+scoring; gates on a missing score) and
  `starting-kit-execution` (executes the notebook; advisory). The report gains
  an **Execution** section recording which image ran, its host/arch fit
  (native vs QEMU), wall-clock duration, the scores produced, and which data
  was consumed. On by default in the CLI (`--no-execute` for static-only);
  off by default in the `validate_bundle_path(..., execute=False)` library call
  so programmatic/keyless use stays static and fast.
- **Execution cache**: successful baseline/notebook runs are recorded next to
  the bundle (`bundles/.acb_execution_cache.json`), keyed by a content hash of
  the bundle. Phase 3 reuses the build phase's runs when the bundle is
  unchanged and re-executes when any file changed (e.g. a hand-edit between a
  separately-run build and a later `validate`), so a stale result can
  never be trusted.
- **Per-phase output folders**: a `create` run is now one session directory
  (`<branch>_<timestamp>/`) with `phase1_plan/`, `phase2_build/`, and
  `phase3_validate/` subdirectories and a session `manifest.json`; phase 3
  writes `validation_report.md`/`.json`. A standalone `validate --execute`
  gets its own session (different prefix) containing only `phase3_validate/`,
  so generation and validation runs never share a prefix.

### Removed
- **The `claude -p` shell-out benchmark harness and interactive-MCP
  scaffolding.** `experiments/bundle_creation_test/` (the skill-driven,
  `claude --print`-based harness), the project `.mcp.json`, the `setup.sh`
  `.claude/` skill-symlink installer, and the `claude mcp add` user
  instructions are gone. Everything that drives an LLM now goes through the
  hermetic SDK / OpenAI-compatible backends (which register the MCP tool
  surface programmatically), so a benchmark run no longer depends on ambient
  `claude` CLI state and is reproducible anywhere. The competition instruments
  moved to `benchmark/autocodabench_create_bench/competitions/`; a
  deterministic auditor (`bench.audit`) replaces the former
  `submission-log-auditor` subagent.
- **The conda execution engine.** Execution is now **Docker-only**: every run
  — scoring, ingestion, and the starting-kit notebook — executes inside the
  bundle's declared `docker_image`, exactly as the Codabench worker does. A
  missing Docker daemon is a hard error rather than a host-side fallback. The
  notebook, previously the last conda-hosted step, now runs in the image too
  (bundle mounted at `/app` as the working directory, which also fixes a
  relative-path/CWD failure mode), using the pinned `jupyter`/`nbclient`
  toolchain baked into the autocodabench base images. `prepare_run_env` now
  ensures the image is available locally (pulling if needed); `install_env_extras`
  returns a "set docker_image to one that ships the dependency" error (run-time
  installation would diverge from the platform, which installs nothing); and
  `remove_run_env` is a no-op (containers run `--rm`). The `engine` argument
  accepts `auto`/`docker`; `conda` returns an explanatory error.

### Changed
- **CLI commands renamed for a clear three-phase pipeline.** The agentic
  surface is now `plan` (Phase 1), `build` (Phase 2), `validate` (Phase 3),
  and `create` (all three end to end), replacing the previous
  `plan-competition` / `create-bundle` / `validate-bundle` names. This is a
  **breaking change** — the old command names (and the `validate` alias for
  `validate-bundle`) are removed, not kept as aliases. `autocodabench -h` now
  groups the phases and explains how to run each one on its own or chain them
  with `create`.
- **`auth status` and `auth use` now verify by default.** Both realize the
  resolved auth preference and authenticate the agent SDK with it — one
  minimal live turn — rather than reporting only on-disk credential
  detection, which cannot prove a login is accepted. The verification is on
  by default (it was previously opt-in via `--probe`); pass `--no-probe` for
  static detection only (offline / CI). `--probe` is still accepted as a
  no-op. The Codabench section is relabeled to make clear those credentials
  are the codabench.org account login used only for publishing — never Claude
  or agent-SDK auth (Claude auth has no username/password concept).
- The standalone `codabench-validate` console script is removed; bundle
  validation is now the `autocodabench validate` subcommand. One console script,
  `autocodabench`, with subcommands; the validator still accepts any
  bundle directory or zip, hand-written or generated.

### Fixed
- **create-bench reformat phase could hang indefinitely.** A reformat agent
  that launched a background training process plus a file-watch "monitor" and
  ended its turn expecting an interactive notification would strand the run
  forever (no `final.json`). The non-interactive reformat footer now forbids
  background processes and requires synchronous, single-turn execution through
  `autocodabench_run_user_submission`, and `reformat_and_run_async` gained a
  wall-clock timeout (default 30 min) that fails the submission rather than
  blocking. Found by the first live create-bench run.
- **create-bench under-reported score fidelity on metric-name differences.**
  The auditor matched the produced score by exact metric-key name, so a
  freshly generated bundle that named its column `geometric_mean_accuracy`
  scored 0 agreement against a ground truth named `geometric_mean_accuracy_metric`
  even when the *number* matched within tolerance. `bench.audit.resolve_score`
  now matches exact → normalized-name → sole-numeric and records which tier
  matched (`metric_match`), so fidelity measures the reproduced score, not the
  column name.
- **Starting-kit notebook execution used an invalid command.** The runner
  invoked `jupyter execute --inplace --allow-errors=false`, but the pinned
  `nbclient` 0.7.4 exposes an argparse `jupyter execute` CLI with no
  `--inplace` and a bare `--allow-errors` flag (it rejects `=false`), so the
  step failed before running a single cell. Switched to
  `jupyter nbconvert --to notebook --execute --inplace
  --ExecutePreprocessor.timeout=-1`, which executes every cell, stops nonzero
  on the first error, and writes outputs back. Found by running the real Docker
  path on Apple silicon; regression-covered by an in-image build-time smoke
  test in both base Dockerfiles.
- CLI `create` runs no longer tell the user to click a "workspace panel",
  "phase bar", or "Advance to Phase 2" button — UI elements that do not exist
  on the command line. The plan skill body was made surface-neutral and the
  non-interactive footers now explicitly suppress web-UI references and supply
  a plain-text hand-off ("Phase 2 will now run automatically"); the web UI is
  unaffected (it keeps its own footer with the phase-bar wording).
- Runner misclassified a λ-style (prediction-file) bundle as γ-style when
  `ingestion_program/` existed but was empty — `init_bundle` creates that
  skeleton directory for every bundle, so the runner then tried to execute
  a nonexistent `ingestion.py`. Now requires the directory to hold
  runnable content. Surfaced by the first real docker-engine run of the
  demo bundle.
- `validate_bundle` falsely gated bundles using the legacy extensionless
  `metadata` program filename, which production Codabench accepts —
  found by validating the STYLE-TRANS-FAIR production reference bundle;
  regression-tested.

- **autocodabench base container images** (`docker/`): `autocodabench-base-cpu`
  (from `codalab/codalab-legacy:py312`) and `autocodabench-base-gpu` (from
  `codalab/codalab-legacy:gpu310`), each pre-loaded with the essential
  scientific-Python stack and a pinned starting-kit notebook toolchain
  (`nbclient`/`nbconvert` compatible with the runner's notebook invocation, the
  source of a long version-resolution loop in practice; each image's build now
  *executes* a tiny notebook so a broken toolchain fails the build rather than
  surfacing at run time). `docker/build_and_push.sh` builds and publishes both under a
  chosen namespace. These become the runner's default `docker_image`, resolved
  from `AUTOCODABENCH_DOCKER_IMAGE` / `AUTOCODABENCH_DOCKER_IMAGE_GPU` (or
  `AUTOCODABENCH_DOCKER_NAMESPACE`), replacing the legacy
  `codalab/codalab-legacy:py37` default. Pre-baking the dependencies lets most
  bundles run with no per-run installation — removing a frequent build failure
  and conserving model budget.
- **Final docker image is recorded and reported.** When the build phase's
  self-validation loop changes `docker_image` to obtain a passing run, the
  *final, proven* image is what `competition.yaml` records; `create` now prints
  it in the summary ("what Codabench will run"), and the build skill reports it
  in its closing block and as a `deviation` message — so the value uploaded to
  Codabench is the one already shown to work locally.
- **Docker runtime preflight banner.** `create` and `validate` now open
  with a Docker preflight: the `docker_image` that will run, its CPU
  architecture versus the host (native vs. slow QEMU emulation), and whether the
  Docker daemon is installed and running — surfacing Docker as the prerequisite
  it is, and warning before an emulated run silently crawls. On Apple silicon it
  recommends the multi-arch `codalab/codalab-legacy:py312` (resolves to arm64)
  for local testing, and tells the user to build the base image locally when the
  default is not yet available. Public helpers `docker_preflight`,
  `docker_daemon_status`, and `image_arch_status` in `autocodabench.runner`
  (best-effort; never raise). New doc `docs/post-create-pipeline.md` documents
  every post-`create` step and how to exercise each in isolation (keyless where
  possible).
- **`create` is no longer an opaque idle.** It now prints its full effective
  configuration before spending anything (backend, auth path, model, the exact
  output directory, sample data, cost cap, output mode, and the three pipeline
  stages), prompts for the output location when `--out` is not given, and
  confirms before starting (skip with `--yes`). An aborted confirmation removes
  the freshly created run dir. New `create` flags: `--out`, `--yes`/`-y`,
  `--debug`, `--quiet`, `--no-validate`.
- **Three-tier, user-oriented progress reporting for `create`.** The default
  output is a concise narrative for end users — a header per phase plus the
  plain-language milestone and *deviation* messages the agent emits (raw tool
  calls, raw output, internal reasoning, and benign parallel-call cancellations
  are omitted). `--debug` shows the full developer trace (cancellation cascades
  are relabelled as benign retries rather than errors), preceded by a notice
  that it is for diagnosing the pipeline, not routine use. `--quiet` prints only
  the final summary. Mechanism: a structured `on_event` callback on the backend
  contract (`AgentTask.on_event`; the Claude backend emits `tool_use` /
  `tool_result` / `text` / `result` events), and a user-facing channel carried
  by `autocodabench_log_event(kind="progress"|"deviation", message=...)`.
- **`updated_implementation_plan.md`.** When the build phase departs from the
  locked plan (for example, correcting a keyword argument removed in a recent
  library release), it records the bundle as actually built in
  `specs/updated_implementation_plan.md`, opening with a *Changes from the
  original plan* section (original specification → what changed → why). The
  original `implementation_plan.md` is preserved unchanged as the provenance
  record; absence of the updated file means the bundle matched the plan.
- **Version-robust planning guidance.** The planning skill now instructs the
  agent to specify the smallest set of constructor arguments that pins the
  intended behavior and to avoid keyword arguments deprecated or removed in
  recent library releases (so a concrete plan does not fail against the
  installed version), with `LogisticRegression(multi_class=...)` cited as the
  motivating case.
- **In-place Claude sign-in.** When the subscription path is chosen but no
  login is found (the `auth status` picker, `auth use subscription`, or the
  `create` / `--judged` preflight), autocodabench now asks for consent and,
  on agreement, launches Claude Code's own sign-in (`claude auth login
  --claudeai`) as a child process — no second terminal, no manual `/login`.
  Consent is always requested first ("We did not find your Claude
  credentials… sign in now?"); declining is a first-class outcome and the
  user can quit and run `claude auth login` themselves. Public helper
  `launch_claude_login()` in `autocodabench.auth`; autocodabench delegates the
  OAuth flow to the official CLI and never handles subscription tokens itself.
- **Masked credential inspection** in `autocodabench auth status`: the
  report now shows a non-recoverable preview of each configured secret
  rather than a bare boolean — `ANTHROPIC_API_KEY` as its scheme prefix
  plus last four characters and length, and a second block for the
  Codabench publishing credentials (`CODABENCH_USERNAME` in full,
  `CODABENCH_PASSWORD` and `CODABENCH_TOKEN` masked). Absent, set-but-empty,
  and present values are distinguishable. Public helpers `mask_secret`,
  `codabench_credentials_status`, and `describe_codabench_credentials` in
  `autocodabench.auth`.
- **Auth preference (choose without unsetting)**: a persisted
  `auto|subscription|api_key` preference (`~/.config/autocodabench/auth.json`,
  env override `AUTOCODABENCH_AUTH`). The Claude SDK prefers
  `ANTHROPIC_API_KEY` over a subscription login; instead of requiring users
  to delete the key, `auth use subscription` (or the picker in `auth status`)
  hides the key from the SDK for the run so the subscription is used.
  `autocodabench auth use <mode>` sets it non-interactively and can paste a
  key (hidden input, optional save to `./.env`) without editing files. Every
  command that starts a live model session prints an `INFO:` banner naming
  the auth in use (API key / subscription / none).
- **Docker execution engine** (platform-faithful runs):
  `run_baseline_submission` / `run_user_submission` (library + MCP tools)
  execute programs inside the bundle's declared `docker_image` exactly as the
  Codabench worker does (sandbox mounted at `/app`, working dir `/app/program`,
  legacy `$input`/`$output`/`$program` substitution, **no** requirements
  installation), so a clean local run is evidence the bundle will execute on
  Codabench; every result records `engine` / `docker_image`. (Superseded later
  in this release: the conda fallback was removed — see *Removed* above — and
  the default image is now the autocodabench base image.)
- **Interactive auth preflight**: `create` and `validate --judged` now
  check for a usable Claude auth path *before* starting a live session. On an
  interactive terminal with no auth, the CLI walks you through it —
  subscription login re-check, or paste an API key (input hidden, optional
  save to `./.env` with mode 600). Non-interactive contexts get a clear
  refusal (exit 2) with guidance instead of an opaque SDK failure mid-run.
- The CLI loads `<cwd>/.env` at startup (stdlib parser; never overrides
  real environment variables) — same convention as the web UI.
- `docs/validate-bundle-walkthrough.md`: a line-by-line execution trace
  of `autocodabench validate` for newcomers, with debugger
  breakpoints per stage.
- `docs/verification-catalog.md`: a complete inventory of all verification,
  in four layers — the 17 registered bundle checks (with the six lint
  condition families inside the structural gate), the dynamic execution
  stages, all 54 unit tests with what each establishes, and the
  system-level evidence (CI matrix, 12-defect seeded instrument, blinded
  harness).
- `docs/design-rationale.md`: derives the architecture from first principles —
  starting from a single-file if/else validator and introducing each layer
  (`core/`, `runner/`, `checks/`, `mcp/`, `backends/`, `agent/`) as the
  resolution of a concrete failure, with the contested decisions (plan/build
  split, keyless test split, validating imported bundles) argued explicitly.
- **Multi-backbone support**: `OpenAICompatBackend` — a stdlib
  tool-calling loop over any OpenAI-compatible chat-completions
  endpoint (Ollama local models, OpenAI, vLLM, LiteLLM proxies), with
  an in-process tool registry exposing the same `autocodabench_*`
  tool surface and writing the same `tool_calls/` audit trail as the
  MCP layer. `--backend claude[:model] | ollama:<model> |
  openai:<model> | <url>#<model>` on `create` and `validate --judged`;
  `resolve_backend()` in the library.
- **Backbone benchmark** (`experiments/backbone_bench/`): axis A
  (validator/judge quality — the E3 seeded-defect instrument,
  12 defect types, per-backbone catch rate + clean-bundle
  false-positive rate; deterministic baseline 9/9) and axis B
  (bundle-creation quality over the ground-truth competitions —
  protocol fixed, runs per backbone).
- `docs/scientific-validation.md` §6: explicit review-gauntlet mapping
  (F4 wrapper objection, F5 solver-grading, F6 overselling,
  F7 key/service walls + non-determinism).

## [0.2.0.dev0] — 2026-06-12

The repository restructured from an MCP-server-in-a-repo
(`auto_codabench/`) into the pip-installable **autocodabench** library
(`src/autocodabench/`).

### Added
- **Check framework** (`autocodabench.checks`): registered validation
  checks in three tiers — deterministic (gates), LLM-judged (advisory
  findings, never gates), attestation (human-certified) — each citing
  Pavão et al. (2024) or the Codabench schema. Declared
  `competition_facts.yaml` enables context-dependent checks
  (100/E test-set sizing, external-data rule, prize legality).
- **`codabench-validate` CLI** — validate any bundle directory or zip,
  hand-written or generated; `--judged` adds LLM-graded checks;
  `--json` for machine-readable reports.
- **Agent backends** (`autocodabench.backends`): the `AgentBackend`
  seam with two implementations — `ClaudeAgentBackend` (live, Claude
  Agent SDK; subscription login or `ANTHROPIC_API_KEY`) and
  `ReplayBackend` (keyless, deterministic re-execution of a recorded
  run's tool calls).
- **`autocodabench demo`** — offline end-to-end demo: replays a shipped
  recorded run into a real bundle, validates, zips. No keys, no network.
- **`autocodabench create`** — the plan→build pipeline as a CLI/library
  call: two isolated agent sessions joined by a locked
  `implementation_plan.md`, full `tool_calls/` audit trail per run.
- **`autocodabench auth status [--probe]`** — reports the active Claude
  auth path; warns when an exported `ANTHROPIC_API_KEY` shadows a
  subscription login.
- Unit test suite (keyless, sub-second) + GitHub Actions CI
  (3.10–3.13, Linux + macOS, including the offline demo and a
  wheel-content check).

### Changed
- Import path: `auto_codabench.mcp_server.*` → `autocodabench.{core,runner,mcp}.*`;
  MCP server entry point is `python -m autocodabench.mcp.server`.
- Artifact roots no longer live inside the package tree: runs and
  bundles default to `<cwd>/.autocodabench/` (override with
  `AUTOCODABENCH_HOME` / `AUTOCODABENCH_BUNDLES_ROOT` /
  `AUTOCODABENCH_RUNS_ROOT`).
- The Codabench upload helper moved into the package
  (`python -m autocodabench.upload.codabench_api`); the web UI and MCP
  tool share one `upload_zip()` implementation.
- The web UI consumes the installed package (skills, config, upload)
  instead of repo-relative paths.

### Removed
- `auto_codabench/` (superseded by `src/autocodabench/`),
  `test_pdf_folder/`, vendored predecessor-project tutorials under
  `documentation/`, and accumulated run artifacts (old web sessions,
  experiment runs).
