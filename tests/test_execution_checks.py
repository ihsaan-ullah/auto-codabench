"""Execution-check behavior, kept keyless by mocking the Docker runner.

These verify the *check logic* — gating, cache reuse, graceful skips, and the
structured evidence the report renders — without ever invoking Docker. The
real Docker path is exercised manually / in the build phase, never in the unit
suite (which must stay fast and keyless).
"""
import shutil

import pytest

from autocodabench.checks import Status, validate_bundle_path
from autocodabench.runner import execution as ex


def _fresh(demo_bundle, tmp_path):
    """A private copy of the demo bundle so cache files written next to it do
    not leak between tests."""
    dst = tmp_path / "copy" / demo_bundle.name
    shutil.copytree(demo_bundle, dst)
    return dst


def _docker_ok(monkeypatch):
    monkeypatch.setattr(ex, "resolve_execution_engine",
                        lambda engine="auto": {"engine": "docker", "note": None, "error": None})
    monkeypatch.setattr(ex, "docker_preflight", lambda image=None: {
        "host_arch": "arm64", "image_arch": "arm64",
        "image_available_arches": ["arm64"], "emulated": False})


def _result(report, check_id):
    rs = [r for r in report.results if r.check_id == check_id]
    assert len(rs) == 1, f"expected exactly one {check_id}, got {len(rs)}"
    return rs[0]


def test_execution_checks_absent_without_execute(demo_bundle):
    report = validate_bundle_path(demo_bundle)  # default: static only
    ids = {r.check_id for r in report.results}
    assert "baseline-execution" not in ids
    assert "starting-kit-execution" not in ids


def test_baseline_execution_pass_records_evidence(demo_bundle, tmp_path, monkeypatch):
    b = _fresh(demo_bundle, tmp_path)
    _docker_ok(monkeypatch)
    seen = {}

    def fake_baseline(slug, root_dir=None, **kw):
        seen["args"] = (slug, root_dir)
        return {"ok": True, "docker_image": "codalab/x:1", "stage": "scoring",
                "duration_s": 3.2, "scores": {"acc": 0.9},
                "data": {"reference_data": ["truth.csv"], "input_data_present": True},
                "logs_dir": str(b.parent / "logs")}

    monkeypatch.setattr(ex, "run_baseline_submission", fake_baseline)
    report = validate_bundle_path(b, execute=True)
    r = _result(report, "baseline-execution")
    assert r.status == Status.PASS
    assert r.details["source"] == "executed"
    assert r.details["scores"] == {"acc": 0.9}
    assert r.details["emulated"] is False
    # the runner was called with the bundle's own slug + parent as root
    assert seen["args"] == (b.name, str(b.parent))
    assert report.ok


def test_baseline_execution_failure_gates(demo_bundle, tmp_path, monkeypatch):
    b = _fresh(demo_bundle, tmp_path)
    _docker_ok(monkeypatch)
    monkeypatch.setattr(ex, "run_baseline_submission",
                        lambda slug, root_dir=None, **kw: {
                            "ok": False, "error": "scoring exit 1",
                            "docker_image": "x:1", "stage": "scoring",
                            "duration_s": 1.0, "scores": None, "data": {},
                            "logs_dir": "/x"})
    report = validate_bundle_path(b, execute=True)
    assert _result(report, "baseline-execution").status == Status.FAIL
    assert not report.ok  # execution failure is a deterministic gate


def test_baseline_execution_reuses_cached_run(demo_bundle, tmp_path, monkeypatch):
    b = _fresh(demo_bundle, tmp_path)
    _docker_ok(monkeypatch)
    ex.write_execution_cache_entry(b, "baseline", {
        "kind": "baseline", "slug": b.name, "ok": True,
        "input_hash": ex.bundle_content_hash(b), "phase": "build",
        "docker_image": "x:1", "duration_s": 9.9, "stage": "scoring",
        "scores": {"acc": 0.5}, "data": {"reference_data": ["truth.csv"]},
        "logs_dir": "/x", "timestamp": "2026-06-14T00:00:00Z"})

    def boom(*a, **k):
        raise AssertionError("runner must not be called on a cache hit")

    monkeypatch.setattr(ex, "run_baseline_submission", boom)
    report = validate_bundle_path(b, execute=True)
    r = _result(report, "baseline-execution")
    assert r.status == Status.PASS
    assert r.details["source"] == "reused"
    assert r.details["phase"] == "build"


