"""Phase-1 research capability: config → backend-aware resolution (keyless).

OpenAlex is an external MCP server (launched via ``npx``); Kaggle is served by
the first-party autocodabench MCP tools (needs the ``kaggle`` package + a token).
The suite controls ``PATH`` and ``find_spec`` so it never depends on whether
``npx`` or ``kaggle`` happen to be installed on the test host.
"""
import importlib.util

import autocodabench.agent.research as R
from autocodabench.agent.research import (
    ResearchConfig, resolve, describe, kaggle_token, backend_supports_research,
    _KAGGLE_FALLBACK_TOKEN,
)


class _Claude:
    name = "claude"


class _Generic:
    name = "openai-compatible"


def _fake_npx(monkeypatch, tmp_path):
    """Put a discoverable `npx` on PATH for the OpenAlex launcher check."""
    bind = tmp_path / "bin"; bind.mkdir()
    npx = bind / "npx"; npx.write_text("#!/bin/sh\n"); npx.chmod(0o755)
    monkeypatch.setenv("PATH", str(bind))


def _kaggle_installed(monkeypatch, present: bool):
    """Force the `kaggle`-package availability check deterministically."""
    real = importlib.util.find_spec
    monkeypatch.setattr(
        R.importlib.util, "find_spec",
        lambda name, *a, **k: (object() if present else None) if name == "kaggle"
        else real(name, *a, **k))


def test_default_config_wants_all():
    c = ResearchConfig()
    assert c.wants("openalex") and c.wants("kaggle") and c.wants("web_search")


def test_off_disables_everything():
    res = resolve(ResearchConfig.off(), backend=_Claude())
    assert res.servers == {} and res.tools == [] and not res.web_search
    assert all("off" in v for v in res.sources.values())


def test_generic_backend_cannot_use_research():
    assert not backend_supports_research(_Generic())
    assert backend_supports_research(_Claude())
    res = resolve(ResearchConfig(), backend=_Generic())
    assert not res.backend_supported
    assert res.servers == {} and not res.web_search and res.tools == []
    assert res.effective() == {"openalex": False, "kaggle": False, "web_search": False}


def test_claude_backend_wires_all_sources(monkeypatch, tmp_path):
    _fake_npx(monkeypatch, tmp_path)
    _kaggle_installed(monkeypatch, True)
    monkeypatch.delenv("KAGGLE_API_TOKEN", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))   # no ~/.kaggle → shared fallback
    res = resolve(ResearchConfig(), backend=_Claude())
    # OpenAlex is an external npx server…
    assert "openalex" in res.servers
    assert res.servers["openalex"]["command"] == "npx"
    assert res.servers["openalex"]["env"]["OPENALEX_EMAIL"]
    assert "mcp__openalex__*" in res.tools
    # …Kaggle is first-party tools + a token injected into the phase env…
    assert any("search_kaggle_competitions" in t for t in res.tools)
    assert any("get_kaggle_competition" in t for t in res.tools)
    assert res.env.get("KAGGLE_API_TOKEN") == _KAGGLE_FALLBACK_TOKEN
    # …and web search is on (no launcher needed).
    assert res.web_search and "WebSearch" in res.tools
    assert res.effective() == {"openalex": True, "kaggle": True, "web_search": True}


def test_missing_npx_only_disables_openalex(monkeypatch):
    monkeypatch.setenv("PATH", "")           # no npx
    _kaggle_installed(monkeypatch, True)
    res = resolve(ResearchConfig(), backend=_Claude())
    assert "openalex" not in res.servers
    assert "unavailable" in res.sources["openalex"]
    # Kaggle (first-party) and web search are independent of npx.
    assert any("search_kaggle_competitions" in t for t in res.tools)
    assert res.web_search


def test_missing_kaggle_package_marks_unavailable(monkeypatch, tmp_path):
    _fake_npx(monkeypatch, tmp_path)
    _kaggle_installed(monkeypatch, False)
    res = resolve(ResearchConfig(), backend=_Claude())
    assert not any("kaggle" in t for t in res.tools)
    assert "KAGGLE_API_TOKEN" not in res.env
    assert "unavailable" in res.sources["kaggle"]
    # OpenAlex still wired.
    assert "openalex" in res.servers


def test_env_override_openalex_launcher(monkeypatch):
    """A user can point OpenAlex at a pip/global install instead of npx."""
    monkeypatch.setenv("AUTOCODABENCH_OPENALEX_MCP_CMD", "openalex-mcp")
    monkeypatch.setattr(R.shutil, "which", lambda c: "/usr/bin/openalex-mcp")
    res = resolve(ResearchConfig(openalex=True, kaggle=False, web_search=False),
                  backend=_Claude())
    assert res.servers["openalex"]["command"] == "openalex-mcp"
    assert res.servers["openalex"]["args"] == []


def test_user_kaggle_token_preferred(monkeypatch):
    monkeypatch.setenv("KAGGLE_API_TOKEN", "KGAT_user_supplied")
    tok, user = kaggle_token()
    assert tok == "KGAT_user_supplied" and user is True


def test_kaggle_token_falls_back(monkeypatch):
    monkeypatch.delenv("KAGGLE_API_TOKEN", raising=False)
    monkeypatch.setenv("HOME", "/nonexistent-home-for-test")
    tok, user = kaggle_token()
    assert tok == _KAGGLE_FALLBACK_TOKEN and user is False


def test_describe_is_per_source_lines():
    lines = describe(resolve(ResearchConfig.off(), backend=_Claude()))
    assert len(lines) == 3
    assert any("OpenAlex" in l for l in lines)
    assert any("Kaggle" in l for l in lines)
