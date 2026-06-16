"""Phase-1 research capability: external knowledge sources for the planner.

Phase 1 (plan) is far more useful when it can look at what already exists than
when it draws on the backbone's training data alone. Two external MCP servers
plus the agent's own web search give it that reach:

- **OpenAlex** (the ``alex-mcp`` server) — recent *related competition and
  benchmark papers* (e.g. from the NeurIPS Competition track or the Datasets &
  Benchmarks track), so the design is grounded in current literature.
- **Kaggle** (the official ``kaggle-mcp`` server) — *how similar competitions
  are actually hosted* (metric choices, phase structure, anti-leakage rules),
  for state-of-the-art hosting suggestions.
- **Web search** — the SDK's built-in ``WebSearch`` / ``WebFetch``, for
  anything the two structured sources miss.

This module turns a small declarative :class:`ResearchConfig` into the concrete
MCP-server launch specs + extra tool allowlist the plan phase hands the backend,
and reports — for the benchmark and the CLI banner — exactly which sources a
given backbone could *actually* use. That last point is load-bearing for
benchmark fairness: **only the Claude backend can spawn external MCP servers and
call WebSearch/WebFetch**; OpenAI-compatible backbones (Ollama/OpenAI/vLLM) get
none of them, and that asymmetry must be recorded, not hidden.

Nothing here requires the user to supply a private key. OpenAlex needs only a
courtesy contact email; Kaggle's public competition reads work against a shared
throw-away token when the user has not set their own.
"""
from __future__ import annotations

import os
import shlex
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

# A public, throw-away Kaggle API token used by default so Phase 1 can read
# PUBLIC competitions out of the box without the user supplying a secret. Users
# are encouraged to generate their own at https://www.kaggle.com/settings/api
# and set KAGGLE_API_TOKEN (or ~/.kaggle/access_token); this is only a fallback.
_KAGGLE_FALLBACK_TOKEN = "KGAT_91c6614cd364fd4aedafafa664434e02"

# Default launch commands (uvx fetches + runs the server with no prior install).
# Each is overridable via an env var for pip-installed / conda / offline setups.
_OPENALEX_DEFAULT_CMD = (
    "uvx --from git+https://github.com/drAbreu/alex-mcp.git@4.1.0 alex-mcp")
_KAGGLE_DEFAULT_CMD = "uvx kaggle-mcp"

_OPENALEX_CMD_ENV = "AUTOCODABENCH_OPENALEX_MCP_CMD"
_KAGGLE_CMD_ENV = "AUTOCODABENCH_KAGGLE_MCP_CMD"


@dataclass
class ResearchConfig:
    """What external research Phase 1 is *allowed* to use (all on by default).

    The user can turn the whole capability off, or any single source off, before
    a run starts. This is intent, not availability — :func:`resolve` reconciles
    it against what the launcher/backend can actually provide.
    """

    enabled: bool = True
    openalex: bool = True
    kaggle: bool = True
    web_search: bool = True

    @classmethod
    def off(cls) -> "ResearchConfig":
        return cls(enabled=False, openalex=False, kaggle=False, web_search=False)

    def wants(self, source: str) -> bool:
        return bool(self.enabled and getattr(self, source))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResolvedResearch:
    """The concrete, backend-aware result of applying a :class:`ResearchConfig`."""

    servers: dict          # MCP server launch specs to merge into the phase
    tools: list[str]       # extra allowed_tools (mcp__openalex__*, WebSearch, …)
    web_search: bool       # whether WebSearch/WebFetch are actually enabled
    sources: dict          # per-source status string for display/recording
    backend_supported: bool  # can this backbone use external MCP/web at all?

    @property
    def any_active(self) -> bool:
        return bool(self.servers) or self.web_search

    def effective(self) -> dict:
        """Which sources are actually wired AND usable on this backbone."""
        active = lambda s: self.sources.get(s, "").startswith("on")
        return {"openalex": active("openalex"), "kaggle": active("kaggle"),
                "web_search": self.web_search}


def _split_cmd(env_value: str | None, default: str) -> list[str]:
    return shlex.split(env_value or default)


def _openalex_mailto() -> str:
    """Courtesy contact email for the OpenAlex API's polite pool (not a secret)."""
    return (os.environ.get("AUTOCODABENCH_OPENALEX_MAILTO")
            or os.environ.get("OPENALEX_MAILTO")
            or "autocodabench@users.noreply.github.com")