def test_cache_invalidated_when_bundle_changes(demo_bundle, tmp_path, monkeypatch):
    b = _fresh(demo_bundle, tmp_path)
    _docker_ok(monkeypatch)
    ex.write_execution_cache_entry(b, "baseline", {
        "kind": "baseline", "slug": b.name, "ok": True,
        "input_hash": ex.bundle_content_hash(b), "phase": "build",
        "docker_image": "x:1", "duration_s": 9.9, "scores": {"acc": 0.5},
        "logs_dir": "/x"})
    # Edit a scored file → hash changes → cache must be ignored and a run done.
    (b / "scoring_program" / "score.py").write_text("# changed\n", encoding="utf-8")
    ran = {"n": 0}

    def fake_baseline(slug, root_dir=None, **kw):
        ran["n"] += 1
        return {"ok": True, "docker_image": "x:1", "stage": "scoring",
                "duration_s": 1.0, "scores": {"acc": 0.7}, "data": {}, "logs_dir": "/x"}

    monkeypatch.setattr(ex, "run_baseline_submission", fake_baseline)
    report = validate_bundle_path(b, execute=True)
    assert ran["n"] == 1
    assert _result(report, "baseline-execution").details["source"] == "executed"


def test_no_docker_skips_not_fails(demo_bundle, tmp_path, monkeypatch):
    b = _fresh(demo_bundle, tmp_path)
    monkeypatch.setattr(ex, "resolve_execution_engine",
                        lambda engine="auto": {"engine": None, "note": None,
                                               "error": "no Docker daemon is reachable."})
    report = validate_bundle_path(b, execute=True)
    assert _result(report, "baseline-execution").status == Status.SKIPPED
    assert report.ok  # a missing daemon must never gate


def test_missing_baseline_is_finding(demo_bundle, tmp_path, monkeypatch):
    b = _fresh(demo_bundle, tmp_path)
    _docker_ok(monkeypatch)
    shutil.rmtree(b / "solutions")
    report = validate_bundle_path(b, execute=True)
    # No baseline to run → advisory finding (not a hard execution gate). The
    # bundle-schema gate separately objects to the now-dangling declaration.
    assert _result(report, "baseline-execution").status == Status.FINDING


def test_missing_notebook_skips_starting_kit(demo_bundle, tmp_path, monkeypatch):
    b = _fresh(demo_bundle, tmp_path)
    _docker_ok(monkeypatch)
    monkeypatch.setattr(ex, "run_baseline_submission",
                        lambda slug, root_dir=None, **kw: {
                            "ok": True, "docker_image": "x:1", "stage": "scoring",
                            "duration_s": 1.0, "scores": {"a": 1}, "data": {}, "logs_dir": "/x"})
    report = validate_bundle_path(b, execute=True)
    # demo ships no .ipynb → the notebook execution check skips cleanly
    assert _result(report, "starting-kit-execution").status == Status.SKIPPED


def test_report_renders_execution_section(demo_bundle, tmp_path, monkeypatch):
    b = _fresh(demo_bundle, tmp_path)
    _docker_ok(monkeypatch)
    monkeypatch.setattr(ex, "run_baseline_submission",
                        lambda slug, root_dir=None, **kw: {
                            "ok": True, "docker_image": "codalab/x:1", "stage": "scoring",
                            "duration_s": 3.0, "scores": {"acc": 0.9},
                            "data": {"reference_data": ["truth.csv"], "input_data_present": True},
                            "logs_dir": "/x"})
    md = validate_bundle_path(b, execute=True).to_markdown()
    assert "## ▶ Execution" in md
    assert "executed now" in md
    assert "acc=0.9" in md
