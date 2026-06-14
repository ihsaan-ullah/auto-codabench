"""Tests for the Docker execution engine (keyless; no Docker daemon needed).

The engine's *selection* logic and *command construction* are tested
here; actually executing a container is verified manually and by the
experiment harness, for the same reason live-LLM calls are excluded
from the unit suite.
"""
import json
from pathlib import Path

import pytest

from autocodabench.runner import execution as ex


# -- engine resolution --------------------------------------------------------

def test_auto_prefers_docker_when_available(monkeypatch):
    monkeypatch.setattr(ex, "_docker_available", lambda: True)
    r = ex.resolve_execution_engine("auto")
    assert r["engine"] == "docker" and r["error"] is None and r["note"] is None


def test_auto_errors_without_docker(monkeypatch):
    # Docker-only: with no daemon there is no fallback — it is a hard error.
    monkeypatch.setattr(ex, "_docker_available", lambda: False)
    r = ex.resolve_execution_engine("auto")
    assert r["engine"] is None
    assert "Docker" in r["error"] and "exclusively through Docker" in r["error"]


def test_conda_engine_removed(monkeypatch):
    # The conda engine has been removed; requesting it returns a clear error.
    monkeypatch.setattr(ex, "_docker_available", lambda: True)
    r = ex.resolve_execution_engine("conda")
    assert r["engine"] is None
    assert "removed" in r["error"]


def test_explicit_docker_errors_without_daemon(monkeypatch):
    monkeypatch.setattr(ex, "_docker_available", lambda: False)
    r = ex.resolve_execution_engine("docker")
    assert r["engine"] is None and "Docker" in r["error"]


def test_unknown_engine_rejected():
    r = ex.resolve_execution_engine("podman")
    assert r["engine"] is None and "unknown engine" in r["error"]


# -- docker command construction ----------------------------------------------

def test_docker_run_mirrors_worker_contract(tmp_path):
    # stage the minimum the mount builder inspects
    (tmp_path / "program" / "scoring_program").mkdir(parents=True)
    (tmp_path / "input").mkdir()
    (tmp_path / "output").mkdir()
    cmd = ex._docker_run(
        "codalab/codalab-legacy:py37", tmp_path, "scoring_program",
        "python3 $program/score.py $input $output",
        {"OMP_NUM_THREADS": "2"}, has_ingestion=False,
    )
    assert cmd.startswith("docker run --rm ")
    # the active program dir is mounted at /app/program, as the worker does
    assert f"-v {tmp_path / 'program' / 'scoring_program'}:/app/program:rw" in cmd
    assert f"-v {tmp_path / 'input'}:/app/input:rw" in cmd
    assert f"-v {tmp_path / 'output'}:/app/output:rw" in cmd
    assert "-w /app/program" in cmd              # worker's working directory
    assert "codalab/codalab-legacy:py37" in cmd
    # canonical $variables resolved to container paths
    assert "/app/program/score.py /app/input /app/output" in cmd
    assert "$program" not in cmd and "$input" not in cmd
    assert "-e PYTHONUNBUFFERED=1" in cmd
    assert "-e OMP_NUM_THREADS=2" in cmd
    # the platform never installs requirements — neither may the engine
    assert "pip install" not in cmd


def test_resolve_command_substitutes_worker_variables(tmp_path):
    # $variables become the worker's absolute container paths; literal /app/...
    # paths are already correct and left untouched.
    out = ex._resolve_command(
        "python3 $program/score.py $input_data $input $output",
        "docker", tmp_path, "scoring_program")
    assert "/app/program/score.py /app/input_data /app/input /app/output" in out
    assert "$" not in out


# -- docker_image resolution from competition.yaml ------------------------------

def test_bundle_docker_image_reads_declared_image(tmp_path):
    bundle = tmp_path / "demo"
    bundle.mkdir()
    (bundle / "competition.yaml").write_text(
        "title: t\ndocker_image: myorg/myimage:1.2\n", encoding="utf-8")
    assert ex.bundle_docker_image("demo", str(tmp_path)) == "myorg/myimage:1.2"


def test_bundle_docker_image_defaults_to_autocodabench_base(tmp_path):
    bundle = tmp_path / "demo"
    bundle.mkdir()
    (bundle / "competition.yaml").write_text("title: t\n", encoding="utf-8")
    # With no declared image, the runner falls back to the autocodabench CPU
    # base image (overridable via AUTOCODABENCH_DOCKER_IMAGE).
    got = ex.bundle_docker_image("demo", str(tmp_path))
    assert got == ex._DEFAULT_DOCKER_IMAGE
    assert "autocodabench-base-cpu" in got


# -- engine plumbing through the sandbox runner ---------------------------------

def test_run_user_submission_requires_daemon_for_explicit_docker(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "_docker_available", lambda: False)
    bundle = tmp_path / "demo"
    (bundle / "scoring_program").mkdir(parents=True)
    sub = tmp_path / "sub"
    sub.mkdir()
    monkeypatch.setenv("AUTOCODABENCH_BUNDLES_ROOT", str(tmp_path))
    res = ex.run_user_submission("demo", env_name="unused",
                                 submission_dir=str(sub), label="t",
                                 engine="docker")
    assert res["ok"] is False and "Docker daemon" in res["error"]


# -- arch normalization -------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    ("aarch64", "arm64"), ("arm64", "arm64"), ("arm64/v8", "arm64"),
    ("x86_64", "amd64"), ("amd64", "amd64"),
    ("", "unknown"), (None, "unknown"), ("ppc64le", "ppc64le"),
])
def test_normalize_arch(raw, want):
    assert ex._normalize_arch(raw) == want


