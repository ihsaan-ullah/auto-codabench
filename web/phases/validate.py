"""Phase 3 — Validation.

The Validation phase runs the autocodabench check framework against the
bundle produced in Phase 2. It produces a validation_report.md summarising
pass/fail/advisory findings.

This phase is a placeholder in web v1 — the pill is shown in the phase bar
but the agent and kickoff logic are not yet wired to the UI. Functionality
will be added in a follow-up.
"""
from __future__ import annotations

from pathlib import Path

import chainlit as cl

from config import PHASE_VALIDATE, PHASE_TITLE
from skills import load_skill_body


class Validate:
    """Encapsulates everything specific to Phase 3 (Validation)."""

    PHASE_ID = PHASE_VALIDATE

    @staticmethod
    def system_prompt() -> str:
        """Build the Phase 3 system prompt.

        Loads the test-competition-bundle skill body and appends a web-UI
        footer. Returns a placeholder if the skill file is missing.
        """
        base = load_skill_body("test-competition-bundle")
        if not base:
            base = "(validate skill body missing — contact the operator.)"

        footer = (
            "\n\n---\n\n"
            "## Web UI runtime note (Phase 3 — Validation)\n\n"
            "You are running in the AutoCodabench web UI, Phase 3. "
            "Run the full check framework against the bundle produced in "
            "Phase 2 and write a `validation_report.md` summarising all "
            "findings. Do not wait for additional instructions."
        )
        return base + footer

    @staticmethod
    async def send_kickoff_message(run_dir: Path, client) -> None:
        """Show the Phase 3 intro card.

        Placeholder — agent kickoff will be added when Phase 3 is fully wired.
        """
        await cl.Message(
            author="autocodabench",
            content=(
                f"# {PHASE_TITLE[PHASE_VALIDATE]}\n\n"
                "⚠️ **Phase 3 is coming soon.** The validation agent will "
                "run the full autocodabench check framework against your "
                "bundle and produce a `validation_report.md`.\n\n"
                "For now you can download and validate the bundle manually "
                "using the workspace panel on the right."
            ),
        ).send()
