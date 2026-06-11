# AutoCodabench — User Guide

You have a one-sentence idea for a Codabench competition. You want to
walk away with a `.zip` ready to upload (or already published on
Codabench). This guide takes you there two ways:

- **Web UI** — click-through chat at the AutoCodabench Space (or
  `chainlit run app.py` locally). 2 phases, no MCP config, no skill
  install — just sign in and chat. See §A.
- **CLI** — Claude Desktop or Claude Code, with the autocodabench MCP
  server + skills wired in. Same 2-phase shape, more knobs. See §B.

---

## What this actually is, in 30 seconds

Two **MCP servers** plug into Claude:

- **alex-mcp (OpenAlex)** — Claude searches papers, looks up authors,
  cross-checks against PubMed and ORCID, so every metric / dataset /
  baseline suggestion is grounded in real published work.
  Authenticated via an email only (`OPENALEX_MAILTO`) — no API key.
- **autocodabench** — Claude writes Codabench bundle files
  (`competition.yaml`, scoring program, pages, etc.), lints them,
  zips them, and (optionally) uploads them. Purely local apart from
  the upload step.

Two **skills** in `auto_codabench/skills/`:

- `autocodabench-plan` — Phase 1: walks the user through a short
  citation-grounded design conversation and saves
  `<run>/specs/implementation_plan.md`. Pure prose, no code.
- `autocodabench-implement` — Phase 2: reads the locked plan and
  packages a Codabench bundle directly (`competition.yaml`,
  `scoring_program/`, `solution/`, pages), validates, zips,
  optionally uploads. No intermediate notebook step.

Two **reference skills** that the two above lean on but you don't
invoke directly: `competition-design` (Pavão book rules of thumb) and
`codabench-bundle` (Codabench bundle schema).

**The flow is the same in both interfaces:**

```
your idea (one sentence)
        │
        ▼
┌──────────────────────────────────────────────────────────┐
│ Phase 1 — PLAN                                            │
│   Short citation-grounded chat. Agent saves               │
│   <run>/specs/implementation_plan.md (covering the 7      │
│   design sections: task, data, metric, baseline, rules,   │
│   ethics, schedule).                                      │
└──────────────────────────────────────────────────────────┘
        │  (you review the plan, advance)
        ▼
┌──────────────────────────────────────────────────────────┐
│ Phase 2 — COMPETITION CREATION                            │
│   Fresh agent (no Phase-1 chat history; only the plan).   │
│   Generates the bundle from the plan, validates, zips.    │
│   Optional one-click Codabench upload → competition URL.  │
└──────────────────────────────────────────────────────────┘
        │
        ▼
   bundle.zip  →  https://www.codabench.org/competitions/<id>/
```

The hard agent reset between phases is the whole cost-savings story —
Phase 2 reads only the plan, not the chat history. Make the plan
concrete (named sklearn classes for baselines, exact metric function
names) and Phase 2 packages without re-inviting design questions.

---

# A. Web UI — the easy path

The maintained AutoCodabench Space is at:

> `https://huggingface.co/spaces/<owner>/<space-name>`
> (Your operator will share the actual URL + the `SHARED_PASSWORD`
> out-of-band.)

You can also run it locally — see `web/README.md` §1.

## A.1 Sign in

You'll see a Chainlit login form: username (anything) + the
`SHARED_PASSWORD` your operator gave you. After signing in, a greeting
appears with your session ID, model name, and budget cap.

## A.2 The phase bar

At the top of the page, next to the **Readme** and **New chat**
buttons, you'll see two black pills:

```
[ 1. 📝 Plan ]  [ 2. 📦 Competition Creation ]
```

- **Active** pill (filled white): you're currently in this phase.
- **🔒 Locked** pill: this phase finished; click to go back and revise
  (a confirm dialog explains what gets discarded).
- **▶ Advance** pill (blue + ▶ glyph): the next phase is unlocked
  because the current phase's artifact exists; click to advance.
- Grayed pill: not yet eligible. Clicking it pulses the **Readme**
  button — that's the hint to open Readme to learn how the bar works.

## A.3 Phase 1 — Plan (chat)

