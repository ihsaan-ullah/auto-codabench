# AutoCodabench — User Guide

You have one sentence about a competition idea ("a contest on detecting
AI-generated text"). You want to walk away with a `.zip` you can upload to
Codabench. This guide takes you from a fresh laptop to that `.zip`, with
Claude doing all the work via two MCP servers and three skills.

---

## 1. What this actually is, in 30 seconds

Two **MCP servers** plug into Claude:

- **semantic-scholar** — lets Claude search papers, fetch citations, get
  recommendations. Used during planning to ground every metric / dataset /
  baseline suggestion in real published work.
- **autocodabench** — lets Claude write Codabench bundle files
  (`competition.yaml`, scoring program, pages, etc.), lint them, and zip
  them. Purely local — it never touches the Codabench server.

Three **skills** in `auto_codabench/skills/` tell Claude *how* to use those
servers:

- `competition-design` — distilled rules of thumb from a 315-page book on
  designing competitions.
- `codabench-bundle` — the exact schema Codabench expects.
- `autocodabench-orchestrator` — the iterative loop you'll run in Session 1.

You have **two conversations** with Claude:

| Session                  | What happens                                                                                                              | What gets written                                            |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| **1 — Planning**  | Claude asks you questions, searches papers, makes proposals. You push back, iterate.*No bundle files are created.*      | `auto_codabench/runs/<branch_id>_<runtime_id>/` containing `specs/*.md`, `implementation_plan.md`, `events.jsonl`, `tool_calls/`, `mcp_stderr/` |
| **2 — Execution** | A fresh chat. Spawn subagents from the plan. They write data, scoring program, pages, assemble the bundle, validate, zip. | `auto_codabench/bundles/<slug>.zip` + further files inside the same run dir under `artifacts/` |

That separation is the most important rule in this whole repo. If Claude
ever starts writing bundle files during Session 1, stop it and remind it of
the iteration-1 rule.

---

## 2. What you need on your machine

- **macOS, Linux, or WSL.** Windows native should work but isn't tested.
- **Miniconda or Anaconda.** If you don't have it:
  https://docs.conda.io/projects/miniconda/en/latest/
- **Claude Desktop OR Claude Code.** Either works.
- **A free Semantic Scholar API key** (optional but recommended; without
  it you'll get hard rate limits): https://www.semanticscholar.org/product/api
- **git** to clone this repo.

---

## 3. One-time install (5–10 minutes)

```bash
# Clone the repo (skip if you already have it)
git clone <this-repo-url> auto-codabench
cd auto-codabench

# Create a dedicated conda env. The fastest way is to clone base.
conda create -n semantic-scholar --clone base -y
conda activate semantic-scholar

# Install BOTH MCP servers into the same env
pip install -e ./semantic-scholar-fastmcp-mcp-server
pip install -e .

# Create your .env (gitignored)
cp auto_codabench/.env.example .env
# Then open .env in any editor and paste your Semantic Scholar key:
#   SEMANTIC_SCHOLAR_API_KEY=...
```

Verify both packages installed by running the **in-process smoke test**:

```bash
python - <<'PY'
import asyncio
from fastmcp import Client
from auto_codabench.mcp_server.mcp import mcp
from auto_codabench.mcp_server import tools  # noqa

async def main():
    async with Client(mcp) as c:
        ts = await c.list_tools()
        print(f"OK: {len(ts)} autocodabench tools available")

asyncio.run(main())
PY
```

You should see `OK: 9 autocodabench tools available` (a one-line
`AuthlibDeprecationWarning` from fastmcp's optional auth module may
appear first — harmless, ignore it).

Also confirm the python path you'll need for Claude's config:

```bash
which python
# expected:  /Users/<you>/miniconda3/envs/semantic-scholar/bin/python
```

Copy that path — you need it in the next step.

---

## 4. Wire the MCP servers into Claude

Pick **A** or **B** based on which Claude you use.

### A. Claude Desktop

Open the config file (create it if absent):

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Add or merge:

```json
{
  "mcpServers": {
    "semantic-scholar": {
      "command": "/Users/<you>/miniconda3/envs/semantic-scholar/bin/python",
      "args": ["-m", "semantic_scholar.server"],
      "env": {
        "SEMANTIC_SCHOLAR_API_KEY": "paste-your-key-here-or-leave-blank"
      }
    },
    "autocodabench": {
      "command": "/Users/<you>/miniconda3/envs/semantic-scholar/bin/python",
      "args": ["-m", "auto_codabench.mcp_server.server"],
      "env": {
        "AUTOCODABENCH_BUNDLES_ROOT": "/absolute/path/to/auto-codabench/auto_codabench/bundles"
      }
    }
  }
}
```

Two things people get wrong:

1. **Absolute paths only.** Claude Desktop does not expand `~` and does not
   read your shell's PATH.
2. **The Python from the conda env**, not system Python. That's why the
   `command` ends in `…/envs/semantic-scholar/bin/python`.

**Restart Claude Desktop.** In the bottom-right of the chat window there's
a small icon (hammer / plug) showing connected MCP servers. Click it — you
should see `semantic-scholar` and `autocodabench` both listed, with their
tools enumerated.

### B. Claude Code (recommended for this repo)

Use the built-in `claude mcp add` command — it writes the canonical
project-scope file `.mcp.json` at the repo root for you. Do **not** edit
`.claude/settings.json` for MCP; that file is not read by Claude Code's
MCP loader (this is a common confusion).

From the repo root:

```bash
# Register the autocodabench server (project scope)
claude mcp add autocodabench --scope project -- \
  /Users/<you>/miniconda3/envs/semantic-scholar/bin/python \
  -m auto_codabench.mcp_server.server

# Register the semantic-scholar server (project scope; key optional).
# SEMANTIC_SCHOLAR_ENABLE_HTTP_BRIDGE=0 turns off the server's bonus HTTP
# bridge that otherwise tries to bind port 8000 — disable it unless you
# specifically want the REST surface, otherwise port conflicts will make
# the server fail to start.
claude mcp add semantic-scholar --scope project \
  --env SEMANTIC_SCHOLAR_API_KEY=your-key-or-leave-blank \
  --env SEMANTIC_SCHOLAR_ENABLE_HTTP_BRIDGE=0 -- \
  /Users/<you>/miniconda3/envs/semantic-scholar/bin/python \
  -m semantic_scholar.server
```

Each command prints `File modified: <repo>/.mcp.json` on success. Verify:

```bash
claude mcp list
```

Expected output (the leading "Checking MCP server health…" is fine):

```
autocodabench:    ... -m auto_codabench.mcp_server.server  - ✓ Connected
semantic-scholar: ... -m semantic_scholar.server           - ✓ Connected
```

If you see anything other than `✓ Connected`, the most likely cause is the
wrong absolute path to the conda env's `python`. Re-check with
`which python` while the env is activated.

Inside a chat you can also type `/mcp` to see the live tool count and
status.

> **Tip — user scope vs project scope.** `--scope project` writes
> `.mcp.json` next to your repo and is shared with collaborators (commit
> it). Use `--scope user` instead if you want the servers available in
> *every* directory you launch `claude` from; that writes to
> `~/.claude.json` and is per-machine.

---

## 5. Install the three skills

Skills tell Claude *how* to use the MCP servers. There are three; install
all of them.

### A. Globally (recommended — works in any project)

```bash
mkdir -p ~/.claude/skills
ln -s "$(pwd)/auto_codabench/skills/competition-design"          ~/.claude/skills/competition-design
ln -s "$(pwd)/auto_codabench/skills/codabench-bundle"            ~/.claude/skills/codabench-bundle
ln -s "$(pwd)/auto_codabench/skills/autocodabench-orchestrator"  ~/.claude/skills/autocodabench-orchestrator
```

### B. Project-scoped (only inside this repo)

```bash
mkdir -p .claude/skills
ln -s "$(pwd)/auto_codabench/skills/competition-design"          .claude/skills/competition-design
ln -s "$(pwd)/auto_codabench/skills/codabench-bundle"            .claude/skills/codabench-bundle
ln -s "$(pwd)/auto_codabench/skills/orchestrator"  .claude/skills/autocodabench-orchestrator
```

Restart Claude (Desktop) or relaunch `claude` (Code). Type `/skills` —
you should see all three listed.

---

## 6. Session 1 — your first conversation (planning only)

Start a **fresh** Claude conversation. The orchestrator skill is keyed on
phrases like "design", "plan", or "build a competition", so it should
auto-activate. To be safe, type `/autocodabench-orchestrator` to invoke
it explicitly the first time.

Then write your idea in one sentence. **Just one.** Don't pre-fill the
form — let Claude pull details out of you.

### Example opening prompt

```
/autocodabench-orchestrator

I want to design a Codabench competition on detecting AI-generated text.
```

### What Claude will do

1. Restate your idea in one paragraph so you can catch misunderstandings
   immediately.
2. Search Semantic Scholar for recent baselines (RAID, M4, DAIGT, etc.)
   and tell you what it found, with paper IDs.
3. Ask you **one** decisive question. Examples it might pick:
   - "Will submissions be prediction files or runnable code?"
   - "Do you already have a dataset, or will we use a public one?"
   - "Is this single-language English-only, or multilingual?"
4. Cycle Q&A + paper searches until every dimension is locked down or
   has a citation-backed proposal you've confirmed.
5. Open a run dir (`autocodabench_open_run`) and tell you where it is.
   Everything else in this session lands inside it:
   - `auto_codabench/runs/<branch_id>_<runtime_id>/specs/01-task-framing.md`
   - `…/specs/02-data.md`
   - `…/specs/03-metrics-and-leaderboard.md`
   - `…/specs/04-baseline-and-starting-kit.md`
   - `…/specs/05-bundle-and-pages.md`
   - `…/specs/06-run-logging-and-env.md`
   - `…/implementation_plan.md`
6. **Stop.** No bundle file under `bundles/<slug>/` exists yet.

### Your job in Session 1

- Answer questions briefly and honestly. "I don't know — what do you
  recommend?" is a valid answer. Claude has the `competition-design`
  skill to fall back on.
- **Push back** when something feels wrong. "The book says X but my
  audience is undergrads — adjust." Claude will revise.
- When all seven files exist, **read the specs** in your editor (they
  live under `auto_codabench/runs/LATEST/specs/`, which is a symlink to
  the active session). Anything ambiguous? Tell Claude in the same chat.
  Iterate until happy.
- If you want to see *exactly* what Claude has been doing,
  `cat auto_codabench/runs/LATEST/events.jsonl` is a structured timeline,
  and `ls auto_codabench/runs/LATEST/tool_calls/` shows every MCP tool
  call with its full request and response. (See §11 for the postmortem
  workflow.)

### Red flag

If Claude starts calling `autocodabench_write_competition_yaml` or any
`autocodabench_write_*` tool during Session 1, **stop it**:

> Stop. We're in iteration 1 — no bundle files. Plan only.

This is the orchestrator skill's hard rule. Claude may forget it under
context pressure; the reminder will reset it.

---

## 7. Session 2 — execution (a fresh conversation)

When you're happy with the specs and `implementation_plan.md`, **start
a brand-new chat**. (This is deliberate: a fresh context window keeps
the execution subagents focused.)

### Opening prompt

```
Execute auto_codabench/runs/LATEST/implementation_plan.md.

Use /agents to spawn the subagents it defines. Each subagent should
work in parallel where the plan permits.

CRITICAL: set AUTOCODABENCH_RUN_DIR to the same path as Session 1's
run so all execution-phase logs land in the same directory:
  export AUTOCODABENCH_RUN_DIR=$(readlink -f auto_codabench/runs/LATEST)

When done, the meta-reviewer subagent writes a final report at
<run>/artifacts/meta-reviewer/report.md summarising what was produced,
what validate_bundle said, and where the final .zip lives.
```

### What happens

The plan defines roughly these subagents (the exact list is whatever
Session 1 wrote — read your plan):

| Subagent             | Tools it can use                          | What it produces                                 |
| -------------------- | ----------------------------------------- | ------------------------------------------------ |
| `data-curator`     | filesystem +`autocodabench_attach_data` | populates `reference_data/`, `input_data/`   |
| `scoring-author`   | `autocodabench_write_scoring_program`   | `scoring_program/score.py` + `metadata.yaml` |
| `baseline-author`  | `autocodabench_write_solution`          | a "barely-passes" reference solution             |
| `pages-author`     | `autocodabench_write_page`              | overview / evaluation / terms / data pages       |
| `bundle-assembler` | `autocodabench_write_competition_yaml`  | the master `competition.yaml`                  |
| `bundle-validator` | `autocodabench_validate_bundle`         | runs the linter, fixes issues, retries           |
| `packager`         | `autocodabench_zip_bundle`              | the final `.zip` at the bundle root            |
| `meta-reviewer`    | read-only on logs/ + bundles/             | the final report (markdown + viz)                |

Each subagent has narrow permissions — the `pages-author` cannot
overwrite the scoring program, etc.

### What you end up with

```
auto_codabench/bundles/<slug>/                          ← the unpacked bundle (browse it)
auto_codabench/bundles/<slug>.zip                       ← upload THIS to Codabench
auto_codabench/runs/<branch_id>_<runtime_id>/           ← one folder per session
  ├── events.jsonl                                       ← structured timeline
  ├── tool_calls/NNNN_<tool>.json                        ← every MCP call captured
  ├── specs/                                             ← final specs
  ├── implementation_plan.md
  ├── specs_history/                                     ← versioned spec rewrites
  ├── mcp_stderr/autocodabench.log                       ← server stderr
  └── artifacts/<subagent>/                              ← Session-2 outputs (report, plots, etc.)
auto_codabench/runs/LATEST                              ← symlink to most recent run
```

Upload `<slug>.zip` to https://www.codabench.org → Benchmark →
"Submit a new benchmark". Codabench unpacks it server-side.

---

## 8. Troubleshooting

### "I don't see the MCP servers in Claude"

- **Claude Code:** run `claude mcp list`. Both should print `✓ Connected`.
  If they don't appear at all, you probably edited `.claude/settings.json`
  by hand — that file is **not** read by the MCP loader. Use
  `claude mcp add --scope project ...` instead; it writes the correct file
  (`.mcp.json` at the repo root). You can `cat .mcp.json` to confirm.
- **Claude Desktop:** quit fully (Cmd-Q) and reopen — config is read only
  at launch. Then click the plug/hammer icon and inspect server logs.
- In both cases, the Python path must be **absolute** and must point to
  the *conda env's* `python` (`…/envs/semantic-scholar/bin/python`), not
  system Python. `~` is not expanded.
- JSON validity: a missing comma silently disables the whole
  `mcpServers` block. If in doubt, pipe through `python -m json.tool`.

### "Claude says the tool failed"

Tool errors come back as `{"error": "..."}`. Common causes:

- **`init_bundle failed: bundle not initialised`** — you called a write
  tool before `init_bundle`. Tell Claude to init first.
- **`validate_bundle: missing required key 'leaderboards'`** — Claude
  wrote a partial `competition.yaml`. Have it fill the missing keys.
- **`zip_bundle: competition.yaml missing`** — same.

### "The orchestrator skill never activates"

Type `/autocodabench-orchestrator` explicitly at the start of the
conversation. Skills auto-activate on description matches but the
match isn't always confident.

### "Semantic Scholar searches return empty"

- Without an API key you're rate-limited to ~100 requests / 5 min and
  some queries time out. Set `SEMANTIC_SCHOLAR_API_KEY` in your config
  and restart Claude.
- The API occasionally has cold starts. If a search returns nothing,
  ask Claude to retry once.

### "Claude is making things up"

The orchestrator skill requires every metric / dataset / baseline
suggestion to be backed by an `<!-- ss:<paperId> -->` comment. If you
see a claim without one, push back:

> Where did you get that? Cite an S2 paperId or remove the claim.

### "My env doesn't have `fastmcp`"

You probably installed into the wrong conda env. Verify:

```bash
conda activate semantic-scholar
python -c "import fastmcp; print(fastmcp.__file__)"
```

If that fails, repeat step 3.

---

## 9. Postmortems — when something went wrong (or you just want to know what Claude did)

Every session — both planning (Session 1) and execution (Session 2) — writes
to a dedicated directory:

```
auto_codabench/runs/<branch_id>_<runtime_id>/
auto_codabench/runs/LATEST                  ← symlink to the most recent
```

### What's in there

| File / dir | What it tells you |
|------------|-------------------|
| `meta.json` | When the run started, what git branch + SHA, conda env, pid, slug |
| `events.jsonl` | Structured timeline. One JSON object per line. `kind` = `run_opened`, `tool_call_started`, `question_asked`, `ss_searched`, `proposal_made`, `spec_written`, `iter1_done`, etc. (see orchestrator skill §11) |
| `tool_calls/NNNN_<tool>.json` | Full request + response of every MCP tool call, in order. Includes args, return value, duration_ms, error if any. |
| `specs/` | The current set of specs. If you re-ran the orchestrator and the specs changed, only the latest is here. |
| `specs_history/` | Every rewrite of every spec, timestamp-suffixed. `diff` adjacent ones to see what Claude changed. |
| `implementation_plan.md` | The Session-2 input. Lists subagents and what each will do. |
| `mcp_stderr/autocodabench.log` | Stderr from the autocodabench MCP server — useful when a tool errored silently. |
| `artifacts/<subagent>/` | Session-2 output: model checkpoints, plots, the meta-reviewer's report. |

### Useful commands

```bash
# Latest run, at a glance
ls -la auto_codabench/runs/LATEST/
cat   auto_codabench/runs/LATEST/meta.json

# Greppable timeline (needs `jq`)
jq -c '{ts, kind, tool: (.tool // null), msg: (.message // null)}' \
  < auto_codabench/runs/LATEST/events.jsonl

# Which tool calls erred?
jq -c 'select(.error != null)' \
  < auto_codabench/runs/LATEST/events.jsonl

# Pretty-print a specific tool call by counter
cat auto_codabench/runs/LATEST/tool_calls/0003_*.json | python -m json.tool

# How a spec evolved
ls auto_codabench/runs/LATEST/specs_history/ | grep '01-task-framing'
diff auto_codabench/runs/LATEST/specs_history/01-task-framing.2026-05-20T15-12-04Z.md \
     auto_codabench/runs/LATEST/specs/01-task-framing.md
```

### Listing all sessions

```bash
ls -t auto_codabench/runs/             # newest first
```

Each directory name is `<branch_id>_<runtime_id>`, where `branch_id` is your
git branch at session start (slashes replaced with hyphens) and `runtime_id`
is `YYYYMMDDTHHMMSS` in UTC. So you can `cd` into any past run and read its
specs / events / tool calls without needing to remember the exact name.

### "I expected logs and the run dir doesn't exist"

The orchestrator skill is supposed to call `autocodabench_open_run` as its
very first MCP action. If you don't see a run dir, that step didn't happen
— check `auto_codabench/runs/LATEST` and look for the most-recent dir. If
none, the skill never activated; type `/autocodabench-orchestrator`
explicitly at the start of the next conversation.

---

## 10. Quick reference

### Paths you'll touch

| Path                                                                | What                          |
| ------------------------------------------------------------------- | ----------------------------- |
| `~/.claude/skills/` (or `.claude/skills/`)                      | Skill symlinks                |
| `~/Library/Application Support/Claude/claude_desktop_config.json` | Desktop MCP config            |
| `.mcp.json` (repo root)                                           | Claude Code MCP config (managed via `claude mcp add`) |
| `.env` (repo root)                                                | API keys, gitignored          |
| `auto_codabench/runs/<branch_id>_<runtime_id>/`                   | All artifacts of one session (gitignored): specs, plan, events, tool calls |
| `auto_codabench/runs/LATEST`                                      | Symlink to the most recent run |
| `auto_codabench/bundles/<slug>/`                                  | Generated bundle (gitignored) |
| `auto_codabench/bundles/<slug>.zip`                               | What you upload               |

### The 13 autocodabench tools (so you can read Claude's tool calls)

**Runs (Session 1 and Session 2 — manage the run dir):**

| Tool                              | When it runs                                                 |
| --------------------------------- | ------------------------------------------------------------ |
| `autocodabench_open_run`        | First MCP call of every session — opens the run dir         |
| `autocodabench_current_run`     | Sanity-check that a run is open                              |
| `autocodabench_log_event`       | Each milestone (question asked, SS searched, proposal made, …) |
| `autocodabench_snapshot_spec`   | Every spec write (also keeps a versioned copy)               |

**Bundle (Session 2 only):**

| Tool                                      | When it runs                                    |
| ----------------------------------------- | ----------------------------------------------- |
| `autocodabench_init_bundle`             | First, creates the empty skeleton               |
| `autocodabench_write_competition_yaml`  | After all other files exist, ties them together |
| `autocodabench_write_page`              | Overview / evaluation / terms / data tabs       |
| `autocodabench_write_scoring_program`   | `score.py` + `metadata.yaml`                |
| `autocodabench_write_ingestion_program` | (Only for code-submission competitions)         |
| `autocodabench_write_solution`          | Baseline / starting kit                         |
| `autocodabench_attach_data`             | Reference data, input data                      |
| `autocodabench_validate_bundle`         | Lint pass — always run before zipping          |
| `autocodabench_zip_bundle`              | Produces the final upload .zip                  |

### Commands cheatsheet

```bash
# Activate the env
conda activate semantic-scholar

# Run the data-layer self-test (no MCP, no Claude — just verifies file I/O)
python -m auto_codabench.mcp_server.bundle_io

# Manually boot the MCP server (it will hang on stdin — Ctrl-C to exit)
python -m auto_codabench.mcp_server.server

# Manually list tools through a real MCP client
python - <<'PY'
import asyncio
from fastmcp import Client
from auto_codabench.mcp_server.mcp import mcp
from auto_codabench.mcp_server import tools  # noqa

async def main():
    async with Client(mcp) as c:
        for t in await c.list_tools():
            print(t.name)

asyncio.run(main())
PY
```

---

## 11. The shortest possible recipe

1. `conda create -n semantic-scholar --clone base -y && conda activate semantic-scholar`
2. `pip install -e ./semantic-scholar-fastmcp-mcp-server && pip install -e .`
3. Register both servers (Claude Code):
   ```bash
   claude mcp add autocodabench --scope project -- \
     /Users/$USER/miniconda3/envs/semantic-scholar/bin/python -m auto_codabench.mcp_server.server
   claude mcp add semantic-scholar --scope project --env SEMANTIC_SCHOLAR_API_KEY=YOUR_KEY -- \
     /Users/$USER/miniconda3/envs/semantic-scholar/bin/python -m semantic_scholar.server
   claude mcp list   # both should print ✓ Connected
   ```
   (Or, for Claude Desktop: edit `claude_desktop_config.json` per §4 and restart.)
4. Symlink the three skills into `~/.claude/skills/` (§5).
5. New Claude chat: `/autocodabench-orchestrator` + your one-sentence idea.
6. Iterate until `specs/` + `implementation_plan.md` look right.
7. **New** Claude chat: "Execute `auto_codabench/implementation_plan.md`."
8. Upload `auto_codabench/bundles/<slug>.zip` to https://www.codabench.org.

That's it. The hard part is being patient in Session 1.
