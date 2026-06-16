"""CLI surface tests — keyless paths only."""
import pytest

from autocodabench.cli.main import main, _make_progress_renderer

from conftest import DEMO_SLUG


# --- create progress renderer (default vs --debug) -------------------------

_EVENTS = [
    {"kind": "phase", "index": 2, "total": 3, "title": "Building the bundle",
     "detail": "writing files; linting; zipping"},
    {"kind": "tool_use", "name": "mcp__autocodabench__autocodabench_init_bundle",
     "input": {"slug": "create"}},
    {"kind": "tool_use", "name": "mcp__autocodabench__autocodabench_log_event",
     "input": {"kind": "progress", "message": "Wrote the scoring program."}},
    {"kind": "tool_result", "is_error": True,
     "preview": "TypeError: unexpected keyword argument 'multi_class'"},
    {"kind": "tool_result", "is_error": True,
     "preview": "Cancelled: parallel tool call Bash(...) errored"},
    {"kind": "tool_use", "name": "mcp__autocodabench__autocodabench_log_event",
     "input": {"kind": "deviation", "message": "Removed multi_class; acc 0.92."}},
    {"kind": "text", "text": "Let me wire the scoring program next."},
    {"kind": "phase_done", "phase": "build", "ok": True, "num_turns": 23},
]


def _render(events, *, debug):
    import io
    import contextlib
    buf = io.StringIO()
    r = _make_progress_renderer(debug=debug)
    with contextlib.redirect_stdout(buf):
        for e in events:
            r(e)
    return buf.getvalue()


def test_default_renderer_is_user_oriented():
    out = _render(_EVENTS, debug=False)
    # User-facing milestone + deviation messages are shown…
    assert "Wrote the scoring program." in out
    assert "Removed multi_class; acc 0.92." in out
    # …tool calls are rendered as friendly actions (not raw tool ids)…
    assert "Init bundle create" in out
    assert "init_bundle" not in out
    # …the agent's narration is shown (it is the user-friendly story)…
    assert "Let me wire the scoring program next." in out
    # …but raw errors and benign parallel cancellations are suppressed.
    assert "TypeError" not in out
    assert "Cancelled" not in out


def test_debug_renderer_shows_full_trace_and_softens_cancellations():
    out = _render(_EVENTS, debug=True)
    assert "Init bundle create" in out             # friendly action…
    assert "init_bundle" in out                    # …with the raw id kept greppable
    assert "TypeError" in out                      # genuine error shown
    assert "Let me wire the scoring program next." in out  # narration shown
    assert "Cancelled" not in out                  # cascade is reworded…
    assert "retried" in out                        # …as a benign retry


def test_checks_list(capsys):
    assert main(["checks", "list"]) == 0
    out = capsys.readouterr().out
    assert "[deterministic]" in out
    assert "bundle-schema" in out


def test_demo_then_validate(tmp_path, capsys):
    out_dir = tmp_path / "demo-out"
    assert main(["demo", "--out", str(out_dir)]) == 0
    out = capsys.readouterr().out
    assert "no LLM, no keys" in out
    assert "Bundle validation — ✅ PASS" in out

    assert main(["validate", str(out_dir / DEMO_SLUG), "--no-execute"]) == 0
    assert "Bundle validation" in capsys.readouterr().out


def test_validate_json_output(demo_bundle, capsys):
    assert main(["validate", str(demo_bundle), "--no-execute", "--json"]) == 0
    out = capsys.readouterr().out
    assert '"ok": true' in out


def test_validate_exit_code_on_gate_failure(demo_bundle, capsys):
    (demo_bundle / "pages" / "terms.md").unlink()
    assert main(["validate", str(demo_bundle), "--no-execute"]) == 1


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_create_requires_idea_or_pdf(capsys):
    # Neither an idea nor --pdf → guard returns 2 before any backend/auth touch.
    assert main(["create"]) == 2
    assert "idea" in capsys.readouterr().err.lower()


def test_create_pdf_must_exist(capsys):
    assert main(["create", "--pdf", "/no/such/proposal.pdf"]) == 2
    assert "not a file" in capsys.readouterr().err.lower()


def test_plan_requires_idea_or_pdf(capsys):
    assert main(["plan"]) == 2
    assert "idea" in capsys.readouterr().err.lower()


def test_plan_pdf_must_exist(capsys):
    assert main(["plan", "--pdf", "/no/such/proposal.pdf"]) == 2
    assert "not a file" in capsys.readouterr().err.lower()


