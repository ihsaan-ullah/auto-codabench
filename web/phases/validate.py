"""Phase 3 — Validation.

Runs the autocodabench deterministic check framework against the bundle
produced in Phase 2. No agent is involved — this is pure Python:
validate_bundle_path_async reads the zip, runs all registered checks, and
writes validation_report.md + validation_report.json to the run dir.

The results are surfaced in chat (verdict + gate-failure list) and as a new
tab in the workspace panel.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import chainlit as cl

from artifacts import PublicArtifacts, Transcript
from config import PHASE_VALIDATE, PHASE_TITLE

log = logging.getLogger("autocodabench.web.validate")


class Validate:
    """Encapsulates everything specific to Phase 3 (Validation)."""

    PHASE_ID = PHASE_VALIDATE

    @staticmethod
    async def send_kickoff_message(run_dir: Path, client) -> None:  # noqa: ARG004
        """Run the check framework against the Phase 2 bundle and surface results.

        No agent is used. Steps:
          1. Locate bundle zip (same helper Phase 2 uses).
          2. Run validate_bundle_path_async — deterministic checks only.
          3. Write validation_report.md + .json to run_dir.
          4. Refresh public artifacts so the workspace panel tab appears.
          5. Send a summary message in chat.
        """
        log.info("[validate] send_kickoff_message start — run_dir=%s", run_dir)

        session_id = cl.user_session.get("session_id") or ""

        # --- locate bundle ---
        bundle_zip = PublicArtifacts.find_bundle_zip(run_dir)
        if bundle_zip is None:
            log.warning("[validate] no bundle zip found in run_dir=%s", run_dir)
            await cl.Message(
                author="autocodabench",
                content=(
                    f"# {PHASE_TITLE[PHASE_VALIDATE]}\n\n"
                    "⚠️ No bundle found. Go back to **Phase 2 — Competition "
                    "Creation** and ensure the agent finishes and zips the bundle."
                ),
            ).send()
            return

        log.info("[validate] bundle located: %s", bundle_zip)

        await cl.Message(
            author="autocodabench",
            content=(
                f"# {PHASE_TITLE[PHASE_VALIDATE]}\n\n"
                f"Running the autocodabench check framework against "
                f"`{bundle_zip.name}` — this is deterministic (no LLM, no "
                f"Docker) and takes a few seconds…"
            ),
        ).send()

        # --- run checks ---
        try:
            from autocodabench.checks import validate_bundle_path_async
            log.info("[validate] calling validate_bundle_path_async")
            report = await asyncio.to_thread(
                _run_sync_validation, bundle_zip
            )
            log.info("[validate] validation complete: ok=%s counts=%s",
                     report.ok, report.counts)
        except Exception as e:
            log.exception("[validate] validation raised: %s: %s", type(e).__name__, e)
            await cl.Message(
                author="autocodabench",
                content=(
                    f"**Validation error:** `{type(e).__name__}: {e}`\n\n"
                    "You can still download the bundle and validate it manually:\n"
                    "```\nautocodabench validate-bundle <path/to/bundle.zip>\n```"
                ),
            ).send()
            return

        # --- write reports ---
        md_text = report.to_markdown()
        try:
            (run_dir / "validation_report.md").write_text(md_text, encoding="utf-8")
            (run_dir / "validation_report.json").write_text(
                json.dumps(report.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
            log.info("[validate] reports written to run_dir")
        except OSError as e:
            log.warning("[validate] failed to write report files: %s", e)

        Transcript.append(run_dir, role="claude", text=md_text)

        # Refresh workspace panel so the tab appears alongside the summary message.
        if session_id:
            PublicArtifacts.write(run_dir, session_id)

        # --- chat summary ---
        verdict = "✅ PASS" if report.ok else "❌ FAIL"
        counts = report.counts
        counts_str = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))

        from autocodabench.checks.base import Status
        fails = report.by_status(Status.FAIL)
        fail_lines = ""
        if fails:
            fail_lines = "\n\n**Gate failures (fix before uploading):**\n" + "\n".join(
                f"- **[{r.check_id}]** {r.message}" for r in fails
            )

        await cl.Message(
            author="autocodabench",
            content=(
                f"## Validation — {verdict}\n\n"
                f"Results: {counts_str}{fail_lines}\n\n"
                f"Open the **✅ validation_report.md** tab in the workspace "
                f"panel for the full report with findings and attestations."
            ),
        ).send()
        log.info("[validate] send_kickoff_message complete")


def _run_sync_validation(bundle_zip: Path):
    """Sync wrapper — runs in a thread so the event loop stays unblocked."""
    from autocodabench.checks import validate_bundle_path
    return validate_bundle_path(bundle_zip)
