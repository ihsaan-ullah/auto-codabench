# auto_codabench — package internals

The `auto_codabench` Python package contains the **MCP server**, the
**skills**, and the bundle authoring code. End-user docs live in
[`INSTRUCTION_FOR_USER.md`](./INSTRUCTION_FOR_USER.md); read that
first if you just want to USE the workflow.

This README is for anyone editing the package itself.

---

## Layout

```
auto_codabench/
├── mcp_server/                  # FastMCP 2.x stdio server
│   ├── server.py                # entry point: python -m auto_codabench.mcp_server.server
│   ├── mcp.py                   # the shared FastMCP() instance
│   ├── config.py                # paths + resolve_bundle_dir(slug) (per-session aware)
│   ├── run_log.py               # open_run, current_run, log_event, snapshot_spec,
│   │                            #   logged_tool decorator (full audit trail)
│   ├── bundle_io.py             # pure file-I/O layer; no MCP; importable standalone
│   └── tools/
│       ├── runs.py              # autocodabench_open_run / current_run / log_event / snapshot_spec
│       ├── bundle.py            # init / write_competition_yaml / write_page /
│       │                        #   write_scoring_program / write_ingestion_program /
│       │                        #   write_solution / attach_data
│       ├── package.py           # validate_bundle / zip_bundle
│       └── upload.py            # upload_zip helper (env- OR param-credentials) +
│                                #   autocodabench_upload_bundle MCP wrapper
│
├── skills/
│   ├── plan/SKILL.md                    # Phase 1 — produces specs/implementation_plan.md
│   ├── autocodabench-implement/SKILL.md # Phase 2 — packages the bundle from the plan
│   ├── competition-design/SKILL.md      # reference — Pavão book rules of thumb
│   └── codabench-bundle/SKILL.md        # reference — Codabench bundle schema
│
├── bundles/                     # default global bundles root (gitignored). Per-session
│                                # bundles land at <run>/bundles/<slug>/ instead.
└── runs/                        # per-session run directories (gitignored).
    └── LATEST                   # symlink to the most recent run
```

---

## Key invariants

- **Per-session isolation.** `resolve_bundle_dir(slug)` defaults to
  `<AUTOCODABENCH_RUN_DIR>/bundles/<slug>/` when the env var is set
  (every web session sets it). The global
  `auto_codabench/bundles/<slug>/` is the fallback for CLI usage
  outside any active run. Two concurrent web sessions can't collide.
- **Run-dir adoption.** `current_run()` adopts `AUTOCODABENCH_RUN_DIR`
  on first call when `_current_run` is None — so a fresh MCP
  subprocess (spawned on every web phase transition) reliably
  resolves to its parent's session, not to the global `runs/LATEST`
  symlink.
- **Every tool call is captured.** `logged_tool(name)` in `run_log.py`
  wraps each `@mcp.tool` so the request + response + duration land
  under `<run>/tool_calls/NNNN_<tool>.json` + a one-liner in
  `<run>/events.jsonl`.

---

## MCP tools

14 tools total. The web app's allowlist exposes a subset per phase
(see `web/app.py:_TOOLS_BY_PHASE`).

### Run + logging

| Tool                            | Used by              | What it does                                           |
| ------------------------------- | -------------------- | ------------------------------------------------------ |
| `autocodabench_open_run`        | Phase 1 (web), CLI   | Create or adopt a run dir; route subsequent logs there |
| `autocodabench_current_run`     | Both phases          | Return active run path (`{opened: bool, path}`)        |
| `autocodabench_log_event`       | Both phases          | Append a structured event to `events.jsonl`            |
| `autocodabench_snapshot_spec`   | Phase 1 only         | Write `<run>/specs/<name>.md` + versioned copy         |

### Bundle authoring (Phase 2)

| Tool                                      | What it does                                                  |
| ----------------------------------------- | ------------------------------------------------------------- |
| `autocodabench_init_bundle`               | Create `<run>/bundles/<slug>/` skeleton                       |
| `autocodabench_write_competition_yaml`    | The master `competition.yaml`                                 |
| `autocodabench_write_page`                | One of `overview.md` / `evaluation.md` / `terms.md` / `data.md` |
| `autocodabench_write_scoring_program`     | `scoring_program/score.py` + `metadata.yaml`                  |
| `autocodabench_write_ingestion_program`   | (Only for γ code-submission competitions)                     |
| `autocodabench_write_solution`            | `solution/sample_code_submission/model.py` + sample data      |
| `autocodabench_attach_data`               | `reference_data` / `input_data` / `public_data`               |
| `autocodabench_validate_bundle`           | Schema lint — always run before zipping                       |
| `autocodabench_zip_bundle`                | Produces `<run>/bundles/<slug>/<slug>.zip`                    |
| `autocodabench_upload_bundle`             | Optional — publishes the zip to Codabench via REST API        |

---

## Install + wire-up (for editing the package)

```bash
# from repo root
conda create -n semantic-scholar --clone base -y
conda activate semantic-scholar
pip install -e .
pip install "git+https://github.com/drAbreu/alex-mcp.git@v4.8.2"
```

Sanity-check the data layer (creates a tiny demo bundle in a tempdir,
no MCP, no Claude):

```bash
python -m auto_codabench.mcp_server.bundle_io
# expect: { "ok": true, "issues": [] ... } then a zip_path line
```

Sanity-check the MCP server boots (it will hang on stdin — that's
correct; Ctrl-C to exit):

```bash
python -m auto_codabench.mcp_server.server
```

In-process tool-count check (14 tools):

```bash
python - <<'PY'
import asyncio
from fastmcp import Client
from auto_codabench.mcp_server.mcp import mcp
from auto_codabench.mcp_server import tools  # noqa: F401 — registers tools

async def main():
    async with Client(mcp) as c:
        ts = await c.list_tools()
        print(f"OK: {len(ts)} autocodabench tools available")
        for t in ts:
            print(" -", t.name)

asyncio.run(main())
PY
```

---

## Wire into Claude (CLI)

See [`INSTRUCTION_FOR_USER.md` §B.3](./INSTRUCTION_FOR_USER.md#b3-wire-the-mcp-servers-into-claude).

Both `claude mcp add` (Claude Code) and the
`claude_desktop_config.json` JSON form work; the underlying contract
is just "run `python -m auto_codabench.mcp_server.server` on stdio".

---

## Skills

The skill files in `skills/*/SKILL.md` are Markdown with YAML
frontmatter (`name`, `description`). Claude loads them when the
description matches user intent, or when the user types
`/<skill-name>` explicitly.

- `autocodabench-plan` — Phase 1 driver. Keep the hard rules at the
  top stable; the rest of the body can evolve.
- `autocodabench-implement` — Phase 2 driver. Reads the plan,
  produces a bundle.
- `competition-design`, `codabench-bundle` — pulled in by the two
  drivers as on-demand reference material.

For Claude Code project-scoped skills, drop them under
`.claude/skills/`. For globally-available skills, symlink into
`~/.claude/skills/` (the user guide shows the exact commands).

---

## Out of scope (deliberately)

- Codabench upload UI lives in the **web** app
  (`web/app.py:/ac/upload-codabench` FastAPI route), not in this
  package. The MCP `autocodabench_upload_bundle` tool exists as a
  CLI alternative.
- The notebook-based 3-phase flow lives on
  `try-web-ui-with-starting-kit` if we ever want to revive it.
- No Codabench compute-worker setup, no Docker images for scoring,
  no queue config. `validate_bundle` is the strongest local
  guarantee.
