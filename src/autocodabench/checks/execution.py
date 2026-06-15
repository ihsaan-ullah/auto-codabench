"""Execution checks — run the bundle, don't just read it.

These are deterministic checks (code computes the verdict) that go beyond
inspecting ``competition.yaml``: they stage the Codabench sandbox and run the
bundle's own baseline through ingestion+scoring, and execute its starting-kit
notebook, inside the declared ``docker_image`` — exactly as the platform
worker will. A pre-launch report that says "the scoring pipeline produced a
score on real data, in this image, in this long" is qualitatively stronger
evidence than "the YAML references a file that exists".

They run only when the validation was asked to *execute*
(``CheckContext.execute``) — a plain ``validate-bundle`` without Docker, and
the keyless unit suite, never trigger them. When execution *is* requested but
no Docker daemon is reachable, each returns SKIPPED with the reason rather
than a misleading pass or a spurious gate.

To avoid paying for a run twice, an execution check first consults the
bundle-adjacent execution cache: if the build phase (or a previous
``validate``) already ran this exact bundle (same content hash) successfully,
the recorded result is reused and labelled as such. Editing the bundle
between phases changes the hash and forces a fresh run.

Epistemic split: a baseline that cannot produce a score is a reproducible
defect in the scoring path, so ``baseline-execution`` *gates* (FAIL). A
starting-kit notebook that errors degrades participant onboarding but does not
break scoring, so ``starting-kit-execution`` only *advises* (FINDING).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Check, CheckContext, CheckResult, Severity, Status, register


def _arch_fit(ex, image: str | None) -> dict[str, Any]:
    """Best-effort host/image architecture fit ('under which condition')."""
    if not image:
        return {}
    try:
        p = ex.docker_preflight(image)
    except Exception:
        return {}
    return {
        "host_arch": p.get("host_arch"),
        "image_arch": p.get("image_arch"),
        "image_available_arches": p.get("image_available_arches"),
        "emulated": p.get("emulated"),
    }


def _has_baseline(bundle_dir: Path) -> bool:
    sol = bundle_dir / "solutions"
    if sol.is_dir() and any(p.is_dir() for p in sol.iterdir()):
        return True
    return (bundle_dir / "solution" / "sample_code_submission").is_dir()


def _find_notebook(bundle_dir: Path) -> Path | None:
    candidates: list[Path] = [bundle_dir / "README.ipynb"]
    kit = bundle_dir / "starting_kit"
    if kit.is_dir():
        candidates.extend(sorted(kit.glob("*.ipynb")))
    return next((c for c in candidates if c.is_file()), None)


@register
class BaselineExecution(Check):
    """Run the bundle's own baseline through the scoring pipeline, in Docker.

    The strongest pre-launch signal there is: the metric plumbing actually
    produces a score on real (toy) data, in the image the platform will use.
    Reused from the build phase when the bundle is unchanged.
    """

    id = "baseline-execution"
    title = "Baseline runs end-to-end through scoring (in Docker)"
    severity = Severity.BLOCKER
    citation = "Pavão et al. (Ch. 5, Ch. 11)"
    requires_execution = True

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        from ..runner import execution as ex

        if not _has_baseline(ctx.bundle_dir):
            return [self.finding(
                "no baseline submission under solutions/ to execute — the scoring "
                "pipeline cannot be verified end-to-end on real data",
                where="solutions/")]

        eng = ex.resolve_execution_engine("auto")
        if eng.get("error"):
            return [self.skipped(
                "execution requested but no run was performed — " + eng["error"])]

        slug, root = ctx.bundle_dir.name, ctx.root_dir
        cur_hash = ex.bundle_content_hash(ctx.bundle_dir)
        cached = ex.cached_run(ctx.bundle_dir, "baseline", cur_hash)
        if cached:
            details = self._cache_details(ex, cached)
            return [self._details(
                Status.PASS,
                f"baseline was verified in the {cached.get('phase', 'build')} phase "
                "and the bundle is unchanged since — reusing that run; a score was "
                f"produced ({_scores_str(cached.get('scores'))})",
                details, where="solutions/")]

        res = ex.run_baseline_submission(slug, root_dir=root)
        details = self._run_details(ex, res, ok=res.get("ok", False))
        if res.get("ok"):
            return [self._details(
                Status.PASS,
                "baseline ran through ingestion+scoring and produced a score "
                f"({_scores_str(res.get('scores'))}) in "
                f"{_dur(res.get('duration_s'))}",
                details, where="solutions/")]
        return [self._details(
            Status.FAIL,
            "baseline did not produce a score — the scoring pipeline is broken: "
            + (res.get("error") or "unknown error"),
            details, where="solutions/")]

    def _run_details(self, ex, res: dict, *, ok: bool) -> dict[str, Any]:
        image = res.get("docker_image")
        return {
            "source": "executed", "phase": "validate", "ok": ok,
            "docker_image": image, "stage": res.get("stage"),
            "duration_s": res.get("duration_s"),
            "scores": res.get("scores"), "data": res.get("data"),
            "logs_dir": res.get("logs_dir"),
            **_arch_fit(ex, image),
        }

    def _cache_details(self, ex, entry: dict) -> dict[str, Any]:
        image = entry.get("docker_image")
        return {
            "source": "reused", "phase": entry.get("phase", "build"), "ok": True,
            "docker_image": image, "stage": entry.get("stage"),
            "duration_s": entry.get("duration_s"),
            "scores": entry.get("scores"), "data": entry.get("data"),
            "logs_dir": entry.get("logs_dir"), "ran_at": entry.get("timestamp"),
            **_arch_fit(ex, image),
        }


@register
class StartingKitExecution(Check):
    """Execute the starting-kit notebook end-to-end inside the bundle's image.

    A starting kit that errors on a clean machine is the single biggest silent
    drag on participation. Advisory, not a gate — it is onboarding, not the
    scoring path. Reused from the build phase when the bundle is unchanged.
    """

    id = "starting-kit-execution"
    title = "Starting-kit notebook executes cleanly (in Docker)"
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 5, Ch. 13)"
    requires_execution = True

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        from ..runner import execution as ex

        nb = _find_notebook(ctx.bundle_dir)
        if nb is None:
            return [self.skipped(
                "no starting-kit notebook to execute (README.ipynb / "
                "starting_kit/*.ipynb) — see the starting-kit check")]

        eng = ex.resolve_execution_engine("auto")
        if eng.get("error"):
            return [self.skipped(
                "execution requested but no run was performed — " + eng["error"])]

        slug, root = ctx.bundle_dir.name, ctx.root_dir
        cur_hash = ex.bundle_content_hash(ctx.bundle_dir)
        cached = ex.cached_run(ctx.bundle_dir, "starting_kit", cur_hash)
        if cached:
            return [self._details(
                Status.PASS,
                f"starting-kit notebook was executed in the {cached.get('phase', 'build')} "
                "phase and the bundle is unchanged since — reusing that run "
                f"({_cells(cached.get('cells_executed'))} executed)",
                self._cache_details(ex, cached), where=_rel(ctx, nb))]

        res = ex.run_starting_kit(slug, root_dir=root)
        image = res.get("docker_image")
        details = {
            "source": "executed", "phase": "validate", "ok": res.get("ok", False),
            "docker_image": image, "duration_s": res.get("duration_s"),
            "cells_executed": res.get("cells_executed"),
            "logs_dir": res.get("logs_dir"),
            **_arch_fit(ex, image),
        }
        if res.get("ok"):
            return [self._details(
                Status.PASS,
                f"starting-kit notebook executed cleanly ({_cells(res.get('cells_executed'))} "
                f"executed) in {_dur(res.get('duration_s'))}",
                details, where=_rel(ctx, nb))]
        return [self._details(
            Status.FINDING,
            "starting-kit notebook failed to execute — participants will hit the "
            "same error: " + (res.get("error") or "unknown error"),
            details, where=_rel(ctx, nb))]

    def _cache_details(self, ex, entry: dict) -> dict[str, Any]:
        image = entry.get("docker_image")
        return {
            "source": "reused", "phase": entry.get("phase", "build"), "ok": True,
            "docker_image": image, "duration_s": entry.get("duration_s"),
            "cells_executed": entry.get("cells_executed"),
            "logs_dir": entry.get("logs_dir"), "ran_at": entry.get("timestamp"),
            **_arch_fit(ex, image),
        }


# --- small formatting helpers ---------------------------------------------

def _rel(ctx: CheckContext, p: Path) -> str:
    try:
        return str(p.relative_to(ctx.bundle_dir))
    except ValueError:
        return p.name


def _scores_str(scores: Any) -> str:
    if not isinstance(scores, dict) or not scores:
        return "scores produced"
    parts = []
    for k, v in list(scores.items())[:4]:
        parts.append(f"{k}={v}")
    return ", ".join(parts)


def _dur(seconds: Any) -> str:
    if not isinstance(seconds, (int, float)):
        return "unknown time"
    return f"{seconds:.1f}s"


def _cells(n: Any) -> str:
    return f"{n} cells" if isinstance(n, int) else "notebook"
