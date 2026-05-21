# AutoCodabench — User Guide

> **Branch note (`try-alex-mcp`):** this branch uses the OpenAlex-based
> `alex-mcp` server in place of `semantic-scholar`. OpenAlex's polite-pool
> (just an email — `OPENALEX_MAILTO`) is far more reliable than
> unauthenticated SS, so most of the "rate-limited / citation pending"
> friction disappears. The autocodabench MCP server is unchanged.

You have one sentence about a competition idea ("a contest on detecting
AI-generated text"). You want to walk away with a `.zip` you can upload to
Codabench. This guide takes you from a fresh laptop to that `.zip`, with
Claude doing all the work via two MCP servers and three skills.

---

## 1. What this actually is, in 30 seconds

Two **MCP servers** plug into Claude:

- **alex-mcp (OpenAlex)** — lets Claude search papers, look up authors,
  cross-check against PubMed and ORCID. Used during planning to ground
  every metric / dataset / baseline suggestion in real published work.
  Authenticated via an email (`OPENALEX_MAILTO`) — no API key required.
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

| Session / Phase | What happens | What gets written | When it ends |
|-----------------|-------------|-------------------|--------------|
| **1A — Proposal crystallization** | Open-ended scientific conversation. Claude asks mind-opening questions, surfaces controversies in the literature, cites paper IDs to read. The goal is a NeurIPS-track-style competition proposal. | `auto_codabench/runs/<branch_id>_<runtime_id>/specs/project_proposal.md` (5–15 pages of structured markdown). Plus the run's transcript, events, and tool-call logs. | You say *"the proposal looks sharp"* / *"lock the proposal"* / *"draft the proposal"*. |
| **1B — Implementation skeleton** (optional, gated) | Claude translates the accepted proposal into 6 implementation specs + an implementation plan. No new design decisions — just translation. | `<run>/specs/01-…06-*.md` and `<run>/implementation_plan.md`. | You say *"ready to implement"* / *"start the specs"*. If you only wanted the proposal, you skip this phase entirely. |
| **2 — Execution** | A *fresh* chat. Subagents spawned from `implementation_plan.md` write data, scoring program, pages, assemble the bundle, validate, zip. | `auto_codabench/bundles/<slug>.zip` + per-subagent outputs under the same `<run>/artifacts/`. | The packager subagent produces a validated zip; meta-reviewer audits. |

That separation is the most important rule in this whole repo. If Claude
ever starts writing bundle files during Session 1, stop it and remind it of
the iteration-1 rule. Similarly, if Claude races into Phase 1B (specs)
before you've signed off the proposal, redirect them back to Phase 1A.

---

## 2. What you need on your machine

- **macOS, Linux, or WSL.** Windows native should work but isn't tested.
- **Miniconda or Anaconda.** If you don't have it:
  https://docs.conda.io/projects/miniconda/en/latest/
- **Claude Desktop OR Claude Code.** Either works.
- **An email for the OpenAlex polite pool** — set `OPENALEX_MAILTO=you@example.com`.
  Any real email works (OpenAlex uses it to identify you for support and
  to give you higher rate limits). **This is required** — alex-mcp will
  refuse to start without it. No registration needed; you do not get an
  API key, just give them a working email.
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
pip install -e ./alex-mcp
pip install -e .

# Create your .env (gitignored)
cp auto_codabench/.env.example .env
# Then open .env and set the OpenAlex polite-pool email:
#   OPENALEX_MAILTO=you@example.com
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
    "alex-mcp": {
      "command": "/Users/<you>/miniconda3/envs/semantic-scholar/bin/python",
      "args": ["-m", "alex_mcp.server"],
      "env": {
        "OPENALEX_MAILTO": "you@example.com"
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
should see `alex-mcp` and `autocodabench` both listed, with their tools
enumerated.

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

# Register the alex-mcp server (project scope). OPENALEX_MAILTO is REQUIRED;
# alex-mcp will refuse to start without it.
claude mcp add alex-mcp --scope project \
  --env OPENALEX_MAILTO=you@example.com -- \
  /Users/<you>/miniconda3/envs/semantic-scholar/bin/python \
  -m alex_mcp.server
```

Each command prints `File modified: <repo>/.mcp.json` on success. Verify:

```bash
claude mcp list
```

Expected output (the leading "Checking MCP server health…" is fine):

```
autocodabench: ... -m auto_codabench.mcp_server.server  - ✓ Connected
alex-mcp:      ... -m alex_mcp.server                   - ✓ Connected
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

### What Claude will do — Phase 1A (proposal crystallization)

This is **the main event of Session 1** and usually the longest part of
the whole workflow. Expect 10–50 turns of back-and-forth.

1. Open a run directory (`autocodabench_open_run`) and tell you where it is.
   Everything in this session lands inside it.
2. **NOT** restate your idea in two paragraphs. Get straight to a useful
   question.
3. Surface a real tension from the literature ("Sadasivan 2023 argues
   detection is futile; Krishna 2023 disagrees — which side do you
   lean?") and ask for your intuition.
4. Cycle: open question → paper searches → option framings (each cited
   with a chapter + OpenAlex Work ID) → your reaction → next exploration.
   Coverage builds across these dimensions (organized internally in the
   skill, not shown to you as a checklist):
   - **Motivation & scope** — what gap, who cares, falsifiable success criterion
   - **Task & data** — domain, languages, generators, sources, splits, leakage, distribution shift between phases
   - **Evaluation & ranking** — primary metric, secondary metrics, error bars, tie-breaking
   - **Rules & participant experience** — submission protocol (λ / γ), caps, starting kit, prize
   - **Ethics & broader impact** — dual-use, privacy, fairness, datasheets
   - **Schedule & sustainability** — phase lengths, post-comp release, FAIR, paper plan
   - **Reproducibility** — env spec, seed policy, winner reproducibility check
5. When the proposal feels sharp, you say so: *"the proposal looks
   crystallized"* / *"lock the proposal"* / *"draft the proposal"*.
   Claude then writes `<run>/specs/project_proposal.md` — 5–15 pages of
   markdown structured like a NeurIPS Competition Track submission
   (motivation, related work, task, data, evaluation, baselines, rules,
   schedule, ethics, sustainability, references).
6. Claude **stops** after writing the proposal. You read it in your
   editor, push back on anything, ask for revisions, OR move on.

### Your job in Phase 1A

- Answer questions thoughtfully — these are scientific questions, not a
  form. *"I don't know — what does the literature say?"* is a legitimate
  answer. Claude will search and bring back papers.
- **Push back** when a citation doesn't fit your context. *"That paper
  is about scientific abstracts; my audience is news articles."* Claude
  will revise.
- Volunteer angles Claude might miss. *"What about adversarial
  paraphrase attacks?"*. Researchers know their subfield better than
  Claude does.
- Read the proposal in your editor when it lands. Iterate as many
  times as you want by saying *"in §4, change …"* — Claude will rewrite
  and the old version is preserved in `specs_history/`.

### What Claude will do — Phase 1B (implementation skeleton, optional)

ONLY if you decide you want the implementation skeleton. Trigger phrases:
*"ready to implement"* / *"draft the implementation plan"* / *"move to
phase B"* / *"write the specs"*.

If you only wanted the proposal (e.g. for a NeurIPS Competition Track
submission), just say *"we're done"* and Claude stops without Phase 1B.

When triggered, Claude translates the *accepted* proposal into 7 files —
no new design decisions, just implementation grain:

- `specs/01-task-framing.md`
- `specs/02-data.md`
- `specs/03-metrics-and-leaderboard.md`
- `specs/04-baseline-and-starting-kit.md`
- `specs/05-bundle-and-pages.md`
- `specs/06-run-logging-and-env.md`
- `implementation_plan.md`

Then Claude **stops**. No bundle files exist yet; that's Session 2.

### Looking at what Claude has done so far

- `transcript.md` in the run dir is the full natural-language
  back-and-forth, with role headers and tool calls folded inline.
  **Read this first.**
- `transcript.jsonl` — the raw Claude Code session log (one JSON
  object per turn) for programmatic analysis.
- `events.jsonl` — structured timeline of MCP calls and skill events.
- `tool_calls/NNNN_*.json` — every MCP tool call with full
  request and response.
- `README.md` — a per-run cheatsheet auto-written when the session
  opens, explaining every file and giving `jq` one-liners.

See §9 below for the full postmortem workflow.

### Red flag

If Claude calls any `autocodabench_write_*` *bundle* tool during
Session 1, **stop it**:

> Stop. We're in Session 1 — no bundle files. Plan only.

If Claude jumps to writing `specs/01-task-framing.md` *before* you've
signed off on `project_proposal.md`, **stop it**:

> Stop. We're still in Phase 1A. Don't write the specs until I've
> accepted the proposal.

Both rules are hard rules in the orchestrator skill but Claude may drift
under context pressure; the reminders reset it.

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

### "alex-mcp searches return empty / the server won't start"

If alex-mcp won't start, the most likely cause is a missing
`OPENALEX_MAILTO`. The server *requires* it at boot and exits with
`sys.exit(1)` otherwise. Verify:

```bash
claude mcp list
# alex-mcp should print ✓ Connected
```

If it shows `✗ Failed to connect`, run it directly to see stderr:

```bash
conda activate semantic-scholar
OPENALEX_MAILTO=you@example.com python -m alex_mcp.server
# should print boot banner; Ctrl-C to exit
```

If `search_works` returns `total_count: 0`, broaden the query (drop
filters, switch `search_type` to `general`) or pass
`peer_reviewed_only=False` — alex-mcp filters aggressively to remove
preprint catalogs and data dumps, which can occasionally remove
legitimate papers.

OpenAlex's polite-pool is generous (10 req/sec by default; tens of
thousands per day). You should very rarely see rate-limit errors with
a real email set.

### (Legacy) Switching back to Semantic Scholar

This branch (`try-alex-mcp`) ships alex-mcp. The Semantic Scholar
server is still in `semantic-scholar-fastmcp-mcp-server/` and can be
re-enabled with:

```bash
claude mcp remove alex-mcp --scope project
claude mcp add semantic-scholar --scope project \
  --env SEMANTIC_SCHOLAR_API_KEY=YOUR_REAL_KEY \
  --env SEMANTIC_SCHOLAR_ENABLE_HTTP_BRIDGE=0 -- \
  /Users/$USER/miniconda3/envs/semantic-scholar/bin/python \
  -m semantic_scholar.server
```

Tunable env vars for SS (when re-enabled):
`SEMANTIC_SCHOLAR_MAX_RETRIES` (4), `SEMANTIC_SCHOLAR_BASE_BACKOFF`
(1.0 s), `SEMANTIC_SCHOLAR_MAX_BACKOFF` (30 s),
`SEMANTIC_SCHOLAR_UNAUTH_RATE` (40 / 5 min),
`SEMANTIC_SCHOLAR_DISABLE_CACHE=1`,
`SEMANTIC_SCHOLAR_CACHE_TTL_SECONDS` (600).
- The API occasionally has cold starts. If a search returns nothing,
  ask Claude to retry once.

### "Claude is making things up"

The orchestrator skill requires every metric / dataset / baseline
suggestion to be backed by **two attributions**:

1. A named book chapter — e.g. `Per Pavão et al. (Ch. 5 §5.3) …` from
   the `competition-design` skill.
2. An OpenAlex Work ID — e.g. `[oa:W4390175962]` — from a real
   `search_works` call.

If you see a claim without either, push back:

> Where did you get that? Cite the chapter and an OpenAlex Work ID, or
> remove the claim.

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

Every run dir also writes its own `README.md` at session-open time that
mirrors this table and includes context-specific `jq` snippets — that
README is the most up-to-date reference for any given run.

| File / dir | What it tells you |
|------------|-------------------|
| **`README.md`** | Auto-written cheatsheet for THIS run. Same info as the table below, plus `jq` recipes pre-filled with the run's name. **Read this first.** |
| **`transcript.md`** | The full natural-language Claude ↔ user conversation, rendered with role headers (👤 user / 🤖 claude). Tool calls and results are folded into `<details>` blocks so the prose stays readable. Mirrored after every assistant turn by the Claude Code `Stop` hook. |
| **`transcript.jsonl`** | Raw Claude Code session log (one JSON object per turn). Ground truth for programmatic analysis. |
| `meta.json` | When the run started, what git branch + SHA, conda env, pid, slug |
| `events.jsonl` | Structured timeline. One JSON object per line. `kind` = `run_opened`, `tool_call_started`, `hook_fired`, `question_asked`, `ss_searched`, `proposal_made`, `spec_written`, `iter1_done`, etc. (see orchestrator skill §11) |
| `tool_calls/NNNN_<tool>.json` | Full request + response of every MCP tool call, in order. Includes args, return value, duration_ms, error if any. |
| **`specs/project_proposal.md`** | The Phase 1A artifact — a NeurIPS-track-style competition proposal (5–15 pages). This is the source of truth for the whole rest of the workflow. |
| `specs/01-…06-*.md` | Phase 1B artifacts (only if you triggered Phase 1B). Implementation specs derived FROM the proposal. |
| `specs_history/` | Every rewrite of every spec / proposal, timestamp-suffixed. `diff` adjacent ones to see what Claude changed. |
| `implementation_plan.md` | The Session-2 input (only if you triggered Phase 1B). Lists subagents and what each will do. |
| `mcp_stderr/autocodabench.log` | Stderr from the autocodabench MCP server — useful when a tool errored silently. |
| `mcp_stderr/hook_errors.log` | (Only if non-empty) Errors from the transcript-mirroring hook. |
| `artifacts/<subagent>/` | Session-2 output: model checkpoints, plots, the meta-reviewer's report. |

### Useful commands

```bash
# The auto-written cheatsheet for this run (start here)
cat auto_codabench/runs/LATEST/README.md

# Read the conversation (rendered)
less auto_codabench/runs/LATEST/transcript.md

# All Claude's text-only output in order
jq -r 'select(.type=="assistant") | .message.content[]?
       | select(.type=="text") | .text' \
   < auto_codabench/runs/LATEST/transcript.jsonl

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
2. `pip install -e ./alex-mcp && pip install -e .`
3. Register both servers (Claude Code):
   ```bash
   claude mcp add autocodabench --scope project -- \
     /Users/$USER/miniconda3/envs/semantic-scholar/bin/python -m auto_codabench.mcp_server.server
   claude mcp add alex-mcp --scope project --env OPENALEX_MAILTO=you@example.com -- \
     /Users/$USER/miniconda3/envs/semantic-scholar/bin/python -m alex_mcp.server
   claude mcp list   # both should print ✓ Connected
   ```
   (Or, for Claude Desktop: edit `claude_desktop_config.json` per §4 and restart.)
4. Symlink the three skills into `~/.claude/skills/` (§5).
5. New Claude chat: `/autocodabench-orchestrator` + your one-sentence idea.
6. **Phase 1A**: iterate on the proposal until you say *"lock the
   proposal"*. Read `<run>/specs/project_proposal.md` in your editor.
7. (Optional) **Phase 1B**: say *"ready to implement"* to get the 6
   specs + `implementation_plan.md`. Skip this if you only wanted the
   proposal.
8. **New** Claude chat: "Execute `auto_codabench/runs/LATEST/implementation_plan.md`."
9. Upload `auto_codabench/bundles/<slug>.zip` to https://www.codabench.org.

That's it. The hard part is being patient in Phase 1A — let Claude
explore the idea space with you for many turns before you lock the
proposal. The depth of Phase 1A is what makes the rest of the pipeline
worthwhile.
