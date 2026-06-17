"""Keyless tests for the arch/emulation guard and the image override.

`autocodabench validate` defaults to executing the bundle in its declared image.
When that image is foreign to the host (amd64 image on an arm64 Mac) it would run
under QEMU emulation — a >20-minute run that previously started silently and read
as a freeze. These guard the honest behaviour: refuse by default, recommend a
native image, and let the user force or override. All pure functions — no Docker.
"""
from __future__ import annotations

from autocodabench.runner import execution as ex


def _pf(emulated, *, host="arm64", image="some/img:amd64", arches=("amd64",)):
    return {"emulated": emulated,
            "runs_natively": (None if emulated is None else not emulated),
            "host_arch": host, "image": image,
            "image_arch": "amd64", "image_available_arches": list(arches)}


def test_no_guidance_when_native_or_unknown():
    assert ex.emulation_guidance(_pf(False)) is None
    assert ex.emulation_guidance(_pf(None)) is None


def test_guidance_when_emulated_is_honest_and_actionable():
    msg = ex.emulation_guidance(_pf(True))
    assert msg is not None
    # honest about the cost…
    assert "20 min" in msg or "20 minutes" in msg
    assert "emulation" in msg.lower() and "skipped" in msg.lower()
    # …and every escape hatch is named.
    assert "AUTOCODABENCH_DOCKER_IMAGE_OVERRIDE" in msg
    assert "--no-execute" in msg
    assert "AUTOCODABENCH_ALLOW_EMULATION" in msg


def test_emulation_allowed_reads_env(monkeypatch):
    monkeypatch.delenv("AUTOCODABENCH_ALLOW_EMULATION", raising=False)
    assert ex.emulation_allowed() is False
    for truthy in ("1", "true", "YES", "on"):
        monkeypatch.setenv("AUTOCODABENCH_ALLOW_EMULATION", truthy)
        assert ex.emulation_allowed() is True
    monkeypatch.setenv("AUTOCODABENCH_ALLOW_EMULATION", "0")
    assert ex.emulation_allowed() is False


def test_image_override_wins_over_declared(monkeypatch, tmp_path):
    # A bundle that declares its own image…
    (tmp_path / "bundle").mkdir()
    (tmp_path / "bundle" / "competition.yaml").write_text(
        "docker_image: declared/image:amd64\n", encoding="utf-8")
    monkeypatch.delenv("AUTOCODABENCH_DOCKER_IMAGE_OVERRIDE", raising=False)
    assert ex.bundle_docker_image("bundle", str(tmp_path)) == "declared/image:amd64"
    assert ex.docker_image_overridden() is None
    # …is overridden by the explicit env, which wins.
    monkeypatch.setenv("AUTOCODABENCH_DOCKER_IMAGE_OVERRIDE", "native/image:py312")
    assert ex.bundle_docker_image("bundle", str(tmp_path)) == "native/image:py312"
    assert ex.docker_image_overridden() == "native/image:py312"


def test_check_skips_emulated_run_without_executing(monkeypatch):
    """The execution check returns SKIPPED (not a started run) when the image
    emulates and the user has not opted in."""
    from autocodabench.checks import execution as exe

    class _FakeEx:
        @staticmethod
        def emulation_allowed():
            return False

        @staticmethod
        def docker_preflight(image):
            return _pf(True)

        @staticmethod
        def emulation_guidance(pf):
            return ex.emulation_guidance(pf)

        @staticmethod
        def bundle_docker_image(slug, root):
            return "some/img:amd64"

    msg = exe._emulation_skip(_FakeEx(), "some/img:amd64")
    assert msg is not None and "AUTOCODABENCH_DOCKER_IMAGE_OVERRIDE" in msg

    class _AllowEx(_FakeEx):
        @staticmethod
        def emulation_allowed():
            return True

    assert exe._emulation_skip(_AllowEx(), "some/img:amd64") is None


def _patch_tty(monkeypatch, answer):
    import sys as _sys
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(_sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda *a, **k: answer)


def test_validate_prompts_and_proceeds_on_yes(monkeypatch):
    from autocodabench.cli import main as M
    monkeypatch.delenv("AUTOCODABENCH_ALLOW_EMULATION", raising=False)
    _patch_tty(monkeypatch, "y")
    M._maybe_prompt_emulation(_pf(True), execute=True)
    assert ex.emulation_allowed() is True  # opted in for this process


def test_validate_prompts_and_skips_on_no(monkeypatch):
    from autocodabench.cli import main as M
    monkeypatch.delenv("AUTOCODABENCH_ALLOW_EMULATION", raising=False)
    _patch_tty(monkeypatch, "n")
    M._maybe_prompt_emulation(_pf(True), execute=True)
    assert ex.emulation_allowed() is False


def test_validate_no_prompt_when_native_or_static(monkeypatch):
    from autocodabench.cli import main as M
    monkeypatch.delenv("AUTOCODABENCH_ALLOW_EMULATION", raising=False)
    called = {"n": 0}
    monkeypatch.setattr("builtins.input", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    M._maybe_prompt_emulation(_pf(False), execute=True)   # native image
    M._maybe_prompt_emulation(_pf(True), execute=False)   # --no-execute
    assert called["n"] == 0  # never prompted