Send your idea in one sentence ("a contest on detecting AI-generated
text"). The agent will:

1. Open a per-session run directory (visible in chat).
2. Show a 7-section table (Pavão Ch. 1-5) and ask 1-2 scope questions.
3. Search OpenAlex / PubMed / ORCID for relevant papers as you go.
4. Once you've answered, write `implementation_plan.md` to disk and
   announce it's ready.

You'll see the rendered plan in the **workspace panel on the right**
under the 📝 `implementation_plan.md` tab. Review it. If anything
critical from the chat is missing, tell the agent — it can re-snapshot
the plan.

When the plan looks right, click **▶ Advance to 2. 📦 Competition
Creation**. A confirm dialog explains what happens (Phase 2 starts
fresh; Phase 1 chat history is dropped; you can come back via 🔒 but
that discards the bundle).

## A.4 Phase 2 — Competition Creation (chat)

A fresh agent starts automatically. It reads the locked plan and
generates the bundle directly: `competition.yaml`,
`scoring_program/score.py` (implements your metric),
`solution/sample_code_submission/model.py` (the baseline class from
the plan), four standard pages. Then validates and zips.

When done, the workspace panel's **Downloads** section lights up with:

- **📦 competition bundle (.zip)** — your Codabench-ready zip.
- **📦 workspace.zip (all artifacts)** — plan + transcript + cost +
  bundle, one file for archival.

(Both buttons are visible from session start, grayed out until ready.)

## A.5 Publish — the Codabench form

Below Downloads in the workspace panel:

```
🚀 Publish to Codabench         ▾
  Username  [____________]
  Password  [____________]
  [🚀 Upload & publish]
```

Type your Codabench username + password and click **Upload &
publish**. This runs as a direct HTTP call to Codabench (4-step
upload + unpack poll, ~30-90 s) — **no LLM is involved**, so no
agent cost. When Codabench finishes unpacking, the competition URL
appears right in the form.

The credentials are sent over HTTPS to the Space and are never logged
or stored. They're only used for this single upload.

## A.6 Going back (revising the plan)

If you realize the plan was wrong after seeing the bundle:

1. Click the now-🔒 **Plan** pill at the top.
2. Confirm. The bundle gets discarded; the plan is preserved so you
   can edit it.
3. Chat with the agent to revise the plan (it has no memory of either
   the previous Phase 1 or the Phase 2 chat — only the saved plan).
4. When happy, click **▶ Advance to Phase 2** again. A new bundle
   regenerates from the updated plan.

## A.7 Watching the cost

After every assistant turn, you'll see a one-line footer:

```
turn ≈ $0.012 · session $0.34 / $5.00 · ctx 4.2% (8,415 tok)
```

- `turn` — what this turn cost.
- `session` — cumulative spend / per-session budget cap.
- `ctx` — input tokens / Sonnet's 200k context window (resets on
  phase advance).

Sessions hard-cap at `MAX_USD_PER_SESSION` (default $5). When you hit
it, send a fresh message and Claude will tell you the cap was hit.
Refresh the page to start a new session with a fresh budget.

## A.8 Things to know

- **Privacy.** Your conversation lands in a per-session run directory
  that the maintainer can see for postmortems. The Space uploads runs
  to a private HF Dataset (`autocodabench-runs`). Don't paste anything
  in chat you wouldn't want the maintainer to read.
- **Multiple tabs / windows.** Each tab is its own session with its
  own run dir and budget. They don't share state.
- **HF Space sleep.** A free-tier Space sleeps after ~48 h of no
  traffic. First visit after sleep takes ~30 s to wake.

---

# B. CLI — Claude Desktop / Claude Code

For power users who want to run the workflow locally without the web
UI. You get the same 2 phases (Plan + Competition Creation), driven
by the two skills, with results on your local filesystem.

## B.1 What you need on your machine

- **macOS, Linux, or WSL.**
- **Miniconda / Anaconda.**
- **Claude Desktop OR Claude Code.** Either works.
- **An email** for the OpenAlex polite pool (any working email; no
  registration). Required — alex-mcp won't start without it.
- **git** to clone this repo.

## B.2 Install (5-10 min, one time)

```bash
git clone https://github.com/ihsaan-ullah/auto-codabench.git
cd auto-codabench

# Dedicated conda env — name is arbitrary; we use semantic-scholar
# for historical reasons.
conda create -n semantic-scholar --clone base -y
conda activate semantic-scholar

# Install autocodabench + alex-mcp from upstream
pip install -e .
pip install "git+https://github.com/drAbreu/alex-mcp.git@v4.8.2"

# .env at the repo root (gitignored). Minimum:
#   OPENALEX_MAILTO=you@example.com
cp -n .env.example .env 2>/dev/null || true
# (open .env in your editor and set OPENALEX_MAILTO)
```