# -- image architecture detection (registry/local, no daemon needed) ----------

def _patch_query(monkeypatch, handler):
    """Replace `_docker_query(args, timeout=...)` with a canned dispatcher."""
    monkeypatch.setattr(ex, "_docker_query", lambda args, timeout=20: handler(args))


def test_image_arch_status_local_inspect(monkeypatch):
    def handler(args):
        if args[:2] == ["image", "inspect"]:
            return "arm64", None
        return None, "should not reach the registry for a local image"
    _patch_query(monkeypatch, handler)
    s = ex.image_arch_status("local/img:1")
    assert s["present_locally"] is True
    assert s["arch"] == "arm64" and s["available_arches"] == ["arm64"]
    assert s["multi_arch"] is False and s["source"] == "local image"


def test_image_arch_status_remote_multiarch(monkeypatch):
    # `docker manifest inspect --verbose` returns a JSON array for a manifest
    # list; attestation entries (architecture == "unknown") are dropped.
    manifest = json.dumps([
        {"Descriptor": {"platform": {"architecture": "amd64", "os": "linux"}}},
        {"Descriptor": {"platform": {"architecture": "arm64", "os": "linux"}}},
        {"Descriptor": {"platform": {"architecture": "unknown", "os": "unknown"}}},
    ])
    def handler(args):
        if args[:2] == ["image", "inspect"]:
            return None, "No such image"
        return manifest, None
    _patch_query(monkeypatch, handler)
    s = ex.image_arch_status("codalab/codalab-legacy:py312")
    assert s["present_locally"] is False
    assert s["available_arches"] == ["amd64", "arm64"]
    assert s["multi_arch"] is True and s["arch"] is None
    assert s["source"] == "remote manifest"


def test_image_arch_status_remote_singlearch(monkeypatch):
    # A single-arch image: `--verbose` returns a JSON object, not a list.
    manifest = json.dumps(
        {"Descriptor": {"platform": {"architecture": "amd64", "os": "linux"}}})
    def handler(args):
        if args[:2] == ["image", "inspect"]:
            return None, "No such image"
        return manifest, None
    _patch_query(monkeypatch, handler)
    s = ex.image_arch_status("codalab/codalab-legacy:py39")
    assert s["available_arches"] == ["amd64"] and s["arch"] == "amd64"
    assert s["multi_arch"] is False


def test_image_arch_status_unavailable_tidies_error(monkeypatch):
    # Not local and not in any registry: multi-line auth errors collapse to one.
    def handler(args):
        if args[:2] == ["image", "inspect"]:
            return None, "No such image"
        return None, "errors:\n denied: requested access\n unauthorized: auth required"
    _patch_query(monkeypatch, handler)
    s = ex.image_arch_status("autocodabench/autocodabench-base-cpu:latest")
    assert s["arch"] is None and s["available_arches"] == []
    assert "\n" not in s["error"] and "denied" in s["error"]


# -- docker_preflight: native vs emulated fit ---------------------------------

def _patch_preflight(monkeypatch, *, host, daemon_arch, img):
    monkeypatch.setattr(ex, "_host_arch", lambda: host)
    monkeypatch.setattr(ex, "docker_daemon_status", lambda: {
        "cli_installed": True, "daemon_running": True,
        "os": "linux", "arch": daemon_arch, "server_version": "27.0"})
    monkeypatch.setattr(ex, "image_arch_status", lambda image: img)


def test_preflight_native_when_host_arch_available(monkeypatch):
    _patch_preflight(monkeypatch, host="arm64", daemon_arch="arm64", img={
        "present_locally": True, "arch": "arm64", "available_arches": ["arm64"],
        "multi_arch": False, "source": "local image", "error": None})
    p = ex.docker_preflight("local/img:1")
    assert p["ready"] is True
    assert p["runs_natively"] is True and p["emulated"] is False


def test_preflight_emulated_when_arch_mismatch(monkeypatch):
    _patch_preflight(monkeypatch, host="arm64", daemon_arch="arm64", img={
        "present_locally": False, "arch": "amd64", "available_arches": ["amd64"],
        "multi_arch": False, "source": "remote manifest", "error": None})
    p = ex.docker_preflight("codalab/codalab-legacy:py39")
    assert p["runs_natively"] is False and p["emulated"] is True


def test_preflight_multiarch_runs_natively(monkeypatch):
    _patch_preflight(monkeypatch, host="arm64", daemon_arch="arm64", img={
        "present_locally": False, "arch": None,
        "available_arches": ["amd64", "arm64"], "multi_arch": True,
        "source": "remote manifest", "error": None})
    p = ex.docker_preflight("codalab/codalab-legacy:py312")
    assert p["runs_natively"] is True and p["emulated"] is False


def test_preflight_unknown_when_arch_undetermined(monkeypatch):
    _patch_preflight(monkeypatch, host="arm64", daemon_arch="arm64", img={
        "present_locally": False, "arch": None, "available_arches": [],
        "multi_arch": False, "source": None, "error": "image not available"})
    p = ex.docker_preflight("private/img:1")
    assert p["runs_natively"] is None and p["emulated"] is None


def test_preflight_not_ready_without_daemon(monkeypatch):
    monkeypatch.setattr(ex, "_host_arch", lambda: "arm64")
    monkeypatch.setattr(ex, "docker_daemon_status", lambda: {
        "cli_installed": True, "daemon_running": False,
        "os": None, "arch": None, "server_version": None})
    p = ex.docker_preflight("any/img:1")
    assert p["ready"] is False and p["runs_natively"] is None
