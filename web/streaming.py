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

    try:
        await client.query(prompt)
        async for message in client.receive_response():

            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        await response_msg.stream_token(block.text)
                        turn_parts.append({"kind": "text", "text": block.text})

                    elif isinstance(block, ToolUseBlock):
                        if block.name in _HIDDEN_TOOLS:
                            continue
                        op   = operation_label(block.name, block.input)
                        step = cl.Step(
                            name=f"Running {op}",
                            type="tool",
                            show_input="json",
                            parent_id=response_msg.id,
                        )
                        step.input = block.input
                        await step.send()
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
                        pass  # not surfaced in the UI

            elif isinstance(message, UserMessage):
                blocks = message.content if isinstance(message.content, list) else []
                for block in blocks:
                    if not isinstance(block, ToolResultBlock):
                        continue
                    record = open_steps.pop(block.tool_use_id, None)
                    if record is None:
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

                    is_error = bool(getattr(block, "is_error", False))
                    if is_error:
                        step.is_error = True
                    step.output = out_text
                    await step.update()

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
                if subtype in ("budget_exceeded", "rate_limit", "stop"):
                    await cl.Message(
                        content=f"_[system: {subtype}]_",
                        author="autocodabench",
                    ).send()

    except Exception as e:
        await cl.Message(
            content=f"**Error:** `{type(e).__name__}: {e}`",
            author="autocodabench",
        ).send()

    await response_msg.update()

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
