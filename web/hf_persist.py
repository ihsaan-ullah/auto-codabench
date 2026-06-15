"""Hugging Face Dataset persistence for AutoCodabench web sessions.

After each assistant turn the per-session run_dir is uploaded to a private
HF Dataset repo. This is the analytics / audit trail mechanism for the
hosted Space — it means session data survives even if the Space restarts.

Setup (once, on the Space owner's account):
  1. https://huggingface.co/new-dataset  → name `autocodabench-runs`, set Private.
  2. https://huggingface.co/settings/tokens → new token with `write` scope.
  3. On the Space: Settings → Variables and secrets → add Secret HF_TOKEN.
  (Optional: add Variable AUTOCODABENCH_RUNS_REPO to override the default repo.)

When HF_TOKEN is not set (local dev) uploads are silently skipped.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from config import HF_RUNS_REPO, HF_TOKEN

log = logging.getLogger("autocodabench.web.hf_persist")


async def persist_to_hf(run_dir: Path) -> None:
    """Best-effort upload of run_dir to the private HF Dataset repo.

    Runs the blocking HF I/O off the event loop via asyncio.to_thread.
    Errors (network blip, rotated token, deleted repo) are logged and
    swallowed — we never want analytics to break a live chat.
    """
    if not HF_TOKEN:
        return
    if not run_dir.exists():
        return

    # Repair transcripts written by the older format whose leading `---`
    # was parsed as YAML frontmatter by most renderers, hiding the first
    # user prompt.
    try:
        tpath = run_dir / "transcript.md"
        if tpath.is_file():
            body = tpath.read_text(encoding="utf-8")
            if body.startswith("\n---\n") or body.startswith("---\n"):
                fix = (
                    f"# Transcript — {run_dir.name}\n\n"
                    f"_(repaired: leading `---` was being parsed as YAML "
                    f"frontmatter and hiding the first user prompt)_\n"
                )
                tpath.write_text(fix + body, encoding="utf-8")
    except Exception as e:
        log.warning("transcript repair for %s failed: %s", run_dir.name, e)

    try:
        from huggingface_hub import HfApi

        def _do_upload() -> None:
            api = HfApi(token=HF_TOKEN)
            api.create_repo(
                repo_id=HF_RUNS_REPO,
                repo_type="dataset",
                private=True,
                exist_ok=True,
            )
            api.upload_folder(
                folder_path=str(run_dir),
                repo_id=HF_RUNS_REPO,
                repo_type="dataset",
                path_in_repo=run_dir.name,
                commit_message=f"sync {run_dir.name}",
                allow_patterns=[
                    "*.md", "*.jsonl", "*.json", "*.txt",
                    "*.py", "*.yaml", "*.yml", "*.log", "*.ipynb",
                ],
            )

        await asyncio.to_thread(_do_upload)
    except Exception as e:
        log.warning("HF persist for %s failed: %s", run_dir.name, e)