Verify autocodabench installed:

```bash
python -c "from auto_codabench.mcp_server import tools; print('ok')"
```

Find your conda env's Python path (you'll need this for Claude's
config):

```bash
which python
# expected: /Users/<you>/miniconda3/envs/semantic-scholar/bin/python
```

## B.3 Wire the MCP servers into Claude

Pick A (Claude Desktop) or B (Claude Code).

### B.3A Claude Desktop

Open the config file (create it if absent):

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Add or merge:

```json
{
  "mcpServers": {
    "alex-mcp": {
      "command": "/Users/<you>/miniconda3/envs/semantic-scholar/bin/python",
      "args": ["-m", "alex_mcp.server"],
      "env": { "OPENALEX_MAILTO": "you@example.com" }
    },
    "autocodabench": {
      "command": "/Users/<you>/miniconda3/envs/semantic-scholar/bin/python",
      "args": ["-m", "auto_codabench.mcp_server.server"]
    }
  }
}
```

Two things people get wrong:

1. **Absolute paths only.** Claude Desktop does not expand `~` and
   does not read your shell's PATH.
2. **The Python from the conda env**, not system Python.

Restart Claude Desktop. Bottom-right of the chat: a small hammer /
plug icon shows connected MCP servers. Click it — `alex-mcp` and
`autocodabench` should both be listed.

### B.3B Claude Code (recommended for this repo)

Use the built-in `claude mcp add` command — it writes the canonical
project-scope file `.mcp.json` at the repo root.

```bash
# Register autocodabench (project scope)
claude mcp add autocodabench --scope project -- \
  /Users/<you>/miniconda3/envs/semantic-scholar/bin/python \
  -m auto_codabench.mcp_server.server

# Register alex-mcp (project scope). OPENALEX_MAILTO is REQUIRED.
claude mcp add alex-mcp --scope project \
  --env OPENALEX_MAILTO=you@example.com -- \
  /Users/<you>/miniconda3/envs/semantic-scholar/bin/python \
  -m alex_mcp.server
```

Verify:

```bash
claude mcp list
# Both should print ✓ Connected
```

Use `--scope user` instead to make the servers available in every
directory.

## B.4 Install the skills

Symlink the two user-invocable skills (and the two reference skills
they lean on) into Claude's skills directory.

**Globally** (recommended):

```bash
mkdir -p ~/.claude/skills
ln -s "$(pwd)/auto_codabench/skills/plan"                ~/.claude/skills/autocodabench-plan
ln -s "$(pwd)/auto_codabench/skills/autocodabench-implement" ~/.claude/skills/autocodabench-implement
ln -s "$(pwd)/auto_codabench/skills/competition-design"  ~/.claude/skills/competition-design
ln -s "$(pwd)/auto_codabench/skills/codabench-bundle"    ~/.claude/skills/codabench-bundle
```

**Project-scoped** (only inside this repo): swap `~/.claude/` for
`.claude/`.

Restart Claude Desktop or relaunch `claude` (Code). Type `/skills` —
you should see all four listed.

## B.5 Phase 1 — Plan

Start a **fresh** Claude conversation. Invoke the planning skill:

```
/autocodabench-plan

I want to design a Codabench competition on detecting AI-generated text.
```

What happens:

1. The skill auto-runs `autocodabench_open_run(slug=<short-kebab>)`
   and tells you the run dir path.
2. Claude shows the 7-section table and asks 1-2 scope questions.
3. After you answer, Claude searches OpenAlex briefly and writes
   `<run>/specs/implementation_plan.md`.
4. Claude **stops** and tells you to start a fresh chat for Phase 2.

Read the plan in your editor. Push back if something's wrong:

> In §3, the metric should be macro-F1 not accuracy.

Claude re-snapshots the plan. The previous version is preserved under
`<run>/specs_history/`.

## B.6 Phase 2 — Competition Creation

When the plan looks right, **start a fresh Claude chat** (a clean
context window is the whole point — no Phase 1 history). Invoke the
implementation skill:

```
/autocodabench-implement
```

That's it. The skill:

1. Calls `autocodabench_current_run()` to locate your most recent
   run dir (via the `LATEST` symlink under `auto_codabench/runs/`).
