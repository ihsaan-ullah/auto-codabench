"""System-prerequisite checks — the dependencies pip cannot install.

autocodabench's Python dependencies install with ``pip install -e .``. But three
capabilities rely on *system* tools that are not Python packages and therefore
cannot be declared in ``pyproject.toml``:

- **Docker** (engine + CLI) — REQUIRED for phases 2-3. The build phase
  self-validates, and ``validate``'s runtime checks run, by executing a bundle's
  programs inside its declared ``docker_image`` exactly as the Codabench worker
  does. With no reachable daemon, those runs cannot happen.
- **Node / npx** — used to launch the external OpenAlex research MCP server in
  Phase 1. Optional: planning still works without it, just without that source.
- **git** — used by the Claude Agent SDK for git-aware behavior.

:func:`system_report` returns a structured status for each. The ``doctor`` CLI
command renders it, and the build/create entrypoints call :func:`check_docker`
to fail fast — before any model spend — when Docker is missing. Nothing here
raises.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass

_DOCKER_NEEDED_FOR = "phases 2-3 (build self-validation + validate runtime checks)"
_NPX_NEEDED_FOR = "OpenAlex research in Phase 1 (optional)"
_GIT_NEEDED_FOR = "Claude Agent SDK git-aware behavior"

_DOCKER_HINT = (
    "install Docker Desktop (macOS/Windows: "
    "https://www.docker.com/products/docker-desktop/) or Docker Engine "
    "(Linux: https://docs.docker.com/engine/install/), then start it — see docker/README.md"
)
_NPX_HINT = (
    "install Node.js, which provides npx (https://nodejs.org/, or `brew install node` / "
    "your distro's package); only needed for the OpenAlex research source"
)
_GIT_HINT = "install git (https://git-scm.com/downloads, or your OS package manager)"


@dataclass
class Check:
    """One prerequisite's status. ``status`` is 'ok' | 'warn' | 'fail'."""

    name: str
    status: str
    required: bool        # True = a hard prerequisite for the phase it serves
    needed_for: str
    detail: str
    hint: str

    @property
    def glyph(self) -> str:
        return {"ok": "✅", "warn": "⚠️", "fail": "❌"}.get(self.status, "•")

    def as_dict(self) -> dict:
        return {
            "name": self.name, "status": self.status, "required": self.required,
            "needed_for": self.needed_for, "detail": self.detail, "hint": self.hint,
        }


def check_docker() -> Check:
    """Probe the Docker CLI + daemon (reuses the runner's status helper)."""
    try:
        from .runner import docker_daemon_status
        st = docker_daemon_status()
    except Exception as e:  # pragma: no cover - defensive; import/probe failure
        return Check("Docker", "fail", True, _DOCKER_NEEDED_FOR,
                     f"could not probe Docker: {type(e).__name__}: {e}", _DOCKER_HINT)
    if not st.get("cli_installed"):
        return Check("Docker", "fail", True, _DOCKER_NEEDED_FOR,
                     "docker CLI not found on PATH", _DOCKER_HINT)
    if not st.get("daemon_running"):
        return Check("Docker", "fail", True, _DOCKER_NEEDED_FOR,
                     "docker CLI present but the daemon is not reachable (is Docker started?)",
                     _DOCKER_HINT)
    ver = st.get("server_version") or "?"
    arch = st.get("arch") or "?"
    return Check("Docker", "ok", True, _DOCKER_NEEDED_FOR,
                 f"daemon running (server {ver}, {arch})", "")


def check_npx() -> Check:
    path = shutil.which("npx")
    if path is None:
        return Check("Node / npx", "warn", False, _NPX_NEEDED_FOR,
                     "npx not found on PATH", _NPX_HINT)
    return Check("Node / npx", "ok", False, _NPX_NEEDED_FOR, f"found at {path}", "")


def check_git() -> Check:
    path = shutil.which("git")
    if path is None:
        return Check("git", "warn", False, _GIT_NEEDED_FOR, "git not found on PATH", _GIT_HINT)
    return Check("git", "ok", False, _GIT_NEEDED_FOR, f"found at {path}", "")


def system_report() -> list[Check]:
    """All system-prerequisite checks, in priority order."""
    return [check_docker(), check_npx(), check_git()]


def render_report(checks: list[Check]) -> str:
    """Human-readable, CLI-style rendering of a list of checks."""
    name_w = max((len(c.name) for c in checks), default=0)
    lines: list[str] = []
    for c in checks:
        lines.append(f"{c.glyph} {c.name:<{name_w}}  {c.detail}")
        lines.append(f"      · needed for: {c.needed_for}")
        if c.status != "ok" and c.hint:
            lines.append(f"      · fix: {c.hint}")
    return "\n".join(lines)
