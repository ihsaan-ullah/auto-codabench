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
            "then follow the autocodabench-implement skill end-to-end. "
            "Don't wait for additional instructions.\n\n"
            "### IMPORTANT — Docker unavailability override\n\n"
            "This web UI runs on CPU-only infrastructure (HF Spaces) where "
            "Docker is often not available. If `autocodabench_prepare_run_env` "
            "returns `ok: false` with a Docker-unavailable error, OR if "
            "`autocodabench_run_baseline_submission` returns `ok: false` with "
            "an error containing 'Docker' or 'docker daemon', do NOT treat "
            "this as a fatal failure — **skip section 5 (self-validation) "
            "entirely** and proceed directly to step 6: call "
            "`autocodabench_zip_bundle(slug)` right away. The lint check in "
            "step 3 is sufficient here; the deterministic Phase 3 check "
            "framework gates the bundle without requiring Docker. "
            "Emitting `autocodabench_log_event(kind='stage_done', "
            "payload={..., 'validate_runtime': false, "
            "'docker_skipped': true})` is correct in this case."
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
            "then follow your autocodabench-implement skill end-to-end. "
            "IMPORTANT: if Docker is unavailable (autocodabench_prepare_run_env "
            "or autocodabench_run_baseline_submission returns a Docker error), "
            "skip self-validation and call autocodabench_zip_bundle immediately "
            "after the lint check passes — do not stop without zipping. "
            "Don't wait for further instructions.",
            run_dir,
            response_msg,
        )
        log.info("[bundle] run_agent_turn returned — checking for bundle zip")

        from artifacts import PublicArtifacts
        bundle_zip = PublicArtifacts.find_bundle_zip(run_dir)
        if bundle_zip is None:
            bundles_dir = run_dir / "bundles"
            has_bundle_dir = False
            if bundles_dir.is_dir():
                has_bundle_dir = any(
                    (d / "competition.yaml").is_file()
                    for d in bundles_dir.iterdir()
                    if d.is_dir()
                )
            if has_bundle_dir:
                log.warning(
                    "[bundle] agent finished without a zip but bundle dir exists"
                )
                await cl.Message(
                    author="autocodabench",
                    content=(
                        "⚠️ **Phase 2 finished without producing a zip.**\n\n"
                        "The agent built the bundle files but didn't call "
                        "`autocodabench_zip_bundle` — this usually happens "
                        "when Docker is unavailable and the agent treated the "
                        "baseline failure as fatal instead of skipping it.\n\n"
                        "Type **`zip the bundle now`** to complete Phase 2, "
                        "or click **▶ Advance to Phase 2** again to restart "
                        "the bundling agent from scratch."
                    ),
                ).send()
            else:
                log.warning("[bundle] agent finished without a zip and no bundle dir")
                await cl.Message(
                    author="autocodabench",
                    content=(
                        "⚠️ **Phase 2 did not produce a bundle.**\n\n"
                        "The agent stopped before writing any bundle files. "
                        "Please click **▶ Advance to Phase 2** again to retry, "
                        "or send a message describing what went wrong and ask "
                        "the agent to continue."
                    ),
                ).send()
        log.info("[bundle] send_kickoff_message complete")
