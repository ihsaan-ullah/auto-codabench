"""Phase 2 — Competition Creation (Bundle).

The Bundle phase runs a fresh agent session with no memory of Phase 1.
It reads the locked specs/implementation_plan.md and produces a complete
Codabench bundle: competition.yaml, scoring_program/, solution/, pages/,
then validates and zips. The resulting bundle.zip is the phase artifact.
"""
from __future__ import annotations

import logging
from pathlib import Path

import chainlit as cl

from config import PHASE_BUNDLE, PHASE_TITLE
from skills import load_skill_body
from streaming import run_agent_turn

log = logging.getLogger("autocodabench.web.bundle")


class Bundle:
    """Encapsulates everything specific to Phase 2 (Competition Creation)."""

    PHASE_ID = PHASE_BUNDLE

    @staticmethod
    def system_prompt() -> str:
        """Build the Phase 2 system prompt.

        Loads the autocodabench-implement skill body and appends a web-UI
        footer telling the agent to start immediately without waiting for
        further user input.
        """
        base = load_skill_body("autocodabench-implement")
        if not base:
            base = "(implement skill body missing — contact the operator.)"

        footer = (
            "\n\n---\n\n"
            "## Web UI runtime note (Phase 2 — Competition Creation)\n\n"
            "You are running in the terminal phase. The user reached this "
            "phase by clicking **▶ Advance to Phase 2** in the phase bar; "
            "the plan at `<run>/specs/implementation_plan.md` is locked. "
            "Execute the autocodabench-implement skill serially in this "
            "chat — `/agents` is not available here.\n\n"
            "Start now: call `autocodabench_current_run`, read the plan, "
            "then follow the autocodabench-implement skill end-to-end "
            "(generate bundle files → validate → zip). Don't wait for "
            "additional instructions."
        )
        return base + footer

    @staticmethod
    async def send_kickoff_message(run_dir: Path, client) -> None:
        """Show the Phase 2 intro card and immediately kick off the agent.

        The agent is given a synthetic prompt to start building the bundle
        without waiting for the user to type anything.
        """
        log.info("[bundle] send_kickoff_message start — run_dir=%s", run_dir)
        log.info("[bundle] sending Phase 2 intro card")
        await cl.Message(
            author="autocodabench",
            content=(
                f"# {PHASE_TITLE[PHASE_BUNDLE]}\n\n"
                "Fresh agent with no memory of Phase 1. It will read the "
                "locked `specs/implementation_plan.md` and write the "
                "Codabench bundle directly: `competition.yaml`, "
                "`scoring_program/`, `solution/`, `pages/`, then validate "
                "and zip. After that you'll get a download link in chat "
                "and a one-click Upload-to-Codabench button."
            ),
        ).send()
        log.info("[bundle] Phase 2 intro card sent")

        response_msg = cl.Message(content="", author="autocodabench")
        log.info("[bundle] sending empty response_msg placeholder")
        await response_msg.send()
        log.info("[bundle] empty response_msg sent — calling run_agent_turn")
        await run_agent_turn(
            client,
            "Begin Phase 2. Read `specs/implementation_plan.md` first, "
            "then follow your autocodabench-implement skill end-to-end "
            "(generate bundle → validate → zip). Don't wait for further "
            "instructions.",
            run_dir,
            response_msg,
        )
        log.info("[bundle] run_agent_turn returned — Phase 2 kickoff complete")
