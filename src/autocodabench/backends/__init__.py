"""Agent backends — the seam between autocodabench and the model runtime.

Two backends ship in v1:

- :class:`~autocodabench.backends.claude.ClaudeAgentBackend` — live execution
  on the Claude Agent SDK (subscription login or ANTHROPIC_API_KEY).
- :class:`~autocodabench.backends.replay.ReplayBackend` — deterministic,
  keyless replay of a recorded run's tool calls. Used by ``autocodabench
  demo --replay`` and by CI.

Everything above this seam (phases, checks, CLI, web UI) talks only to
:class:`~autocodabench.backends.base.AgentBackend`, so additional live
backends are an extension point, not a rewrite.
"""
from .base import AgentBackend, AgentRunResult
from .replay import ReplayBackend

__all__ = ["AgentBackend", "AgentRunResult", "ReplayBackend", "get_claude_backend"]


def get_claude_backend(**kwargs):
    """Late import so keyless environments never load the Agent SDK."""
    from .claude import ClaudeAgentBackend

    return ClaudeAgentBackend(**kwargs)
