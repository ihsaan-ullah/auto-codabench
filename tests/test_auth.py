"""Tests for auth resolution (filesystem + env detection only; no probing)."""
import json
from pathlib import Path

import pytest

from autocodabench import auth


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return home


def test_none_detected(fake_home):
    status = auth.resolve_auth()
    assert status.effective == "none"
    assert not status.warnings


def test_api_key_wins(fake_home, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    status = auth.resolve_auth()
    assert status.effective == "api_key"


def test_subscription_via_credentials_file(fake_home):
    creds = fake_home / ".claude" / ".credentials.json"
    creds.parent.mkdir()
    creds.write_text("{}")
    status = auth.resolve_auth()
    assert status.effective == "subscription"


def test_subscription_via_oauth_account(fake_home):
    (fake_home / ".claude.json").write_text(json.dumps({"oauthAccount": {"id": "x"}}))
    status = auth.resolve_auth()
    assert status.effective == "subscription"


def test_api_key_shadows_subscription_with_warning(fake_home, monkeypatch):
    creds = fake_home / ".claude" / ".credentials.json"
    creds.parent.mkdir()
    creds.write_text("{}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    status = auth.resolve_auth()
    assert status.effective == "api_key"
    assert any("shadows" in w for w in status.warnings)


def test_empty_api_key_warns(fake_home, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    status = auth.resolve_auth()
    assert status.effective == "api_key"
    assert any("EMPTY" in w for w in status.warnings)


def test_describe_renders(fake_home):
    assert "Auth:" in auth.resolve_auth().describe()
