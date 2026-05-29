# AutoCodabench web UI — local dev + Hugging Face Spaces deploy

A private-alpha Chainlit chat surface over the 2-phase workflow
(Plan → Competition Creation). End-user docs live in
[`../auto_codabench/INSTRUCTION_FOR_USER.md`](../auto_codabench/INSTRUCTION_FOR_USER.md)
§A. This file is for the maintainer.

```
┌────────────────────────────────────────────────────────────────────┐
│ Browser  ─►  Chainlit app  ─►  ClaudeSDKClient ─► api.anthropic.com │
│                          │                                          │
│                          ├─► spawns: autocodabench MCP server       │
│                          │           alex-mcp MCP server            │
│                          │                                          │
│                          ├─► writes: auto_codabench/runs/web_…/     │
│                          │           transcript.md / events.jsonl   │
│                          │           specs/implementation_plan.md   │
│                          │           bundles/<slug>/<slug>.zip      │
│                          │                                          │
│                          └─► serves: /public/sessions/<sid>/...     │
│                                      (manifest.json + plan/         │
│                                       transcript/cost HTML +        │
│                                       bundle.zip + workspace.zip)   │
│                                                                     │
│ Browser  ─►  POST /ac/upload-codabench (workspace publish form)     │
│              direct HTTP — no LLM involved                          │
└────────────────────────────────────────────────────────────────────┘
```

---

## 0. Prerequisites

