"""Per-phase run-directory layout: sessions, phase subdirs, flat adoption."""
import json
import os

from autocodabench import run_log
from autocodabench.core.config import resolve_bundle_dir


def test_session_groups_phases_under_shared_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCODABENCH_RUNS_ROOT", str(tmp_path))
    monkeypatch.delenv("AUTOCODABENCH_RUN_DIR", raising=False)

    s = run_log.open_session(branch_id="br", runtime_id="ts")
    assert s.path == tmp_path / "br_ts"
    assert (s.path / "manifest.json").is_file()

    p1 = run_log.open_run(slug="create", phase="phase1_plan",
                          session_dir=s.path, branch_id="br", runtime_id="ts")
    p2 = run_log.open_run(slug="create", phase="phase2_build",
                          session_dir=s.path, branch_id="br", runtime_id="ts")
    assert p1.path == tmp_path / "br_ts" / "phase1_plan"
    assert p2.path == tmp_path / "br_ts" / "phase2_build"
    assert (p1.path / "meta.json").is_file()
    assert json.loads((p1.path / "meta.json").read_text())["phase"] == "phase1_plan"

    # The most recently opened phase is the active run, and bundles resolve
    # under it (so phase 2 writes into phase2_build/bundles/).
    assert os.environ["AUTOCODABENCH_RUN_DIR"] == str(p2.path)
    assert resolve_bundle_dir("demo") == p2.path / "bundles" / "demo"


def test_record_session_phase_writes_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCODABENCH_RUNS_ROOT", str(tmp_path))
    monkeypatch.delenv("AUTOCODABENCH_RUN_DIR", raising=False)
    s = run_log.open_session(branch_id="br", runtime_id="ts2")
    run_log.record_session_phase(s.path, "phase2_build", {"ok": True, "bundle_dir": "x"})
    man = json.loads((s.path / "manifest.json").read_text())
    assert man["phases"]["phase2_build"] == {"ok": True, "bundle_dir": "x"}


def test_flat_open_run_still_adopts_inherited_dir(tmp_path, monkeypatch):
    """The default (non-phase) path is unchanged: a child that inherits
    AUTOCODABENCH_RUN_DIR joins the parent's run rather than forking a new one
    — the contract the MCP subprocesses and the experiment harness rely on."""
    monkeypatch.setenv("AUTOCODABENCH_RUNS_ROOT", str(tmp_path))
    monkeypatch.delenv("AUTOCODABENCH_RUN_DIR", raising=False)

    a = run_log.open_run(slug="x", branch_id="br", runtime_id="ts3")
    assert a.path == tmp_path / "br_ts3"  # flat, no phase subdir

    # Simulate a fresh child process: env points at the run, module state reset.
    monkeypatch.setenv("AUTOCODABENCH_RUN_DIR", str(a.path))
    monkeypatch.setattr(run_log, "_current_run", None)
    b = run_log.open_run(slug="ignored")
    assert b.path == a.path  # adopted, not a new dir
