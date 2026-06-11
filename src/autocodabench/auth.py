"""Auth status for the Claude Agent SDK runtime.

autocodabench's friendliest path is **subscription auth**: if Claude Code is
installed and logged in (Pro/Max plan), the Agent SDK just works and usage
draws from the plan's monthly Agent SDK credit — no keys to manage. The
second path is ``ANTHROPIC_API_KEY``, which is also the *required* path for
any hosted multi-user deployment (Anthropic does not permit routing requests
through one person's subscription credentials on behalf of other users).

The SDK's own precedence is the reverse of our recommendation: an exported
``ANTHROPIC_API_KEY`` silently wins over a stored subscription login. The
status report exists chiefly to surface that foot-gun.

Nothing here can *prove* a login is valid without spending a turn — use
``probe()`` for an end-to-end confirmation.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AuthStatus:
    effective: str                       # "api_key" | "subscription" | "none"
    api_key_set: bool = False
    subscription_login_detected: bool = False
    cli_path: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective": self.effective,
            "api_key_set": self.api_key_set,
            "subscription_login_detected": self.subscription_login_detected,
            "cli_path": self.cli_path,
            "warnings": self.warnings,
        }

    def describe(self) -> str:
        lines = []
        if self.effective == "api_key":
            lines.append("Auth: ANTHROPIC_API_KEY (usage billed to the API account).")
        elif self.effective == "subscription":
            lines.append("Auth: Claude subscription login (usage draws from your "
                         "plan's Agent SDK credit).")
        else:
            lines.append(
                "Auth: none detected. Either log in to Claude Code (`claude` then "
                "`/login`) to use your Pro/Max subscription, or export "
                "ANTHROPIC_API_KEY. Keyless commands (validate, demo --replay) "
                "still work.")
        cli = self.cli_path or ("(not found — the Agent SDK ships its own "
                                "runtime, so this is informational)")
        lines.append(f"  api key set:           {self.api_key_set}")
        lines.append(f"  subscription login:    {self.subscription_login_detected}")
        lines.append(f"  claude CLI on PATH:    {cli}")
        for w in self.warnings:
            lines.append(f"  ⚠ {w}")
        return "\n".join(lines)


def _subscription_login_detected() -> bool:
    """Best-effort: look for the artifacts `claude /login` leaves behind.

    On Linux the OAuth credential lives at ``~/.claude/.credentials.json``;
    on macOS it lives in the Keychain, but ``~/.claude.json`` records the
    ``oauthAccount`` after a successful login. Neither proves the token is
    still valid — ``probe()`` does that.
    """
    home = Path.home()
    if (home / ".claude" / ".credentials.json").is_file():
        return True
    cfg = home / ".claude.json"
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            if data.get("oauthAccount"):
                return True
        except (json.JSONDecodeError, OSError):
            pass
    return False


def resolve_auth() -> AuthStatus:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    api_key_set = api_key is not None
    subscription = _subscription_login_detected()
    cli = shutil.which("claude")

    warnings: list[str] = []
    if api_key_set and not api_key:
        warnings.append("ANTHROPIC_API_KEY is set but EMPTY — it still wins the "
                        "precedence slot and authenticates with an empty key. "
                        "Unset it (don't just blank it).")
    if api_key_set and subscription:
        warnings.append("ANTHROPIC_API_KEY shadows your subscription login: usage "
                        "will bill the API account, not your plan's Agent SDK "
                        "credit. Unset the key to use the subscription.")

    if api_key_set:
        effective = "api_key"
    elif subscription:
        effective = "subscription"
    else:
        effective = "none"

    return AuthStatus(
        effective=effective,
        api_key_set=api_key_set,
        subscription_login_detected=subscription,
        cli_path=cli,
        warnings=warnings,
    )


async def probe(model: str | None = None) -> dict[str, Any]:
    """Spend one tiny turn to confirm auth works end to end."""
    from .backends.base import AgentTask
    from .backends.claude import ClaudeAgentBackend

    backend = ClaudeAgentBackend(model=model) if model else ClaudeAgentBackend()
    result = await backend.run(AgentTask(
        prompt="Reply with exactly: OK", allowed_tools=[]))
    return {
        "ok": result.ok and "OK" in (result.final_text or ""),
        "status": result.status,
        "cost_usd": result.total_cost_usd,
        "error": result.error,
    }
