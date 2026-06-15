"""Phase 3 — Validation.

The Validation phase runs the autocodabench bundle linter against the bundle
produced in Phase 2 and writes a `validation_report.md` summarising the
findings. It drives the `autocodabench_validate_bundle` MCP tool — the same
schema lint the CLI `validate` surface exposes — then turns the issue list
into a human-readable report.

The report file (`<run>/validation_report.md`) is the phase artifact that the
phase bar checks for.
"""
from __future__ import annotations

import logging
from pathlib import Path

import chainlit as cl

from config import PHASE_VALIDATE, PHASE_TITLE
from streaming import run_agent_turn

log = logging.getLogger("autocodabench.web.validate")


class Validate:
    """Encapsulates everything specific to Phase 3 (Validation)."""

    PHASE_ID = PHASE_VALIDATE

    @staticmethod
    def system_prompt() -> str:
        """Build the Phase 3 system prompt.

        There is no agent "validate" skill in the package — validation is the
        deterministic bundle linter, exposed to the agent as the
        `autocodabench_validate_bundle` MCP tool. So the prompt is inlined here
        rather than loaded from a SKILL.md.
        """
        return (
            "# AutoCodabench — Phase 3: Validation\n\n"
            "You are a careful release engineer running the pre-launch lint on "
            "a Codabench competition bundle. You have NO memory of how the "
            "bundle was built — judge it only by what the linter and the files "
            "on disk say.\n\n"
            "## Your job\n\n"
            "1. Call `autocodabench_current_run` to find the active run "
            "directory.\n"
            "2. Find the bundle to validate: it lives under "
            "`<run>/bundles/<slug>/`. Use `Glob` on `<run>/bundles/*` to get "
            "the bundle's `<slug>` (the directory name).\n"
            "3. Call `autocodabench_validate_bundle(slug=\"<slug>\")`. This is "
            "the same schema lint the `autocodabench validate` CLI runs: it "
            "checks `competition.yaml`, referenced pages/data/image paths, the "
            "scoring program's `metadata.yaml`/`command`, leaderboard column "
            "keys, and phase/task wiring. It returns `ok`, an `issues` list "
            "(each with `severity`, `where`, `message`), and "
            "`leaderboard_keys_expected`.\n"
            "4. If the result helps, `Read` the relevant bundle files to give "
            "the issues context.\n"
            "5. Write `<run>/validation_report.md` (use the absolute run-dir "
            "path from step 1) summarising the outcome.\n\n"
            "## Report format\n\n"
            "Start the report with a one-line verdict — **PASS** if `ok` is "
            "true (no error-severity issues), otherwise **FAIL**. Then a table "
            "of every issue (severity · where · message), followed by concrete "
            "fixes for each. If there are no issues, say so plainly and list "
            "what was checked. Be honest about scope: this is the schema "
            "linter, not the full three-tier check framework (deterministic + "
            "judged + attestation) that the `autocodabench validate` CLI runs "
            "end to end.\n\n"
            "## Web UI runtime note\n\n"
            "You are running in the AutoCodabench web UI, Phase 3. Execute the "
            "steps above serially in this chat without waiting for further "
            "instructions. When `validation_report.md` is written, give the "
            "user a short summary of the verdict in chat."
        )

    @staticmethod
    async def send_kickoff_message(run_dir: Path, client) -> None:
        """Show the Phase 3 intro card and immediately kick off the agent.

        Mirrors Phase 2: the agent is handed a synthetic prompt so it starts
        validating without waiting for the user to type anything.
        """
        log.info("[validate] send_kickoff_message start — run_dir=%s", run_dir)
        await cl.Message(
            author="autocodabench",
            content=(
                f"# {PHASE_TITLE[PHASE_VALIDATE]}\n\n"
                "Running the AutoCodabench bundle linter against the bundle "
                "built in Phase 2 — the same schema checks as the "
                "`autocodabench validate` CLI. I'll write a "
                "`validation_report.md` with the verdict and any issues to "
                "fix, and summarise it here."
            ),
        ).send()
        log.info("[validate] Phase 3 intro card sent")

        response_msg = cl.Message(content="", author="autocodabench")
        await response_msg.send()
        log.info("[validate] empty response_msg sent — calling run_agent_turn")
        await run_agent_turn(
            client,
            "Begin Phase 3 validation. Call `autocodabench_current_run`, find "
            "the bundle slug under `<run>/bundles/*`, run "
            "`autocodabench_validate_bundle` on it, then write "
            "`<run>/validation_report.md` and summarise the verdict. Don't "
            "wait for further instructions.",
            run_dir,
            response_msg,
        )
        log.info("[validate] run_agent_turn returned — Phase 3 kickoff complete")
