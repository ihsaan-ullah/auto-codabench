"""Render a human ``run_report.md`` from a benchmark result record.

The result JSON (see :mod:`.results`) is the machine-readable artifact; this
is its readable companion — a single page a reviewer can scan to see whether
a backbone authored a working bundle and reproduced the ground-truth scores.
Defensive ``.get`` access throughout so a partial run (e.g. build failed
before scoring) still renders.
"""
from __future__ import annotations

from typing import Any


def _fmt(x: Any, nd: int = 4) -> str:
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return "—" if x is None else str(x)


def _yn(x: Any) -> str:
    return "—" if x is None else ("yes" if x else "no")


def render_run_report(result: dict[str, Any]) -> str:
    m = result.get("metrics", {}) or {}
    be = result.get("backend", {}) or {}
    ex = m.get("execution", {}) or {}
    subs = m.get("submissions", []) or []
    mi = m.get("missing_info_totals", {}) or {}

    L: list[str] = []
    L.append(f"# Create-bench run report — {result.get('competition', '?')}")
    L.append("")
    L.append(f"- **backend**: `{be.get('spec') or be.get('name')}`"
             f"  (model `{be.get('model')}`"
             + (f", host `{be['endpoint_host']}`" if be.get("endpoint_host") else "")
             + ")")
    L.append(f"- **run_id**: {result.get('run_id')}")
    L.append(f"- **generated_at**: {result.get('generated_at')}")
    L.append(f"- **autocodabench**: {result.get('autocodabench_version')}"
             f"  ·  git `{result.get('git_sha')}`")
    if result.get("cost_usd") is not None:
        L.append(f"- **cost**: ${result['cost_usd']:.2f}  ·  turns {result.get('turns')}")
    L.append("")

    # Pipeline outcomes.
    L.append("## Pipeline")
    L.append("")
    L.append("| stage | outcome |")
    L.append("|-------|---------|")
    L.append(f"| plan | {_yn(m.get('plan_ok'))}"
             f" ({_fmt(m.get('plan_sections_covered'))} / 7 sections) |")
    L.append(f"| build (bundle produced) | {_yn(m.get('bundle_builds'))} |")
    L.append(f"| validate (no gate failures) | {_yn(m.get('validate_ok'))} |")
    L.append(f"| baseline executes | {_yn(ex.get('baseline_pass'))}"
             f" (attempts {_fmt(ex.get('baseline_attempts'))}) |")
    L.append(f"| starting-kit notebook | {_yn(ex.get('notebook_pass'))}"
             f" (attempts {_fmt(ex.get('notebook_attempts'))}) |")
    L.append("")

    # Score fidelity — the headline of create-bench.
    L.append("## Score fidelity (ground-truth submissions)")
    L.append("")
    if subs:
        L.append("| sub | reformat | verdict | expected | actual | Δ | within tol |")
        L.append("|-----|----------|---------|----------|--------|---|------------|")
        for s in subs:
            L.append(
                f"| {s.get('sub')} | {s.get('reformat_status')}"
                f" ({_fmt(s.get('reformat_attempts'))}) | {s.get('verdict')}"
                f" | {_fmt(s.get('expected'))} | {_fmt(s.get('actual'))}"
                f" | {_fmt(s.get('delta'))} | {_yn(s.get('within_tolerance'))} |")
        rate = m.get("score_agreement_rate")
        L.append("")
        L.append(f"**Score-agreement rate**: {_fmt(rate, 3)}"
                 f"  ({sum(1 for s in subs if s.get('within_tolerance'))}/{len(subs)}"
                 " within tolerance)")
    else:
        L.append("_No submissions scored (build/validate did not reach scoring)._")
    L.append("")

    # Missing-info summary.
    if mi:
        L.append("## Missing-information inventory")
        L.append("")
        L.append(f"- total items: {mi.get('total_items', '—')}")
        for k in ("by_severity", "by_impact_area", "by_resolution_action"):
            if mi.get(k):
                pairs = ", ".join(f"{kk}={vv}" for kk, vv in mi[k].items())
                L.append(f"- {k.replace('by_', '').replace('_', ' ')}: {pairs}")
        hs = mi.get("high_stakes_inferences") or []
        L.append(f"- high-stakes inferences (could change scoring): {len(hs)}")
        L.append("")

    return "\n".join(L) + "\n"
