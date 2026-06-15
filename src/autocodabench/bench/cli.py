"""Shared CLI helpers for the benchmark harnesses."""
from __future__ import annotations

_MODELS_HELP = "model IDs: https://docs.claude.com/en/docs/about-claude/models"


def require_explicit_model(spec: str | None, model: str | None) -> None:
    """Force the Claude backend to name an exact model in a benchmark run.

    A leaderboard row is only meaningful if it records *which* model produced
    it. Non-Claude specs already carry the model (``ollama:<m>``, ``openai:<m>``,
    ``host#<m>``), but bare ``claude`` — and the implicit default when
    ``--backend`` is omitted — would hide it behind whatever the SDK picks. So
    for benchmarks the Claude model must be given, inline (``claude:<model>``)
    or via ``--model``. Raises ``SystemExit`` with guidance otherwise.
    """
    head = (spec or "claude").split(":", 1)
    is_claude = head[0] == "claude"
    inline_model = head[1] if len(head) == 2 else ""
    if is_claude and not inline_model and not model:
        raise SystemExit(
            "Benchmarks need the exact Claude model, so leaderboard rows are "
            "unambiguous. Specify it:\n"
            "  --backend claude:claude-opus-4-8\n"
            "  (or)  --backend claude --model claude-opus-4-8\n"
            f"  {_MODELS_HELP}")
