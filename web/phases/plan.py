"""Phase 1 — Plan.

The Plan phase runs a single agent session that produces
specs/implementation_plan.md covering all 7 design sections of a
Codabench competition (task, data, metric, baseline, rules, ethics,
schedule). No bundle files are written here; the plan is the only output
and acts as the locked interface to Phase 2.
"""
from __future__ import annotations

from pathlib import Path

import chainlit as cl

from config import PHASE_BUNDLE, PHASE_PLAN, PHASE_TITLE
from skills import load_skill_body


class Plan:
    """Encapsulates everything specific to Phase 1 (Plan)."""

    PHASE_ID = PHASE_PLAN

    @staticmethod
    def system_prompt() -> str:
        """Build the Phase 1 system prompt.

        Loads the autocodabench-plan skill body and appends a short web-UI
        footer reminding the agent that phase transitions are button-driven
        (not agent-triggered) and that Phase 2 starts with no memory of this
        conversation.
        """
        base = load_skill_body("autocodabench-plan", "plan")
        if not base:
            base = "(plan skill body missing — contact the operator.)"

        footer = (
            "\n\n---\n\n"
            "## Web UI runtime note (Phase 1 — Plan)\n\n"
            "You are running in the AutoCodabench web UI, Phase 1. The user "
            "advances between phases by clicking the pill in the **phase bar "
            "at the top of the page** — you cannot trigger the advance "
            "yourself.\n\n"
            "When `implementation_plan.md` is saved and you'd recommend "
            "moving on, say something like:\n\n"
            "> ✅ Plan saved. When you're ready, click **▶ Advance to "
            "> Phase 2 — Competition Creation** in the phase bar at the top.\n\n"
            "Phase 2 starts with NO memory of this conversation — only the "
            "plan file. If anything important from our chat is missing from "
            "the plan, tell the user so we can revise before advancing."
        )
        return base + footer

    @staticmethod
    async def send_revisit_message() -> None:
        """Shown when the user navigates back to Phase 1 from Phase 2.

        The bundle has been discarded. We tell the user the plan is still
        intact and wait for them to say what to change — no auto-prompt so
        we don't waste a turn.
        """
        await cl.Message(
            author="autocodabench",
            content=(
                f"# {PHASE_TITLE[PHASE_PLAN]} *(re-opened)*\n\n"
                "The bundle has been discarded. The plan itself is "
                "preserved — tell me what to change and I'll re-snapshot "
                "it. When you're done, click **▶ Advance to Phase 2** "
                "again to regenerate the bundle from the updated plan."
            ),
        ).send()