2. Reads `<run>/specs/implementation_plan.md`.
3. Generates the bundle (`competition.yaml`, `scoring_program/`,
   `solution/`, `pages/`).
4. Validates + zips → `<run>/bundles/<slug>/<slug>.zip`.

When done, the bundle is in `<run>/bundles/<slug>/<slug>.zip`. Browse
the unpacked tree at `<run>/bundles/<slug>/` to inspect what Claude
wrote.

To publish to Codabench in the same chat, say:

```
publish to Codabench.
```

This requires `CODABENCH_USERNAME` + `CODABENCH_PASSWORD` (or
`CODABENCH_TOKEN`) in env. The skill calls the upload tool, polls for
~30-90 s, and surfaces the competition URL.

If you'd rather upload manually, take the `.zip` to
https://www.codabench.org → Benchmark → "Submit a new benchmark".

## B.7 Where everything lives

```
auto_codabench/runs/<branch_id>_<runtime_id>/   ← per session
  ├── meta.json                                  ← branch / git_sha / slug / start time
  ├── events.jsonl                               ← structured timeline of MCP calls
  ├── tool_calls/NNNN_<tool>.json                ← every MCP call captured (args + return)
  ├── specs/implementation_plan.md               ← Phase 1 artifact
  ├── specs_history/                             ← every revision, timestamped
  ├── transcript.md                              ← natural-language conversation
  ├── transcript.jsonl                           ← raw Claude Code session log
  ├── bundles/<slug>/                            ← Phase 2 artifact (unpacked)
  ├── bundles/<slug>/<slug>.zip                  ← the upload-to-Codabench zip
  └── mcp_stderr/autocodabench.log               ← server stderr

auto_codabench/runs/LATEST                       ← symlink to the most recent run
```

(Bundles live UNDER the per-session run dir to keep concurrent
sessions isolated. If `AUTOCODABENCH_RUN_DIR` isn't set the bundles
fall back to the global `auto_codabench/bundles/` — but that's only
for one-off CLI usage with no active run.)

## B.8 Postmortems

Useful commands:

```bash
# Read the conversation
less auto_codabench/runs/LATEST/transcript.md

# Greppable timeline
jq -c '{ts, kind, tool: (.tool // null), msg: (.message // null)}' \
  < auto_codabench/runs/LATEST/events.jsonl

# Which tool calls erred?
jq -c 'select(.error != null)' \
  < auto_codabench/runs/LATEST/events.jsonl

# Pretty-print a specific tool call by counter
cat auto_codabench/runs/LATEST/tool_calls/0003_*.json | python -m json.tool

# How the plan evolved
diff auto_codabench/runs/LATEST/specs_history/implementation_plan.<ts>.md \
     auto_codabench/runs/LATEST/specs/implementation_plan.md
```

Each run dir also writes its own `README.md` at session-open time with
context-specific `jq` snippets — that README is the most up-to-date
reference for any given run.

---

# Troubleshooting

### Web UI: "unknown error" from the Publish form
You should never see this anymore (the route returns explicit error
messages for every failure path). If you do, expand the
`<details>` block below the error to see the full server response,
and report it to the operator with the session ID from the greeting.

### Web UI: bundle download button stays grayed
Phase 2 hasn't finished writing the bundle. Send a message in chat
and Claude will tell you what state it's in.

### CLI: "I don't see the MCP servers in Claude"
- **Claude Code:** `claude mcp list` — both should print ✓ Connected.
  If they don't appear, you probably edited `.claude/settings.json`
  by hand; that file is NOT read by the MCP loader. Use
  `claude mcp add --scope project ...` (writes `.mcp.json` at the
  repo root).
- **Claude Desktop:** quit fully (Cmd-Q) and reopen — config is read
  only at launch.

### CLI: alex-mcp won't start
Almost always a missing `OPENALEX_MAILTO`. Verify with:
```bash
OPENALEX_MAILTO=you@example.com python -m alex_mcp.server
# should print a boot banner; Ctrl-C to exit
```

### CLI: tool call fails with "init_bundle failed: bundle not initialised"
Claude tried a write tool before `init_bundle`. Tell it: *"You
skipped init_bundle; start over with that."*

