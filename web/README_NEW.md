# AutoCodabench Web UI

A Chainlit chat interface for agentic authoring of Codabench competition bundles.
Users describe a competition idea; the system plans, builds, validates, and
optionally publishes a complete Codabench bundle — all through a conversational UI.

---

## How it works

The UI runs a **3-phase pipeline** backed by the Claude Agent SDK. Each phase
is an isolated agent session; the only thing that carries forward between phases
is the locked artifact on disk.

```
Phase 1 — Plan               Phase 2 — Competition Creation     Phase 3 — Validation
─────────────────            ──────────────────────────────      ──────────────────────
User + agent design          Fresh agent reads the plan and      Agent runs the full
the competition in           writes a complete Codabench         check framework and
conversation.                bundle (competition.yaml,           produces a
                             scoring_program/, solution/,        validation_report.md.
Artifact produced:           pages/), then validates             (Placeholder in v1)
specs/implementation_        and zips it.
plan.md
                             Artifact produced: bundle.zip
```

Phase transitions are driven by the **phase pills** in the header bar. The user
clicks a pill to advance or revert; the UI disconnects the old SDK client and
builds a fresh one with the new phase's system prompt and tool allowlist.

---

## Running locally

```bash
# From the repo root:
pip install -e .
pip install -r web/requirements.txt
pip install 'git+https://github.com/drAbreu/alex-mcp.git@v4.8.2'   # not on PyPI

cp .env.example .env
# Edit .env — at minimum set SHARED_PASSWORD and ANTHROPIC_API_KEY (or log in
# with `claude /login` to use your Claude subscription instead of an API key).

cd web
chainlit run app.py --host 127.0.0.1 --port 8500 -h
```

Open http://127.0.0.1:8500, enter your `SHARED_PASSWORD`, and start chatting.

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | For multi-user | — | API key. Local dev can use subscription login instead. |
| `SHARED_PASSWORD` | Yes | — | Gates access to the UI (single shared password). |
| `OPENALEX_MAILTO` | Yes | — | Email for OpenAlex polite-pool (alex-mcp). |
| `CODABENCH_USERNAME` | For upload | — | Codabench account (can also be entered in the UI form). |
| `CODABENCH_PASSWORD` | For upload | — | Codabench password (can also be entered in the UI form). |
| `AUTOCODABENCH_DEFAULT_MODEL` | No | `claude-sonnet-4-6` | Claude model to use. |
| `MAX_USD_PER_SESSION` | No | `5.0` | Hard cost cap per session (USD). |
| `AUTOCODABENCH_CONTEXT_WINDOW` | No | `200000` | Token denominator for context-% display. |
| `HF_TOKEN` | For HF Spaces | — | Write-scoped HF token. Enables run upload to HF Dataset. |
| `AUTOCODABENCH_RUNS_REPO` | No | `ktgiahieu/autocodabench-runs` | HF Dataset repo for run uploads. |

---

## File structure

```
web/
├── app.py               # Chainlit entry point — hooks only, no business logic
├── config.py            # All constants: phases, tool allowlists, env var reads
├── session_manager.py   # SessionManager — chat start/message/end lifecycle
├── phase_manager.py     # PhaseManager — advance/revert, phase bar, bundle offer
├── streaming.py         # Shared agent response streaming loop (used by both
│                        # on_message and phase kickoffs)
├── artifacts.py         # Transcript, CostLog, PublicArtifacts, PhaseState
├── skills.py            # SKILL.md loader (strips frontmatter, returns body)
├── upload_route.py      # POST /ac/upload-codabench FastAPI endpoint
├── hf_persist.py        # HF Dataset upload after each turn
├── phases/
│   ├── plan.py          # Plan class — Phase 1 system prompt + revisit message
│   ├── bundle.py        # Bundle class — Phase 2 system prompt + kickoff
│   └── validate.py      # Validate class — Phase 3 (placeholder for v1)
├── public/
│   ├── login.css        # All custom CSS (login form, phase pills, workspace panel)
│   ├── chat.js          # All custom JS (phase pills, workspace panel, init lock)
│   └── sessions/        # Per-session HTML/JSON files served to the workspace panel
├── .chainlit/
│   ├── config.toml      # Chainlit configuration (cot, file upload, custom JS/CSS)
│   └── translations/    # UI string translations (en-US.json has the button labels)
└── chainlit.md          # Content shown in the README modal (📖 README button)
```

---

## Workspace panel

The right-side panel is injected by `chat.js` and refreshes every 3.5 s by
polling `/public/sessions/<sid>/manifest.json`. After every assistant turn,
`PublicArtifacts.write()` renders:

- **📝 implementation_plan.md** — the living plan document (Phase 1)
- **📄 transcript.md** — full conversation with tool calls as collapsibles
- **💰 cost.jsonl** — per-turn cost log
- **📦 bundle.zip** — the built bundle (Phase 2+), downloadable
- **📦 workspace.zip** — everything above as one archive

The **Publish to Codabench** form in the panel footer POSTs to
`/ac/upload-codabench` (handled by `upload_route.py`) using credentials
typed by the user — credentials never touch the LLM.

---

## Phase pills

The phase pills live in the Chainlit header (injected by `chat.js`). They poll
`/public/sessions/<sid>/phase_state.json` every 2 s. Clicking a pill:

- **Active pill** — flashes the README button (no action, already here)
- **Locked pill** — confirm dialog → triggers `AC_REVERT::<phase>` action
- **Pending pill with ▶** — confirm dialog → triggers `AC_ADVANCE::<phase>` action

The actual Chainlit action buttons are hidden in a silent chat message and
click-simulated by JS, keeping the Chainlit action callback system intact
while allowing the custom pill UI.

---

## Adding Phase 3 (Validation)

Phase 3 is currently a placeholder pill. To wire it up:

1. Implement `Validate.send_kickoff_message()` in `phases/validate.py` to
   call `run_agent_turn()` with the validation prompt.
2. Ensure the `test-competition-bundle` skill exists under
   `src/autocodabench/skills/test-competition-bundle/SKILL.md`.
3. The `_phase_artifact_exists` check in `artifacts.py` already handles
   `validation_report.md` — the agent just needs to write it.

---

## Deployment (HF Spaces)

The `Dockerfile` at the repo root is detected automatically by HF Spaces.
It installs `alex-mcp` from GitHub (not on PyPI), pins `fastmcp==2.14.7`,
installs the `autocodabench` package in editable mode, then installs
`web/requirements.txt`. The Space runs:

```
cd /app/web && chainlit run app.py --host 0.0.0.0 --port $PORT
```

Set these Repository Secrets on the Space:
`ANTHROPIC_API_KEY`, `SHARED_PASSWORD`, `OPENALEX_MAILTO`,
`CODABENCH_USERNAME`, `CODABENCH_PASSWORD`, `HF_TOKEN`, `CHAINLIT_AUTH_SECRET`
