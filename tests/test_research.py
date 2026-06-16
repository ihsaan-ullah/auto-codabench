"""Phase-1 research capability: config → backend-aware resolution (keyless)."""
import os

from autocodabench.agent.research import (
    ResearchConfig, resolve, describe, kaggle_token, backend_supports_research,
    _KAGGLE_FALLBACK_TOKEN,
)


class _Claude:
    name = "claude"


class _Generic:
    name = "openai-compatible"


def _env_with_uvx(monkeypatch, tmp_path):
    """Make a fake `uvx` discoverable so launcher availability is satisfied."""
    fake = tmp_path / "bin"; fake.mkdir()
    uvx = fake / "uvx"; uvx.write_text("#!/bin/sh\n"); uvx.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake), prepend=False)
    return fake


def test_default_config_wants_all():
    c = ResearchConfig()
    assert c.wants("openalex") and c.wants("kaggle") and c.wants("web_search")


def test_off_disables_everything():
    c = ResearchConfig.off()
    assert not any(c.wants(s) for s in ("openalex", "kaggle", "web_search"))
    res = resolve(c, backend=_Claude())
    assert res.servers == {} and res.tools == [] and not res.web_search
    assert all("off" in v for v in res.sources.values())


def test_generic_backend_cannot_use_research():
    """Only the Claude backend hosts external MCP / web tools."""
    assert not backend_supports_research(_Generic())
    assert backend_supports_research(_Claude())
    res = resolve(ResearchConfig(), backend=_Generic())
    assert not res.backend_supported
    assert res.servers == {} and not res.web_search
    assert res.effective() == {"openalex": False, "kaggle": False, "web_search": False}


def test_claude_backend_wires_servers_when_launcher_present(monkeypatch, tmp_path):
    _env_with_uvx(monkeypatch, tmp_path)
    res = resolve(ResearchConfig(), backend=_Claude())
    assert set(res.servers) == {"openalex", "kaggle"}
    assert "mcp__openalex__*" in res.tools and "mcp__kaggle__*" in res.tools
    assert res.web_search and "WebSearch" in res.tools and "WebFetch" in res.tools
    # Kaggle server gets a token (the shared fallback by default).
    assert res.servers["kaggle"]["env"]["KAGGLE_API_TOKEN"] == _KAGGLE_FALLBACK_TOKEN
    assert res.effective() == {"openalex": True, "kaggle": True, "web_search": True}


def test_missing_launcher_marks_unavailable(monkeypatch):
    monkeypatch.setenv("PATH", "")  # nothing discoverable
    res = resolve(ResearchConfig(), backend=_Claude())
    assert res.servers == {}
    assert "unavailable" in res.sources["openalex"]
    assert "unavailable" in res.sources["kaggle"]
    # Web search needs no launcher — still on for a Claude backend.
    assert res.web_search


def test_env_override_launcher(monkeypatch):
    """A user can point a source at a pip-installed server instead of uvx."""
    monkeypatch.setenv("AUTOCODABENCH_OPENALEX_MCP_CMD", "python -m alex_mcp.server")
    res = resolve(ResearchConfig(openalex=True, kaggle=False, web_search=False),
                  backend=_Claude())
    assert "openalex" in res.servers
    assert res.servers["openalex"]["command"] == "python"
    assert res.servers["openalex"]["args"] == ["-m", "alex_mcp.server"]


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