# --- docker preflight banner ----------------------------------------------

import autocodabench.runner as _runner
from autocodabench.cli.main import _bundle_declared_image, _print_docker_preflight


def _fake_preflight(**over):
    base = {
        "host_arch": "arm64", "host_os": "Darwin",
        "docker": {"cli_installed": True, "daemon_running": True,
                   "os": "linux", "arch": "arm64", "server_version": "27.0"},
        "image": "codalab/codalab-legacy:py312",
        "image_present_locally": True, "image_arch": "arm64",
        "image_available_arches": ["arm64"], "image_multi_arch": False,
        "image_source": "local image", "image_error": None,
        "runs_natively": True, "emulated": False, "ready": True,
    }
    base.update(over)
    return base


def test_preflight_banner_native(monkeypatch, capsys):
    monkeypatch.setattr(_runner, "docker_preflight", lambda image: _fake_preflight())
    _print_docker_preflight("codalab/codalab-legacy:py312", required=False)
    out = capsys.readouterr().out
    assert "Docker runtime" in out
    assert "runs natively" in out
    assert "arm64 (Darwin)" in out


def test_preflight_banner_emulated_warns(monkeypatch, capsys):
    monkeypatch.setattr(_runner, "docker_preflight", lambda image: _fake_preflight(
        image="codalab/codalab-legacy:py39", image_arch="amd64",
        image_available_arches=["amd64"], image_present_locally=False,
        image_source="remote manifest", runs_natively=False, emulated=True))
    _print_docker_preflight("codalab/codalab-legacy:py39", required=True)
    out = capsys.readouterr().out
    assert "QEMU emulation" in out
    assert "AUTOCODABENCH_DOCKER_IMAGE=codalab/codalab-legacy:py312" in out


def test_preflight_banner_no_daemon_warns_when_required(monkeypatch, capsys):
    monkeypatch.setattr(_runner, "docker_preflight", lambda image: _fake_preflight(
        docker={"cli_installed": False, "daemon_running": False,
                "os": None, "arch": None, "server_version": None},
        ready=False, runs_natively=None, emulated=None, image_arch=None,
        image_available_arches=[], image_error="Docker daemon not running"))
    _print_docker_preflight("any/img:1", required=True)
    cap = capsys.readouterr()
    assert "Docker is not installed" in cap.out
    assert "WARNING:" in cap.err  # loud only when the run requires Docker


def test_bundle_declared_image_from_dir(demo_bundle):
    # The shipped demo declares a codalab image in competition.yaml.
    img = _bundle_declared_image(demo_bundle)
    assert img and "codalab" in img


def test_bundle_declared_image_from_zip(tmp_path):
    import zipfile
    z = tmp_path / "b.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("competition.yaml", "title: t\ndocker_image: myorg/img:9\n")
    assert _bundle_declared_image(z) == "myorg/img:9"


def test_bundle_declared_image_none_when_absent(tmp_path):
    (tmp_path / "competition.yaml").write_text("title: t\n")
    assert _bundle_declared_image(tmp_path) is None
# ---------------------------------------------------------------------------
# build argument guards (keyless: rejected before any live-auth probe
# or backend call, so these run without credentials)
# ---------------------------------------------------------------------------

def test_build_requires_a_plan_source(capsys):
    assert main(["build", "--yes"]) == 2
    assert "plan file" in capsys.readouterr().err


def test_build_rejects_both_sources(tmp_path, capsys):
    plan = tmp_path / "plan.md"
    plan.write_text("# plan", encoding="utf-8")
    code = main(["build", str(plan), "--run-dir", str(tmp_path), "--yes"])
    assert code == 2
    assert "not both" in capsys.readouterr().err


def test_build_missing_run_dir(tmp_path, capsys):
    missing = tmp_path / "nope"
    assert main(["build", "--run-dir", str(missing), "--yes"]) == 2
    assert "run dir not found" in capsys.readouterr().err


def test_build_run_dir_without_plan(tmp_path, capsys):
    (tmp_path / "specs").mkdir()
    assert main(["build", "--run-dir", str(tmp_path), "--yes"]) == 2
    assert "implementation_plan.md" in capsys.readouterr().err


def test_build_missing_plan_file(tmp_path, capsys):
    assert main(["build", str(tmp_path / "absent.md"), "--yes"]) == 2
    assert "plan file not found" in capsys.readouterr().err
