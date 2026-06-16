"""Unit tests for the system-prerequisite preflight (keyless, no Docker needed).

The checks are forced via monkeypatch so the suite never depends on whether
Docker/npx/git happen to be installed on the test host.
"""
from __future__ import annotations

import autocodabench.preflight as P


def test_system_report_shape():
    checks = P.system_report()
    names = [c.name for c in checks]
    assert names == ["Docker", "Node / npx", "git"]
    # Docker is the only hard prerequisite; the others advise.
    assert [c.required for c in checks] == [True, False, False]
    # render must never raise and must mention every check.
    out = P.render_report(checks)
    for n in names:
        assert n in out


def test_docker_ok(monkeypatch):
    # check_docker does `from .runner import docker_daemon_status`, so patch the
    # symbol on the runner package (the lazily-imported source).
    import autocodabench.runner as R
    monkeypatch.setattr(R, "docker_daemon_status", lambda: {
        "cli_installed": True, "daemon_running": True,
        "os": "linux", "arch": "arm64", "server_version": "27.0"})
    c = P.check_docker()
    assert c.status == "ok" and c.required and "27.0" in c.detail


def test_docker_no_cli(monkeypatch):
    import autocodabench.runner as R
    monkeypatch.setattr(R, "docker_daemon_status", lambda: {
        "cli_installed": False, "daemon_running": False,
        "os": None, "arch": None, "server_version": None})
    c = P.check_docker()
    assert c.status == "fail" and c.required and "PATH" in c.detail and c.hint


def test_docker_daemon_down(monkeypatch):
    import autocodabench.runner as R
    monkeypatch.setattr(R, "docker_daemon_status", lambda: {
        "cli_installed": True, "daemon_running": False,
        "os": None, "arch": None, "server_version": None})
    c = P.check_docker()
    assert c.status == "fail" and "not reachable" in c.detail


def test_npx_and_git(monkeypatch):
    monkeypatch.setattr(P.shutil, "which", lambda name: None)
    assert P.check_npx().status == "warn"
    assert P.check_git().status == "warn"
    monkeypatch.setattr(P.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert P.check_npx().status == "ok"
    assert P.check_git().status == "ok"


def test_doctor_exit_code(monkeypatch, capsys):
    from autocodabench.cli.main import _cmd_doctor
    import argparse
    # Docker fails -> exit 1.
    monkeypatch.setattr(P, "system_report", lambda: [
        P.Check("Docker", "fail", True, "x", "no daemon", "install it"),
        P.Check("git", "ok", False, "y", "found", ""),
    ])
    rc = _cmd_doctor(argparse.Namespace(as_json=False))
    assert rc == 1
    assert "missing" in capsys.readouterr().out

    # All ok -> exit 0.
    monkeypatch.setattr(P, "system_report", lambda: [
        P.Check("Docker", "ok", True, "x", "ok", ""),
    ])
    assert _cmd_doctor(argparse.Namespace(as_json=False)) == 0


def test_require_docker_blocks(monkeypatch, capsys):
    from autocodabench.cli import main as M
    # A failing Docker check blocks build / plan-build-validate, and the message
    # points at the prerequisites doc.
    monkeypatch.setattr(
        P, "check_docker",
        lambda: P.Check("Docker", "fail", True, "x", "no daemon", "install it"))
    assert M._require_docker() is False
    err = capsys.readouterr().err
    assert "Docker is required" in err and M._PREREQS_URL in err
    # A healthy Docker check lets it proceed.
    monkeypatch.setattr(
        P, "check_docker",
        lambda: P.Check("Docker", "ok", True, "x", "ok", ""))
    assert M._require_docker() is True
