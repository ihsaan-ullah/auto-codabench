# Dockerfile for the AutoCodabench Chainlit app — used by Hugging Face
# Spaces (Docker SDK). HF auto-detects this at the repo root.
#
# Local test (optional):
#   docker build -t autocodabench-web .
#   docker run -p 7860:7860 \
#     -e ANTHROPIC_API_KEY=sk-... -e SHARED_PASSWORD=... \
#     -e OPENALEX_MAILTO=... -e CODABENCH_USERNAME=... \
#     -e CODABENCH_PASSWORD=... -e CHAINLIT_AUTH_SECRET=... \
#     autocodabench-web

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git is needed by claude-agent-sdk for git-aware behavior;
# build-essential helps if any wheel needs to compile from sdist.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git build-essential && \
    rm -rf /var/lib/apt/lists/*

# HF Spaces runs as a non-root user (uid 1000). Create a matching one so
# pip + writing to /app/auto_codabench/runs/ works without permission errors.
RUN useradd -m -u 1000 user
WORKDIR /app

# Copy everything (the build context is the repo root). Adjust .dockerignore
# to keep the image small.
COPY --chown=user:user . /app

# Install the two MCP packages (alex-mcp + autocodabench) editable so that
# `python -m alex_mcp.server` and `python -m auto_codabench.mcp_server.server`
# work as the agent SDK spawns them.
RUN pip install --upgrade pip && \
    pip install -e ./alex-mcp && \
    pip install -e . && \
    pip install -r web/requirements.txt && \
    chown -R user:user /app

USER user
ENV HOME=/home/user

# HF Spaces injects $PORT; default to 7860 for local runs.
EXPOSE 7860

# Chainlit needs to be run from web/ so it picks up .chainlit/config.toml
# and chainlit.md. The app itself bootstraps PYTHONPATH for the rest of
# the repo (see web/app.py top).
WORKDIR /app/web
CMD ["sh", "-c", "chainlit run app.py --host 0.0.0.0 --port ${PORT:-7860}"]
