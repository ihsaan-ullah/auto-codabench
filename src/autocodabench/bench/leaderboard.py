"""Fold contributed benchmark records into a leaderboard.

Contributors run a benchmark with a backbone and commit the resulting
``bench.results`` record under
``benchmark/<bench>/results/<backbone-tag>/<run-id>.json``. This module
discovers every such record, groups them by benchmark and backbone, averages
the headline metrics across runs, and renders the committed ``LEADERBOARD.md``.

It is pure data → data → markdown (no network, no LLM), so it is unit-tested
and runs in CI on merge. Records that fail ``results.validate`` are skipped
with a note rather than crashing the aggregation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import results

SCHEMA_VERSION = 1


def discover_results(benchmark_root: str | Path) -> list[Path]:
    """All contributed result JSONs under ``benchmark/*/results/**/*.json``."""
    root = Path(benchmark_root)
    return sorted(
        p for p in root.glob("*/results/**/*.json")
        if p.is_file() and p.name != ".gitkeep"
    )


def _backend_label(record: dict) -> str:
    b = record.get("backend") or {}
    if b.get("spec"):
        return b["spec"]
    name, model = b.get("name"), b.get("model")
    if name and model:
        return f"{name}:{model}"
    return name or model or b.get("endpoint_host") or "unknown"


def _mean(values: list) -> float | None:
    nums = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return sum(nums) / len(nums) if nums else None


def _rate(values: list) -> float | None:
    """Mean of booleans (treating None as absent)."""
    bools = [1.0 if v else 0.0 for v in values if isinstance(v, bool)]
    return sum(bools) / len(bools) if bools else None


def _group(records: list[dict], benchmark: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for r in records:
        if r.get("benchmark") != benchmark:
            continue
        groups.setdefault(_backend_label(r), []).append(r)
    return groups


def _create_rows(records: list[dict]) -> list[dict]:
    rows = []
    for backend, recs in _group(records, "create").items():
        ms = [r.get("metrics", {}) for r in recs]
        rows.append({
            "backend": backend,
            "runs": len(recs),
            "score_agreement_rate": _mean([m.get("score_agreement_rate") for m in ms]),
            "build_rate": _rate([m.get("bundle_builds") for m in ms]),
            "validate_ok_rate": _rate([m.get("validate_ok") for m in ms]),
            "competitions": sorted({r.get("competition") for r in recs if r.get("competition")}),
        })
    # Best score-agreement first; None sinks to the bottom.
    rows.sort(key=lambda x: (x["score_agreement_rate"] is None,
                             -(x["score_agreement_rate"] or 0.0)))
    return rows


def _judged_field(metrics: dict, field: str):
    tier = (metrics.get("tiers") or {}).get("judged")
    return tier.get(field) if isinstance(tier, dict) else None


def _validate_rows(records: list[dict]) -> list[dict]:
    rows = []
    for backend, recs in _group(records, "validate").items():
        ms = [r.get("metrics", {}) for r in recs]
        det = [(m.get("tiers") or {}).get("deterministic") or {} for m in ms]
        rows.append({
            "backend": backend,
            "runs": len(recs),
            "judged_recall": _mean([_judged_field(m, "recall") for m in ms]),
            "judged_precision": _mean([_judged_field(m, "precision") for m in ms]),
            "judged_f1": _mean([_judged_field(m, "f1") for m in ms]),
            "judged_clean_fp_rate": _mean([_judged_field(m, "clean_false_positive_rate") for m in ms]),
            "deterministic_recall": _mean([d.get("recall") for d in det]),
        })
    rows.sort(key=lambda x: (x["judged_f1"] is None, -(x["judged_f1"] or 0.0)))
    return rows


def aggregate(records: list[dict]) -> dict[str, Any]:
    """Group valid records by benchmark+backbone and average headline metrics."""
    valid, skipped = [], 0
    for r in records:
        if results.validate(r):
            skipped += 1
        else:
            valid.append(r)
    return {
        "schema_version": SCHEMA_VERSION,
        "n_records": len(valid),
        "n_skipped": skipped,
        "create": _create_rows(valid),
        "validate": _validate_rows(valid),
    }


def _fmt(x: Any) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.3f}"
    return str(x)


def render_markdown(agg: dict, *, generated_at: str | None = None) -> str:
    ts = generated_at or datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
    out = [
        "# autocodabench benchmark leaderboard",
        "",
        "_Aggregated from contributed runs under `benchmark/*/results/`. "
        "Regenerate with `python benchmark/scripts/aggregate.py`._",
        "",
        f"- generated: {ts}",
        f"- records aggregated: {agg.get('n_records', 0)}"
        + (f" ({agg['n_skipped']} skipped as invalid)" if agg.get("n_skipped") else ""),
        "",
        "## create-bench — proposal → working bundle",
        "",
        "Higher is better. *score agreement* = fraction of ground-truth "
        "submissions whose score through the generated bundle matched the "
        "reference within tolerance.",
        "",
        "| backbone | runs | score agreement | builds | validates | competitions |",
        "|----------|------|-----------------|--------|-----------|--------------|",
    ]
    for r in agg.get("create", []):
        out.append(
            f"| `{r['backend']}` | {r['runs']} | {_fmt(r['score_agreement_rate'])} "
            f"| {_fmt(r['build_rate'])} | {_fmt(r['validate_ok_rate'])} "
            f"| {', '.join(r['competitions']) or '—'} |")
    if not agg.get("create"):
        out.append("| _(no runs yet)_ | | | | | |")

    out += [
        "",
        "## validate-bench — defect catch rate (judged tier)",
        "",
        "Higher recall/precision/F1 is better; lower clean-FP is better. The "
        "deterministic tier is ~1.0 by construction (sanity baseline); the "
        "**judged** tier is the backbone-sensitive measurement.",
        "",
        "| backbone | runs | judged recall | judged precision | judged F1 | clean FP rate | det. recall |",
        "|----------|------|---------------|------------------|-----------|---------------|-------------|",
    ]
    for r in agg.get("validate", []):
        out.append(
            f"| `{r['backend']}` | {r['runs']} | {_fmt(r['judged_recall'])} "
            f"| {_fmt(r['judged_precision'])} | {_fmt(r['judged_f1'])} "
            f"| {_fmt(r['judged_clean_fp_rate'])} | {_fmt(r['deterministic_recall'])} |")
    if not agg.get("validate"):
        out.append("| _(no runs yet)_ | | | | | | |")
    out.append("")
    return "\n".join(out)