### CLI: Phase 2 starts looking for the wrong plan
The skill resolves the run dir via `autocodabench_current_run()`,
which adopts `AUTOCODABENCH_RUN_DIR` from env or falls back to
`runs/LATEST`. If you advanced to Phase 2 in a different conversation
than your most recent Phase 1, point it explicitly:
> Read `auto_codabench/runs/<branch>_<ts>/specs/implementation_plan.md`
> and follow autocodabench-implement.

### CLI: "Claude is making things up"
Both skills require citations to be clickable markdown links
(`[Author YYYY](https://openalex.org/Wxxxxx)` or
`[Pavão Ch. X §Y](https://ai-competitions-book.github.io/...)`).
If you see a claim without either:
> Where did you get that? Cite the chapter and an OpenAlex Work ID,
> or remove the claim.

---

# Quick reference

### Paths you'll touch (CLI)

| Path | What |
|------|------|
| `~/.claude/skills/` (or `.claude/skills/`) | Skill symlinks |
| `~/Library/Application Support/Claude/claude_desktop_config.json` | Desktop MCP config |
| `.mcp.json` (repo root) | Claude Code MCP config |
| `.env` (repo root) | `OPENALEX_MAILTO`, optionally `CODABENCH_USERNAME` / `CODABENCH_PASSWORD` for CLI uploads |
| `auto_codabench/runs/<branch>_<ts>/` | Per-session artifacts |
| `auto_codabench/runs/LATEST` | Symlink to the most recent run |

### The autocodabench tools (so you can read Claude's tool chips)

**Run dir + logging:**

| Tool | When |
|------|------|
| `autocodabench_open_run` | First MCP call of every session |
| `autocodabench_current_run` | Sanity-check / locate active run dir |
| `autocodabench_log_event` | At every milestone |
| `autocodabench_snapshot_spec` | Plan writes (versioned in `specs_history/`) |

**Bundle authoring (Phase 2):**

| Tool | When |
|------|------|
| `autocodabench_init_bundle` | First — creates the empty skeleton |
| `autocodabench_write_competition_yaml` | After all other files exist |
| `autocodabench_write_page` | Overview / evaluation / terms / data |
| `autocodabench_write_scoring_program` | `score.py` + `metadata.yaml` |
| `autocodabench_write_ingestion_program` | (Only for γ code-submission competitions) |
| `autocodabench_write_solution` | Baseline / starting kit |
| `autocodabench_attach_data` | `reference_data` / `input_data` / `public_data` |
| `autocodabench_validate_bundle` | Lint — always run before zipping |
| `autocodabench_zip_bundle` | Produces the final upload `.zip` |
| `autocodabench_upload_bundle` | Optional — publishes to Codabench |

### Shortest possible CLI recipe

```bash
# 1. Install
conda create -n semantic-scholar --clone base -y && conda activate semantic-scholar
pip install -e . "git+https://github.com/drAbreu/alex-mcp.git@v4.8.2"

# 2. Register MCP servers (Claude Code)
claude mcp add autocodabench --scope project -- \
  /Users/$USER/miniconda3/envs/semantic-scholar/bin/python -m auto_codabench.mcp_server.server
claude mcp add alex-mcp --scope project --env OPENALEX_MAILTO=you@example.com -- \
  /Users/$USER/miniconda3/envs/semantic-scholar/bin/python -m alex_mcp.server
claude mcp list                                # both ✓ Connected

# 3. Symlink skills
mkdir -p ~/.claude/skills
ln -s "$(pwd)/auto_codabench/skills/plan"                ~/.claude/skills/autocodabench-plan
ln -s "$(pwd)/auto_codabench/skills/autocodabench-implement" ~/.claude/skills/autocodabench-implement
ln -s "$(pwd)/auto_codabench/skills/competition-design"  ~/.claude/skills/competition-design
ln -s "$(pwd)/auto_codabench/skills/codabench-bundle"    ~/.claude/skills/codabench-bundle

# 4. Phase 1 — new chat
#    /autocodabench-plan
#    "design a competition on <your idea>"
#    iterate until plan looks right

# 5. Phase 2 — FRESH chat
#    /autocodabench-implement
#    "publish to Codabench."   # only if you want the upload

# 6. Bundle is at auto_codabench/runs/LATEST/bundles/<slug>/<slug>.zip
```

The hard part is being concrete in Phase 1. A B+ plan with named
sklearn classes for baselines and exact metric function names ships
faster than an A+ plan full of "an appropriate model".