- An **Anthropic API key** (separate from Claude Max / Pro — see
  https://console.anthropic.com → API Keys). Top up ~$20 to cover
  trial usage.
- A **Hugging Face account** (free).
- The `semantic-scholar` conda env from the parent README, with
  `alex-mcp`, `autocodabench`, `chainlit`, and `claude-agent-sdk`
  installed. From repo root:
  ```bash
  conda activate semantic-scholar
  pip install -e .
  pip install "git+https://github.com/drAbreu/alex-mcp.git@v4.8.2"
  pip install -r web/requirements.txt
  ```

---

## 1. Run it locally (smoke test)

`.env` at the **repo root** (Chainlit auto-loads it):

```bash
ANTHROPIC_API_KEY=sk-ant-…
SHARED_PASSWORD=…                  # any 16-char random string
CHAINLIT_AUTH_SECRET=…             # run `chainlit create-secret` once
OPENALEX_MAILTO=you@example.com
AUTOCODABENCH_DEFAULT_MODEL=claude-sonnet-4-6
MAX_USD_PER_SESSION=5.0

# Optional — fallback for CLI uploads via autocodabench_upload_bundle.
# The web UI's workspace form takes credentials from the user directly
# and does NOT need these to be set.
CODABENCH_USERNAME=ihsanchalearn
CODABENCH_PASSWORD=…
```

Launch from inside `web/` (so Chainlit finds `chainlit.md` +
`.chainlit/config.toml`; the repo-root `.env` is still auto-loaded):

```bash
cd web
chainlit run app.py --host 127.0.0.1 --port 8500 -h
```

Open http://localhost:8500. Sign in with any username + the
`SHARED_PASSWORD`.

### Smoke-test checklist

1. ✅ Greeting appears with session ID, model name, and
   `budget $5.00`.
2. ✅ Phase pill bar at the top shows
   `[1. 📝 Plan]` (active, white) and
   `[2. 📦 Competition Creation]` (grayed out / 🔒).
3. ✅ Send "design a competition on detecting AI-generated text".
   Claude opens a run dir (visible under
   `auto_codabench/runs/web_*_<sid>/`) and starts asking 1-2 scope
   questions.
4. ✅ After the agent saves `specs/implementation_plan.md`, the
   workspace panel on the right shows the rendered plan, and the
   Phase 2 pill turns blue with ▶.
5. ✅ Click ▶ Advance, confirm. A fresh agent starts Phase 2 and
   writes the bundle (chips: `init_bundle`,
   `write_competition_yaml`, etc.). When done, the workspace footer
   shows `📦 competition bundle (.zip)` as a real download link
   alongside `📦 workspace.zip`.
6. ✅ Per-turn footer shows `turn ≈ $X · session $Y / $5.00 · ctx
   Z% (N tok)`.
7. ✅ Click the 🔒 Plan pill, confirm. Bundle gets wiped; Phase 1
   chat resumes for revisions.
8. ✅ (Optional) Expand the **🚀 Publish to Codabench** form in the
   workspace footer, enter username + password, click Upload.
   Status shows "uploading...", then the competition URL appears
   inline (30-90 s).

Ctrl-C to stop the local server.

---

## 2. Deploy to Hugging Face Spaces

### 2.1 Create a private Space

1. Log in to https://huggingface.co
2. Click **+ New → Space**.
3. Settings:
   - **Owner**: your user or org.
   - **Space name**: e.g. `autocodabench-alpha`.
   - **License**: `mit`.
   - **SDK**: **Docker** (Chainlit has no first-class template).
   - **Hardware**: `CPU basic — 2 vCPU · 16 GB RAM · free` is enough.
   - **Visibility**: **Private**.
4. Click **Create Space**.

### 2.2 Add Repository Secrets

Settings → Variables and secrets → **New secret** (Secrets table —
not Variables, which are public):

| Secret name | Required | Value |
|-------------|----------|-------|
| `ANTHROPIC_API_KEY` | ✅ | `sk-ant-…` from console.anthropic.com |
| `SHARED_PASSWORD` | ✅ | 16-char random; gates the UI |
| `CHAINLIT_AUTH_SECRET` | ✅ | `chainlit create-secret` output |
| `OPENALEX_MAILTO` | ✅ | any working email |
| `HF_TOKEN` | optional | `write` scope, for the per-session HF Dataset upload (`autocodabench-runs`). Skip → uploads silently no-op. |
| `CODABENCH_USERNAME` | optional | Fallback for the CLI MCP upload tool. The Web UI publish form takes credentials from the user directly. |
| `CODABENCH_PASSWORD` | optional | (same — fallback only) |

Optional Variables (visible in Space settings, not secrets):

| Variable | Default |
|----------|---------|
| `AUTOCODABENCH_DEFAULT_MODEL` | `claude-sonnet-4-6` |
| `MAX_USD_PER_SESSION` | `5.0` |

### 2.3 Push the code

The `Dockerfile` at the repo root is the source of truth for the
build. Two push options:

**Option A — git push (recommended)** so future updates are one
`git push` away:

```bash
# from repo root, on the try-web-ui branch
git remote add hf https://huggingface.co/spaces/<your-user>/autocodabench-alpha
git push hf try-web-ui:main
```

You'll be prompted for an HF write token (create at
https://huggingface.co/settings/tokens, scope: `write`).

**Option B — web upload.** Drag-and-drop the repo into the Space's
"Files" tab.

### 2.4 Watch the build

The "Logs" tab streams the build. First build ~5 min (pip install).
Subsequent ~30 s (cache hit). When the log says
`Your app is available at <URL>`, open it and sign in.

### 2.5 Invite collaborators

Settings → **Members → Add member** → paste their HF usernames (Read
role is enough). They open the URL, sign in with `SHARED_PASSWORD`.

---

## 3. Operational notes

### Phase model

Each web session has its own:
- **Run dir** at `auto_codabench/runs/web_<user>_<runtime>_<sid>/`.
- **MCP subprocess** with `AUTOCODABENCH_RUN_DIR` env set to that
  run dir. Bundles land at `<run>/bundles/<slug>/`.
- **Public session dir** at `web/public/sessions/<sid>/` with
  `plan.html`, `transcript.html`, `cost.html`, `bundle.zip`,
  `workspace.zip`, and `manifest.json` + `phase_state.json` polled
  by chat.js.

On every phase transition (Plan ↔ Competition Creation), the SDK
client is disconnected and a fresh one is spawned with the new
phase's system prompt and tool allowlist — the chat history is
dropped entirely.

### Cold start

HF Spaces puts a free-tier Space to sleep after ~48 h of no traffic.
First request wakes the container (~30 s).

### Where data lives

- **Inside the container**:
  `auto_codabench/runs/web_*` — chat transcripts, plan, bundle,
  cost log, MCP tool snapshots.
- **HF Dataset upload**: if `HF_TOKEN` is set, the run dir is
  uploaded (text-only allowlist) to a private dataset
  (`autocodabench-runs` by default; override with
  `AUTOCODABENCH_RUNS_REPO`). This is the only durable record —
  the container filesystem is ephemeral.

### Cost monitoring

- **Anthropic**: https://console.anthropic.com/usage updates every
  few minutes.
- **HF Spaces** (free tier): nothing to monitor.
- **Codabench**: each successful upload via the form creates a
  competition under whatever username the user typed. Track at
  https://www.codabench.org/profiles/me/ once signed in.

### Killing the alpha

1. Anthropic console → API keys → revoke (or unset the HF secret).
2. HF Space → Settings → Delete this Space.
3. Local: `git branch -D try-web-ui` (after merging anything to keep).

---

## 4. Troubleshooting

### Sign-in loop locally
`SHARED_PASSWORD` not set, or doesn't match what you're typing.
Username field is informational only.

### Phase pill stays disabled even after the agent says "plan saved"
The phase bar polls `web/public/sessions/<sid>/phase_state.json`
every 2 s. If it's not updating, look at the browser console for
fetch errors. Also confirm `specs/implementation_plan.md` actually
exists in the run dir.

### Bundle download stays grayed after Phase 2 finishes
Look at the Space logs for warnings from `_find_bundle_zip` — it
prefers `<run>/bundles/` and falls back to the global
`auto_codabench/bundles/` if the env propagation broke.

### Publish form: "unknown error" or any other unclear failure
The `/ac/upload-codabench` route returns a non-empty `error` string
for every failure path. If you ever see "unknown error" in the UI:
expand the `<details>` block below the error message — it includes
the full server response (HTTP status + body). Cross-reference
against the Space logs (search for `upload-codabench` lines).

### MCP server doesn't boot
Look at `web/.files/mcp_stderr_*` or the Space's main logs. Most
common: `fastmcp` version mismatch (the Dockerfile pins
`fastmcp==2.14.7`).

### HF Space build fails
Read the build log. Common causes:
- Missing required Repository Secret (see §2.2).
- Python version mismatch — the Dockerfile uses `python:3.11-slim`.
- A `pip install` step erroring on a network glitch — re-trigger
  the build (Settings → Factory rebuild).