def kaggle_token(*, allow_fallback: bool = True) -> tuple[str | None, bool]:
    """Return ``(token, is_user_supplied)`` for the Kaggle MCP.

    Prefers a user token (``KAGGLE_API_TOKEN`` env, then
    ``~/.kaggle/access_token``); otherwise the shared throw-away fallback so
    public reads work with no setup. ``is_user_supplied`` lets the banner tell
    the user whether they are on their own token or the shared one.
    """
    env_tok = os.environ.get("KAGGLE_API_TOKEN")
    if env_tok:
        return env_tok.strip(), True
    token_file = Path.home() / ".kaggle" / "access_token"
    try:
        if token_file.is_file():
            tok = token_file.read_text(encoding="utf-8").strip()
            if tok:
                return tok, True
    except OSError:
        pass
    return (_KAGGLE_FALLBACK_TOKEN, False) if allow_fallback else (None, False)


def _server_spec(cmd: list[str], env: dict) -> dict:
    return {"type": "stdio", "command": cmd[0], "args": cmd[1:],
            "env": {**os.environ, **env}}


def backend_supports_research(backend) -> bool:
    """Only the Claude backend can spawn external MCP servers / call WebSearch.

    The OpenAI-compatible backend executes a fixed local-tool surface and ignores
    ``mcp_servers``; it has no web tool. Recording this keeps cross-backbone
    benchmark numbers honest about who had internet/MCP reach.
    """
    return getattr(backend, "name", "") == "claude"


def resolve(config: ResearchConfig | None, *, backend=None) -> ResolvedResearch:
    """Reconcile *config* against launcher and backend availability.

    Returns the MCP servers + extra tools to wire into the plan phase, plus a
    per-source status (``on`` / ``off`` / ``unavailable: …``) for the banner and
    the benchmark record.
    """
    config = config if config is not None else ResearchConfig()
    supported = backend is None or backend_supports_research(backend)
    servers: dict = {}
    tools: list[str] = []
    sources: dict = {}

    def _wire(source: str, cmd_env: str, default_cmd: str, env: dict,
              tool_glob: str, label: str) -> None:
        if not config.wants(source):
            sources[source] = "off (disabled by user)"
            return
        if not supported:
            sources[source] = "unavailable: backbone has no MCP support (Claude only)"
            return
        cmd = _split_cmd(os.environ.get(cmd_env), default_cmd)
        if not shutil.which(cmd[0]):
            sources[source] = (f"unavailable: launcher '{cmd[0]}' not found "
                               f"(install it or set {cmd_env})")
            return
        servers[source] = _server_spec(cmd, env)
        tools.append(tool_glob)
        sources[source] = f"on — {label}"

    _wire("openalex", _OPENALEX_CMD_ENV, _OPENALEX_DEFAULT_CMD,
          {"OPENALEX_MAILTO": _openalex_mailto()},
          "mcp__openalex__*", "related competition/benchmark papers")

    tok, user_supplied = kaggle_token()
    kaggle_label = ("similar competitions (your KAGGLE_API_TOKEN)"
                    if user_supplied else
                    "similar competitions (shared public token — set "
                    "KAGGLE_API_TOKEN for your own)")
    _wire("kaggle", _KAGGLE_CMD_ENV, _KAGGLE_DEFAULT_CMD,
          {"KAGGLE_API_TOKEN": tok or ""}, "mcp__kaggle__*", kaggle_label)

    web_search = config.wants("web_search") and supported
    if config.wants("web_search") and not supported:
        sources["web_search"] = "unavailable: backbone has no web tool (Claude only)"
    elif web_search:
        sources["web_search"] = "on — internet search for related competitions"
        tools += ["WebSearch", "WebFetch"]
    else:
        sources["web_search"] = "off (disabled by user)"

    return ResolvedResearch(servers=servers, tools=tools, web_search=web_search,
                            sources=sources, backend_supported=supported)


def describe(resolved: ResolvedResearch) -> list[str]:
    """Human-readable banner lines, one per source."""
    order = ("openalex", "kaggle", "web_search")
    pretty = {"openalex": "OpenAlex (related papers)",
              "kaggle": "Kaggle (similar competitions)",
              "web_search": "Web search (internet)"}
    return [f"{pretty[s]}: {resolved.sources.get(s, 'off')}" for s in order]
