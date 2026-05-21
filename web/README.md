# AutoCodabench web UI — local dev + Hugging Face Spaces deploy

A private-alpha Chainlit chat surface over the orchestrator workflow.
Designed for 3-5 trusted collaborators, 1-2 weeks, then thrown away.

```
┌──────────────────────────────────────────────────────────────────┐
│ Browser ─► Chainlit app ─► ClaudeSDKClient ─► api.anthropic.com  │
│                          │                                        │
│                          └─► spawns:  autocodabench MCP server    │
│                                       alex-mcp MCP server         │
│                          │                                        │
│                          └─► writes:  auto_codabench/runs/web_…/  │
│                                       transcript.md / events.jsonl │
└──────────────────────────────────────────────────────────────────┘
```

---

## 0. Prerequisites

- An **Anthropic API key** (separate from Claude Max / Pro — see
  https://console.anthropic.com → API Keys). Top up ~$20 to cover the
  trial.
- A **Hugging Face account** (free).
- The `semantic-scholar` conda env from the project root README, with
  `alex-mcp`, `autocodabench`, `chainlit`, and `claude-agent-sdk`
  installed. If you've followed the parent README this is already done;
  otherwise:
  ```bash
  conda activate semantic-scholar
  pip install -e ../alex-mcp -e ../. -r requirements.txt
  ```

---

## 1. Run it locally (smoke test)

From the **repo root** (not from `web/`), set the env vars in `.env`
and launch Chainlit:

```bash
cd /Users/<you>/Documents/auto-codabench/web

# Repo-root .env should already contain (chainlit auto-loads it):
#   ANTHROPIC_API_KEY=sk-ant-…
#   SHARED_PASSWORD=…             (16-char random)
#   CHAINLIT_AUTH_SECRET=…        (run `chainlit create-secret` once)
#   OPENALEX_MAILTO=…
#   CODABENCH_USERNAME=ihsanchalearn
#   CODABENCH_PASSWORD=…
#   AUTOCODABENCH_DEFAULT_MODEL=claude-sonnet-4-6
#   MAX_USD_PER_SESSION=2.0

chainlit run app.py --host 127.0.0.1 --port 8500 -h
```

Note: run from inside `web/` so Chainlit finds `chainlit.md` and
`.chainlit/config.toml`. The repo-root `.env` is still auto-loaded.

Open http://localhost:8500. Sign in with any username and the
`SHARED_PASSWORD` value from `.env`.

Smoke-test checklist:
1. The greeting appears with the session ID and model name.
2. Send "hello" — Claude should reply within ~5 s.
3. Send "design a competition on detecting AI-generated text" — Claude
   should open a run and start asking exploratory questions (Phase 1A).
4. `ls auto_codabench/runs/` — a new `web_<user>_<ts>_<uuid>/` dir
   exists with `meta.json`, `transcript.md`, and tool snapshots.

Ctrl-C to stop the local server.

---

## 2. Deploy to Hugging Face Spaces

### 2.1 Create a private Space

1. Log in to https://huggingface.co
2. Click **+ New → Space**.
3. Settings:
   - **Owner**: your user or org.
   - **Space name**: `autocodabench-alpha` (or anything).
   - **License**: `mit`.
   - **SDK**: pick **Docker** (Chainlit doesn't have a first-class
     template; Docker gives us full control).
   - **Hardware**: `CPU basic — 2 vCPU · 16 GB RAM · free` is plenty.
   - **Visibility**: **Private**.
4. Click **Create Space**.

### 2.2 Add Repository Secrets

Go to the Space's **Settings → Variables and secrets → New secret**.
Add **each of these** (the *Secrets* table, NOT *Variables* — variables
are public):

| Secret name | Value |
|-------------|-------|
| `ANTHROPIC_API_KEY` | `sk-ant-…` from console.anthropic.com |
| `SHARED_PASSWORD` | The 16-char value from your local `.env` |
| `OPENALEX_MAILTO` | Any working email (e.g. yours) |
| `CODABENCH_USERNAME` | `ihsanchalearn` |
| `CODABENCH_PASSWORD` | (from your local `.env`) |

Optional Variables (not secrets — visible in the Space settings):

| Variable name | Value |
|---------------|-------|
| `AUTOCODABENCH_DEFAULT_MODEL` | `claude-sonnet-4-6` |
| `MAX_USD_PER_SESSION` | `2.0` |

### 2.3 Add the Dockerfile

In the Space repo, drop in this `Dockerfile` (the build system will
auto-detect and use it):

```dockerfile
FROM python:3.11-slim

# Faster install + smaller image
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install everything in one go so the build cache survives later edits.
COPY . /app
RUN pip install --upgrade pip && \
    pip install -e ./alex-mcp -e ./. && \
    pip install -r web/requirements.txt

# HF Spaces injects $PORT and expects the app to bind to 0.0.0.0
ENV CHAINLIT_HOST=0.0.0.0
ENV CHAINLIT_PORT=7860
EXPOSE 7860

WORKDIR /app/web
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "7860"]
```

### 2.4 Push the code

Two options:

**Option A — git push (recommended)** so future updates are one
`git push` away:

```bash
# From the repo root, on the try-web-ui branch
git remote add hf https://huggingface.co/spaces/<your-user>/autocodabench-alpha
git push hf try-web-ui:main
```

You'll be prompted for an HF write token (create at
https://huggingface.co/settings/tokens, scope: `write`).

**Option B — web upload.** Drag-and-drop the repo into the Space's
"Files" tab. Slower for big repos but no git config needed.

### 2.5 Watch the build

The Space's "Logs" tab streams the build. First build takes ~5 min
(pip install). Subsequent builds use the cache (~30 s).

When the log says `Your app is available at <URL>` — open it. Sign in
with `SHARED_PASSWORD`.

### 2.6 Invite collaborators

Settings → **Members → Add member** → paste their HF usernames. Each
gets push/read access depending on the role you pick (Read is enough).
They open the Space URL, sign in with `SHARED_PASSWORD`, start chatting.

---

## 3. Operational notes

### Cold start

HF Spaces puts a private free-tier Space to sleep after 48 h of no
traffic. A visitor's first request after sleep wakes the container
(~30 s). After that it's snappy until the next idle window.

### Where the data lives

Each chat session writes to `auto_codabench/runs/web_<user>_<ts>_<uuid>/`
*inside the running container*. On HF Spaces, that filesystem is
ephemeral — when the Space restarts (e.g. you push a new commit, or it
wakes from sleep), everything in `runs/` is **lost**.

For an alpha this is OK. If you want persistence:

- Attach a **Persistent Storage** to the Space (HF settings → Persistent
  Storage, small size paid feature ~$5/mo).
- Or have the app `aws s3 sync` the run dir on `on_chat_end`.
- Or just have your collaborators screenshot interesting moments.

### Killing the alpha

When you're done:

1. **Anthropic console** → API keys → revoke the key (or just unset the
   HF secret).
2. **HF Space** → Settings → Delete this Space.
3. Local: `git branch -D try-web-ui` (after merging anything you want
   to keep).

### Cost monitoring

- Anthropic: https://console.anthropic.com/usage — usage updates every
  few minutes.
- HF Spaces (free tier): nothing to monitor.
- Codabench: each successful upload creates a competition under the
  `ihsanchalearn` account, visible at
  https://www.codabench.org/profiles/me/.

---

## 4. Troubleshooting

### "Sign in" loop on the local app

Check `SHARED_PASSWORD` is set and matches what you're typing. The
default username field is informational — pick anything.

### Bot never replies after a message

- Open the terminal where you ran `chainlit run`. Look for errors —
  most often: missing `ANTHROPIC_API_KEY`, exhausted API credits, or
  the MCP subprocess failed to start.
- Run `python -m auto_codabench.mcp_server.server` separately to
  confirm the MCP server boots.

### "max_budget_usd exceeded"

Per-session cap hit. Reset by starting a new chat. Tune
`MAX_USD_PER_SESSION` upward if you need longer sessions.

### Tool calls fail with `init_bundle failed: bundle not initialised`

Claude tried a write tool before `init_bundle`. Tell it: *"You skipped
init_bundle; start over with that."*

### HF Spaces build fails

Read the build log carefully. Common causes:
- Forgot a required Repository Secret.
- `alex-mcp/` not pushed (it's a sibling directory, must be in the
  same repo on HF).
- Python 3.10/3.11 mismatch — pin the base image as in §2.3.

### Bot speaks but never opens a run

Open `auto_codabench/runs/` and look for the latest dir. If it doesn't
exist, the orchestrator skill failed to call `autocodabench_open_run`
— remind it: *"Please call autocodabench_open_run first."*
