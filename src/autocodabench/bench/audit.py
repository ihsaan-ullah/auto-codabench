"""Deterministic submission auditor.

Given the JSON a reformat-and-run session produced for one ground-truth
submission (``final``) and that submission's ``expected_result.json``
(``expected``), decide whether the bundle scored it correctly — i.e. within
the tolerance the competition author specified. This is **pure arithmetic**:
the original experiment harness ran it as an LLM subagent, but the work is
JSON parsing + a tolerance compare, so it lives here as plain Python (one
fewer model dependency, fully reproducible).

The orchestrator — never the reformat-and-run session — is what calls this,
and only it ever opens ``expected_result.json``. That keeps the data-leakage
boundary a code invariant: the model that adapts/scores the submission is
structurally blind to the target.
"""
from __future__ import annotations

from typing import Any

# Verdicts. ``pass``/``fail`` are score comparisons; the other two are
# upstream failures (the bundle produced no usable score at all).
PASS = "pass"
FAIL = "fail"
NO_SCORE = "no_score_produced"
METRIC_MISMATCH = "metric_mismatch"


def metric_key_for(expected: dict[str, Any]) -> str | None:
    """The key to read from the produced ``scores`` dict.

    ``primary_score_key`` wins when present (some bundles report several
    metrics); otherwise the human-facing ``metric`` name is used.
    """
    return expected.get("primary_score_key") or expected.get("metric")


def audit_submission(final: dict[str, Any], expected: dict[str, Any],
                     *, sub_label: str = "") -> dict[str, Any]:
    """Verdict one submission's reformat-and-run output against its target.

    ``final`` has the shape the reformat-and-run phase emits
    (``status``/``scores``/``stage_failed``/``error``/``attempts_used``/…).
    ``expected`` has at minimum ``{metric, score, tolerance}`` and optionally
    ``primary_score_key``. Returns a verdict dict (the same record the old
    ``verdict.json`` held).
    """
    scores = final.get("scores")
    status = final.get("status")
    key = metric_key_for(expected)

    verdict = {
        "sub": sub_label,
        "verdict": None,
        "within_tolerance": None,
        "metric_key": key,
        "actual_score": None,
        "expected_score": _maybe_float(expected.get("score")),
        "tolerance": _maybe_float(expected.get("tolerance")) or 0.0,
        "delta": None,
        "reformat_attempts_used": final.get("attempts_used"),
        "reformat_max_attempts": final.get("max_attempts"),
        "extras_installed": final.get("extras_installed") or [],
        "adapter_notes": final.get("adapter_notes") or [],
        "error_summary": None,
    }

    # 2a. No score produced upstream.
    if status == "fail" or scores is None:
        verdict["verdict"] = NO_SCORE
        verdict["error_summary"] = (
            final.get("error")
            or f"reformat-and-run produced no score (stage_failed="
               f"{final.get('stage_failed')})")
        return verdict

    # 2b. Metric mismatch — the expected key isn't in what the bundle reported.
    if not key or key not in scores:
        verdict["verdict"] = METRIC_MISMATCH
        verdict["within_tolerance"] = False
        verdict["error_summary"] = (
            f"bundle produced scores={sorted(scores.keys())}, "
            f"expected metric={key!r}")
        return verdict

    # 2c. Score available — compare within tolerance.
    actual = _maybe_float(scores.get(key))
    expected_score = verdict["expected_score"]
    tol = verdict["tolerance"]
    verdict["actual_score"] = actual
    if actual is None or expected_score is None:
        verdict["verdict"] = METRIC_MISMATCH
        verdict["within_tolerance"] = False
        verdict["error_summary"] = (
            f"non-numeric score (actual={scores.get(key)!r}, "
            f"expected={expected.get('score')!r})")
        return verdict
    delta = abs(actual - expected_score)
    within = delta <= tol
    verdict["delta"] = delta
    verdict["within_tolerance"] = within
    verdict["verdict"] = PASS if within else FAIL
    return verdict


def audit_status(verdict: dict[str, Any]) -> str:
    """Collapse a verdict to ``pass``/``fail`` — pass iff within tolerance."""
    return PASS if verdict.get("within_tolerance") is True else FAIL


def _maybe_float(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
