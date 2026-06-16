"""Filesystem sandbox for agent phases — a code-enforced read boundary.

A phase must only touch what the user handed it: the run/session workspace and
any ``--data`` directory. Left to the prompt and the tool allowlist alone this
is *not* enforced — the Claude backend runs under ``bypassPermissions`` (so the
allowlist is an auto-approve list, not a deny-list), which means generic
``Bash``/``Read``/``Glob`` can roam the whole filesystem. In the create
pipeline that let the planner wander into a ground-truth bundle.

:class:`FsSandbox` is the single policy both backends consult:

- **MCP tools** (``mcp__*``) are always allowed — they are scoped to the run
  directory by construction.
- **Escape tools** (``Bash``/shells, ``Task``, ``WebFetch``/``WebSearch``) are
  denied: a phase has no need for them and they can read outside any root.
- **Filesystem tools** (``Read``/``Write``/``Edit``/``Glob``/``Grep``/…) are
  allowed only when their path argument resolves inside a declared root.

The Claude backend wires this into a ``PreToolUse`` hook (guardrails run
regardless of permission mode); the OpenAI-compatible backend consults it
before executing a tool in-process.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# Tools a sandboxed phase never needs and that can reach arbitrary files (or the
# network) — denied outright rather than path-checked.
_DENY_TOOLS = {
    "Bash", "BashOutput", "KillShell",
    "Task",
    "WebFetch", "WebSearch",
}
# The subset of deny tools that are network research tools, lifted from the deny
# set when a phase is explicitly granted a research capability (see
# ``FsSandbox(..., allow_web=True)``). Shells/Task are never lifted.
_WEB_TOOLS = {"WebFetch", "WebSearch"}

# Filesystem tools, mapped to the argument that carries the path they touch.
_PATH_TOOLS = {
    "Read": "file_path",
    "Write": "file_path",
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "NotebookEdit": "notebook_path",
    "NotebookRead": "notebook_path",
    "Glob": "path",
    "Grep": "path",
    "LS": "path",
    # local_tools (OpenAI-compatible backend) canonical names
    "read_file": "path",
    "write_file": "path",
    "list_dir": "path",
}
# Search tools whose path argument is optional (defaulting to cwd) — we require
# an explicit, in-sandbox path rather than letting them walk the whole tree.
_SEARCH_TOOLS = {"Glob", "Grep", "LS"}


def _resolve(p: Any) -> Path | None:
    try:
        return Path(str(p)).expanduser().resolve()
    except Exception:
        return None


class FsSandbox:
    """Confine an agent's filesystem reach to a set of roots."""

    def __init__(self, roots: list[str | Path] | None, *, allow_web: bool = False):
        self.roots: list[Path] = []
        for r in roots or []:
            rp = _resolve(r)
            if rp is not None:
                self.roots.append(rp)
        # Deny set for this phase: web tools are lifted only when explicitly
        # granted a research capability; shells/Task stay denied either way.
        self.deny = _DENY_TOOLS - _WEB_TOOLS if allow_web else set(_DENY_TOOLS)

    def _within(self, target: Path) -> bool:
        for root in self.roots:
            if target == root or root in target.parents:
                return True
        return False

    def check(self, tool_name: str, tool_input: dict | None) -> str | None:
        """Return a human-readable denial reason, or ``None`` to allow."""
        name = tool_name or ""
        if name.startswith("mcp__"):
            return None  # MCP surface is scoped to the run dir by construction
        base = name.split("__")[-1]
        if base in self.deny:
            return (
                f"{base} is disabled in this phase — it can reach files outside "
                "the inputs you were given. Use Read/Glob/Grep within the "
                "provided directories instead."
            )
        arg = _PATH_TOOLS.get(base)
        if arg is None:
            return None  # not a filesystem tool — nothing to confine
        raw = (tool_input or {}).get(arg)
        if not raw:
            if base in _SEARCH_TOOLS:
                allowed = ", ".join(str(r) for r in self.roots) or "(none)"
                return (
                    f"{base} needs an explicit path inside the inputs you were "
                    f"given. Allowed directories: {allowed}."
                )
            return None
        target = _resolve(raw)
        if target is None or not self._within(target):
            allowed = ", ".join(str(r) for r in self.roots) or "(none)"
            return (
                f"Accessing {raw} is outside this phase's inputs. You may only "
                f"read within: {allowed}."
            )
        return None
