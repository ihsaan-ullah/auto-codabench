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

import re
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


def _normalize_metric(name: Any) -> str:
    """Canonicalize a metric name for tolerant matching.

    Lowercase, drop every non-alphanumeric character, and strip a trailing
    ``metric`` token — so ``geometric_mean_accuracy_metric`` (a ground-truth
    name) and ``geometric_mean_accuracy`` (what a freshly generated bundle
    tends to emit) collapse to the same key.
    """
    s = re.sub(r"[^a-z0-9]+", "", str(name).lower())
    if s.endswith("metric") and len(s) > len("metric"):
        s = s[: -len("metric")]
    return s


def resolve_score(scores: dict[str, Any], expected: dict[str, Any]
                  ) -> tuple[str | None, Any, str | None]:
    """Find the produced score to compare against the expected metric.

    Measuring score *fidelity* means asking whether the bundle reproduced the
    number — not whether it happened to name its leaderboard column exactly the
    way the reference bundle did (a freshly generated bundle almost never will).
    So matching is tiered, most-specific first, and the chosen tier is reported:

    1. ``exact`` — the ``primary_score_key`` or ``metric`` name is a key as-is.
    2. ``normalized`` — a produced key matches the expected ``metric`` after
       :func:`_normalize_metric` (suffix/punctuation/case-insensitive).
    3. ``sole`` — the bundle reported exactly one numeric score; use it.

    Returns ``(key, value, match)``; ``(None, None, None)`` if nothing matched.
    """
    if not isinstance(scores, dict) or not scores:
        return None, None, None
    for cand in (expected.get("primary_score_key"), expected.get("metric")):
        if cand and cand in scores:
            return cand, scores[cand], "exact"
    want = _normalize_metric(expected.get("metric") or expected.get("primary_score_key") or "")
    if want:
        for k, v in scores.items():
            if _normalize_metric(k) == want:
                return k, v, "normalized"
    numeric = {k: v for k, v in scores.items() if _maybe_float(v) is not None}
    if len(numeric) == 1:
        (k, v), = numeric.items()
        return k, v, "sole"
    return None, None, None


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

    verdict = {
        "sub": sub_label,
        "verdict": None,
        "within_tolerance": None,
        "metric_key": metric_key_for(expected),
        "metric_match": None,         # exact | normalized | sole — how the key was resolved
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

    # 2b. Metric mismatch — no produced score maps to the expected metric
    # (after exact → normalized-name → sole-numeric matching).
    key, raw_actual, match = resolve_score(scores, expected)
    if key is None:
        verdict["verdict"] = METRIC_MISMATCH
        verdict["within_tolerance"] = False
        verdict["error_summary"] = (
            f"bundle produced scores={sorted(scores.keys())}, "
            f"expected metric={metric_key_for(expected)!r}")
        return verdict
    verdict["metric_key"] = key
    verdict["metric_match"] = match

    # 2c. Score available — compare within tolerance.
    actual = _maybe_float(raw_actual)
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
