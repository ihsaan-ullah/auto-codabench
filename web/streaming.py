"""Shared agent response streaming for the AutoCodabench web UI.

Both the regular on_message handler and the synthetic phase-kickoff prompt
need the same streaming loop. This module provides a single implementation
used by both call sites, eliminating the duplication that existed in the
original app.py.
"""
from __future__ import annotations

import logging
from pathlib import Path

import chainlit as cl
from claude_agent_sdk import (
    AssistantMessage,
    RateLimitEvent,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from artifacts import CostLog, Transcript
from config import CONTEXT_WINDOW_TOKENS, DEFAULT_MODEL, MAX_USD_PER_SESSION

log = logging.getLogger("autocodabench.web.streaming")

# Tools we don't surface as chips in the UI — they're agent machinery that
# only adds clutter for the end user.
_HIDDEN_TOOLS = {"Skill", "ToolSearch", "Read", "Grep", "Glob"}

# Human-readable verb phrase per MCP tool, used in the running-step chip label.
_OP_LABELS: dict[str, str] = {
    "mcp__alex-mcp__search_works":               "OpenAlex search",
    "mcp__alex-mcp__search_authors":             "OpenAlex author search",
    "mcp__alex-mcp__autocomplete_authors":       "OpenAlex author autocomplete",
    "mcp__alex-mcp__retrieve_author_works":      "OpenAlex retrieve works",
    "mcp__alex-mcp__search_pubmed":              "PubMed search",
    "mcp__alex-mcp__pubmed_author_sample":       "PubMed author sample",
    "mcp__alex-mcp__search_orcid_authors":       "ORCID author search",
    "mcp__alex-mcp__get_orcid_publications":     "ORCID retrieve works",
    "mcp__autocodabench__autocodabench_open_run":               "opening session",
    "mcp__autocodabench__autocodabench_current_run":            "verifying session",
    "mcp__autocodabench__autocodabench_log_event":              "logging event",
    "mcp__autocodabench__autocodabench_snapshot_spec":          "saving spec",
    "mcp__autocodabench__autocodabench_init_bundle":            "creating bundle",
    "mcp__autocodabench__autocodabench_write_competition_yaml": "writing competition.yaml",
    "mcp__autocodabench__autocodabench_write_page":             "writing page",
    "mcp__autocodabench__autocodabench_write_scoring_program":  "writing scoring program",
    "mcp__autocodabench__autocodabench_write_ingestion_program":"writing ingestion program",
    "mcp__autocodabench__autocodabench_write_solution":         "writing solution",
    "mcp__autocodabench__autocodabench_attach_data":            "attaching data",
    "mcp__autocodabench__autocodabench_validate_bundle":        "validating bundle",
    "mcp__autocodabench__autocodabench_zip_bundle":             "zipping bundle",
    "mcp__autocodabench__autocodabench_upload_bundle":          "uploading to Codabench",
}


def operation_label(tool_name: str, tool_input: dict | None) -> str:
    """Return a friendly verb phrase for the step chip.

    For search tools we also append a truncated query string so the user can
    see what's being looked up at a glance.
    """
    base = _OP_LABELS.get(tool_name)
    if base is None:
        last = tool_name.split("__")[-1]
        base = last.removeprefix("autocodabench_").replace("_", " ")
    if isinstance(tool_input, dict) and "search" in tool_name.lower():
        q = tool_input.get("query") or tool_input.get("q") or ""
        q = str(q).strip()
        if q:
            return f"{base}: '{q[:40]}'"
    return base


async def run_agent_turn(
    client,
    prompt: str,
    run_dir: Path,
    response_msg: cl.Message,
) -> None:
    """Stream one agent turn to the UI and append the result to the transcript.

    Handles the full receive_response() loop: text streaming, tool-use chips,
    tool-result chips, cost/context footer, and transcript writing.

    Used by both on_message (user-initiated turns) and _stream_one_turn
    (synthetic phase-kickoff prompts injected by the server).
    """
    open_steps: dict[str, tuple[cl.Step, str]] = {}
    turn_parts: list[dict] = []
    tool_idx_by_id: dict[str, int] = {}
    msg_count = 0

    log.info("[turn] START — prompt %.80r", prompt)
    try:
        log.info("[turn] calling client.query()")
        await client.query(prompt)
        log.info("[turn] client.query() returned — entering receive_response() loop")

        async for message in client.receive_response():
            msg_count += 1
            log.info("[turn] message #%d: %s", msg_count, type(message).__name__)

            if isinstance(message, AssistantMessage):
                block_types = [type(b).__name__ for b in message.content]
                log.info("[turn] AssistantMessage blocks: %s", block_types)
                for block in message.content:
                    if isinstance(block, TextBlock):
                        log.debug("[turn] TextBlock len=%d", len(block.text))
                        await response_msg.stream_token(block.text)
                        turn_parts.append({"kind": "text", "text": block.text})

                    elif isinstance(block, ToolUseBlock):
                        log.info("[turn] ToolUseBlock name=%r id=%s", block.name, block.id)
                        if block.name in _HIDDEN_TOOLS:
                            log.debug("[turn] hidden tool %r — skipping chip", block.name)
                            continue
                        op   = operation_label(block.name, block.input)
                        step = cl.Step(
                            name=f"Running {op}",
                            type="tool",
                            show_input="json",
                            parent_id=response_msg.id,
                        )
                        step.input = block.input
                        log.info("[turn] sending step chip for tool=%r op=%r", block.name, op)
                        await step.send()
                        log.info("[turn] step chip sent for tool=%r", block.name)
                        open_steps[block.id] = (step, op)
                        turn_parts.append({
                            "kind":     "tool",
                            "id":       block.id,
                            "raw_name": block.name,
                            "op":       op,
                            "input":    block.input,
                            "output":   "",
                            "is_error": False,
                        })
                        tool_idx_by_id[block.id] = len(turn_parts) - 1

                    elif isinstance(block, ThinkingBlock):
                        log.debug("[turn] ThinkingBlock (not surfaced)")

            elif isinstance(message, UserMessage):
                blocks = message.content if isinstance(message.content, list) else []
                result_blocks = [b for b in blocks if isinstance(b, ToolResultBlock)]
                log.info("[turn] UserMessage with %d ToolResultBlock(s)", len(result_blocks))
                for block in blocks:
                    if not isinstance(block, ToolResultBlock):
                        continue
                    is_error = bool(getattr(block, "is_error", False))
                    log.info(
                        "[turn] ToolResultBlock tool_use_id=%s is_error=%s content_len=%d",
                        block.tool_use_id,
                        is_error,
                        len(str(block.content or "")),
                    )
                    record = open_steps.pop(block.tool_use_id, None)
                    if record is None:
                        log.warning("[turn] ToolResultBlock for unknown id=%s — skipping", block.tool_use_id)
                        continue
                    step, op = record
                    step.name = op

                    if isinstance(block.content, list):
                        parts = []
                        for c in block.content:
                            if hasattr(c, "text"):
                                parts.append(c.text)
                            elif isinstance(c, dict) and "text" in c:
                                parts.append(c["text"])
                            else:
                                parts.append(str(c))
                        out_text = "\n".join(parts)
                    else:
                        out_text = str(block.content or "")

                    if is_error:
                        step.is_error = True
                    step.output = out_text
                    log.info("[turn] updating step chip op=%r is_error=%s out_len=%d", op, is_error, len(out_text))
                    await step.update()
                    log.info("[turn] step chip updated op=%r", op)

                    idx = tool_idx_by_id.get(block.tool_use_id)
                    if idx is not None:
                        turn_parts[idx]["output"]   = out_text
                        turn_parts[idx]["is_error"] = is_error

            elif isinstance(message, ResultMessage):
                cost = getattr(message, "total_cost_usd", None) or 0.0
                cum  = cl.user_session.get("cum_cost_usd", 0.0) + cost
                cl.user_session.set("cum_cost_usd", cum)

                usage = getattr(message, "usage", None) or {}
                if isinstance(usage, dict):
                    in_tok  = int(usage.get("input_tokens")  or 0)
                    out_tok = int(usage.get("output_tokens") or 0)
                else:
                    in_tok  = int(getattr(usage, "input_tokens",  0) or 0)
                    out_tok = int(getattr(usage, "output_tokens", 0) or 0)
                log.info("[turn] ResultMessage cost=$%.4f cum=$%.4f in_tok=%d out_tok=%d", cost, cum, in_tok, out_tok)
                if in_tok:
                    cl.user_session.set("last_input_tokens", in_tok)
                if out_tok:
                    cl.user_session.set("last_output_tokens", out_tok)

                if cost or in_tok:
                    ctx_pct = 100.0 * in_tok / CONTEXT_WINDOW_TOKENS if in_tok else 0.0
                    await response_msg.stream_token(
                        f"\n\n_turn ≈ ${cost:.3f} · session "
                        f"${cum:.2f} / ${MAX_USD_PER_SESSION:.2f} · "
                        f"ctx {ctx_pct:.1f}% ({in_tok:,} tok)_"
                    )

                user = cl.user_session.get("user")
                CostLog.append(
                    run_dir,
                    turn_cost=cost,
                    cumulative=cum,
                    model=DEFAULT_MODEL,
                    session_id=cl.user_session.get("session_id") or "",
                    user_id=user.identifier if user else "anon",
                )

            elif isinstance(message, SystemMessage):
                subtype = getattr(message, "subtype", "")
                log.info("[turn] SystemMessage subtype=%r", subtype)
                if subtype in ("budget_exceeded", "rate_limit", "stop"):
                    await cl.Message(
                        content=f"_[system: {subtype}]_",
                        author="autocodabench",
                    ).send()

            elif isinstance(message, RateLimitEvent):
                info = message.rate_limit_info
                status = getattr(info, "status", "unknown")
                utilization = getattr(info, "utilization", None)
                resets_at = getattr(info, "resets_at", None)
                log.info(
                    "[turn] RateLimitEvent status=%r utilization=%s resets_at=%s",
                    status, utilization, resets_at,
                )
                if status == "rejected":
                    import datetime
                    if resets_at:
                        reset_dt = datetime.datetime.fromtimestamp(resets_at, tz=datetime.timezone.utc)
                        wait_secs = max(0, int((reset_dt - datetime.datetime.now(tz=datetime.timezone.utc)).total_seconds()))
                        reset_str = f" Resets in ~{wait_secs}s (at {reset_dt.strftime('%H:%M:%S')} UTC)."
                    else:
                        reset_str = ""
                    log.warning("[turn] rate limit REJECTED — agent is paused.%s", reset_str)
                    await cl.Message(
                        content=f"_⏳ Rate limit reached — waiting for the window to reset.{reset_str}_",
                        author="autocodabench",
                    ).send()
                elif status == "allowed_warning":
                    pct = f"{utilization * 100:.0f}%" if utilization is not None else "high"
                    log.warning("[turn] rate limit warning — utilization=%s", pct)
                    await cl.Message(
                        content=f"_⚠️ Approaching rate limit ({pct} utilization) — may pause soon._",
                        author="autocodabench",
                    ).send()

        log.info("[turn] receive_response() loop exited normally after %d messages", msg_count)

    except Exception as e:
        log.exception("[turn] EXCEPTION in run_agent_turn: %s: %s", type(e).__name__, e)
        await cl.Message(
            content=f"**Error:** `{type(e).__name__}: {e}`",
            author="autocodabench",
        ).send()

    log.info("[turn] calling response_msg.update()")
    await response_msg.update()
    log.info("[turn] END — %d messages processed, %d turn_parts", msg_count, len(turn_parts))

    # Write completed turn to transcript.
    if turn_parts:
        body_chunks: list[str] = []
        for part in turn_parts:
            if part["kind"] == "text":
                body_chunks.append(part["text"])
            else:
                body_chunks.append(Transcript.format_tool_call(
                    op=part["op"],
                    raw_name=part["raw_name"],
                    input_json=part["input"],
                    output_text=part["output"],
                    is_error=part["is_error"],
                ))
        Transcript.append(run_dir, role="claude", text="".join(body_chunks))
