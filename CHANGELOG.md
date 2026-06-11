# Changelog

All notable changes to autocodabench. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow
[SemVer](https://semver.org/).

## [Unreleased]

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
