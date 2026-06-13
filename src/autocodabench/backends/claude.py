"""Live backend on the Claude Agent SDK.

Credential resolution is owned by the SDK's bundled Claude Code runtime,
with its own precedence (an exported ``ANTHROPIC_API_KEY`` takes priority
over a stored subscription login). Rather than fight that, the backend
calls :func:`autocodabench.auth.apply_auth_preference` before the SDK
reads the environment: when the user's stored preference is
``subscription``, any ``ANTHROPIC_API_KEY`` is removed for the process so
the subscription login is the one used — no manual unsetting.
:mod:`autocodabench.auth` also provides the status report and the
pre-session ``INFO`` banner.

The backend records every SDK message to a JSONL trace when
``task.trace_path`` is set — those traces, together with the MCP layer's
``tool_calls/`` snapshots, are the raw material for replay fixtures.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path
from typing import Any

from .base import AgentRunResult, AgentTask

log = logging.getLogger("autocodabench.backends.claude")

DEFAULT_MODEL = "claude-sonnet-4-6"


def _to_jsonable(obj: Any) -> Any:
    """Best-effort conversion of SDK message objects to plain JSON."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)


def _result_preview(content: Any, limit: int = 160) -> str:
    """One-line, length-capped preview of a tool result for progress display.
    Tool-result content is a string or a list of content blocks."""
    if content is None:
        return ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(getattr(item, "text", item)))
        text = " ".join(p for p in parts if p)
    else:
        text = str(content)
    text = " ".join(text.split())  # collapse whitespace/newlines
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ClaudeAgentBackend:
    """Execute a phase as one Claude Agent SDK session."""

    name = "claude"

    def __init__(
        self,
        *,
        model: str | None = None,
        permission_mode: str = "bypassPermissions",
    ) -> None:
        self.model = model or DEFAULT_MODEL
        self.permission_mode = permission_mode

    async def run(self, task: AgentTask) -> AgentRunResult:
        # Realize the user's auth preference (e.g. hide ANTHROPIC_API_KEY when
        # they chose the subscription) before the SDK reads the environment.
        # The CLI also does this at preflight; doing it here covers library
        # and web callers. Idempotent and quiet (the banner is the CLI's job).
        from ..auth import apply_auth_preference
        apply_auth_preference()

        # Lazy import: keyless environments (validator-only, CI replay)
        # never touch the SDK or its bundled CLI runtime.
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            query,
        )
        # Block/message types for progress events vary slightly across SDK
        # versions; import defensively so a missing name degrades to "no tool
        # events" rather than breaking the run.
        try:
            from claude_agent_sdk import ToolUseBlock
        except ImportError:  # pragma: no cover
            ToolUseBlock = ()  # type: ignore[assignment]
        try:
            from claude_agent_sdk import ToolResultBlock, UserMessage
        except ImportError:  # pragma: no cover
            ToolResultBlock = ()  # type: ignore[assignment]
            UserMessage = ()      # type: ignore[assignment]

        def emit(event: dict) -> None:
            if task.on_event is not None:
                try:
                    task.on_event(event)
                except Exception:  # a rendering bug must never kill the run
                    log.debug("on_event callback raised", exc_info=True)

        options = ClaudeAgentOptions(
            model=task.model or self.model,
            system_prompt=task.system_prompt,
            mcp_servers=task.mcp_servers or {},
            allowed_tools=task.allowed_tools or [],
            permission_mode=self.permission_mode,
            cwd=task.cwd,
            env=task.env or {},
            max_budget_usd=task.max_budget_usd,
        )

        trace_file = None
        if task.trace_path is not None:
            Path(task.trace_path).parent.mkdir(parents=True, exist_ok=True)
            trace_file = Path(task.trace_path).open("w", encoding="utf-8")

        texts: list[str] = []
        result_msg: Any = None
        try:
            async for message in query(prompt=task.prompt, options=options):
                if trace_file is not None:
                    record = {"type": type(message).__name__, "data": _to_jsonable(message)}
                    trace_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                    trace_file.flush()
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text:
                            texts.append(block.text)
                            if task.on_text is not None:
                                task.on_text(block.text)
                            emit({"kind": "text", "text": block.text})
                        elif ToolUseBlock and isinstance(block, ToolUseBlock):
                            emit({"kind": "tool_use",
                                  "name": getattr(block, "name", "?"),
                                  "input": getattr(block, "input", {}) or {}})
                elif UserMessage and isinstance(message, UserMessage):
                    for block in (getattr(message, "content", None) or []):
                        if ToolResultBlock and isinstance(block, ToolResultBlock):
                            emit({"kind": "tool_result",
                                  "is_error": bool(getattr(block, "is_error", False)),
                                  "preview": _result_preview(getattr(block, "content", None))})
                elif isinstance(message, ResultMessage):
                    result_msg = message
                    emit({"kind": "result",
                          "num_turns": getattr(message, "num_turns", None),
                          "cost_usd": getattr(message, "total_cost_usd", None)})
        except Exception as e:
            log.exception("Claude backend run failed")
            return AgentRunResult(
                status="error",
                final_text="\n\n".join(texts),
                error=f"{type(e).__name__}: {e}",
                trace_path=str(task.trace_path) if task.trace_path else None,
            )
        finally:
            if trace_file is not None:
                trace_file.close()

        if result_msg is None:
            return AgentRunResult(
                status="error",
                final_text="\n\n".join(texts),
                error="session ended without a ResultMessage",
                trace_path=str(task.trace_path) if task.trace_path else None,
            )

        status = result_msg.subtype or ("error" if result_msg.is_error else "success")
        return AgentRunResult(
            status=status,
            # `result` carries the final text on success; fall back to the
            # accumulated assistant text for error subtypes.
            final_text=result_msg.result or "\n\n".join(texts),
            session_id=result_msg.session_id,
            num_turns=result_msg.num_turns,
            total_cost_usd=result_msg.total_cost_usd,
            usage=_to_jsonable(result_msg.usage) if result_msg.usage else None,
            trace_path=str(task.trace_path) if task.trace_path else None,
            error="; ".join(result_msg.errors) if getattr(result_msg, "errors", None) else None,
        )
