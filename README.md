---
title: AutoCodabench
emoji: 🧪
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: A scientific-friend chat assistant for designing Codabench competitions.
---

# AutoCodabench

A scientific-friend chat assistant that helps researchers turn a one-line
competition idea into a NeurIPS-Competition-Track-style proposal, an
implementation skeleton, and a ready-to-upload Codabench `.zip`.

> **This `README.md` is also the Hugging Face Spaces metadata file** —
> the YAML header above configures the Space (Docker SDK, port 7860).
> Don't delete it on the HF side; edit prose freely below.

## What's where

| Path | What it is |
|------|------------|
| `web/` | Chainlit app — the chat UI deployed by this Space (see `web/README.md` for local-dev + deploy details). |
| `auto_codabench/` | The autocodabench MCP server + skill files + bundle output. |
| OpenAlex MCP | Installed from upstream `git+https://github.com/drAbreu/alex-mcp.git@v4.8.2` by the Dockerfile and the local conda env — not vendored. |
| `documentation/codabench_bundle_upload/` | Reference Codabench REST-API upload helper. |
| `Dockerfile` | Used by HF Spaces to build the image. |

## Running locally

See [`web/README.md`](web/README.md) §1.

## Deploying as this Space

See [`web/README.md`](web/README.md) §2.

## What you need

- An Anthropic API key (Anthropic API is *separate* from Claude Max — set
  `ANTHROPIC_API_KEY` in HF Repository Secrets).
- An email for OpenAlex polite-pool (`OPENALEX_MAILTO`).
- Codabench login for the upload step.
- A shared password (`SHARED_PASSWORD`) gating the UI for your invited
  collaborators.

All of these go into HF Spaces **Settings → Variables and secrets**.
The Space template at deployment time will refuse to start cleanly
without `ANTHROPIC_API_KEY` and `SHARED_PASSWORD`.

## How it talks to itself

```
  Browser ─► Chainlit UI ─► ClaudeSDKClient ─► api.anthropic.com
                          │
                          ├─► subprocess: python -m auto_codabench.mcp_server.server
                          │      (write Codabench bundle files, log events, upload zip)
                          └─► subprocess: python -m alex_mcp.server
                                 (OpenAlex / PubMed / ORCID lookups)
```

## License

MIT.
