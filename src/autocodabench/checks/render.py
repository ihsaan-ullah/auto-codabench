"""Markdown rendering for a :class:`ValidationReport` + the Phase-1 design
scorecard.

Shared by the CLI (`autocodabench validate`) and the web UI so both surfaces
produce the *same* report: colorful status tables, the execution evidence
section, and — when a Phase-1 ``design_assessment.json`` is available — the
7-section design scorecard. Keeping this in the package (not the web app)
means the feature is global; the web layer only does Chainlit presentation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import Status
from .report import ValidationReport, _detail_lines

# Check status (Status enum value) → emoji.
STATUS_EMOJI = {
    "pass": "✅", "fail": "❌", "finding": "⚠️",
    "attestation_required": "📋", "skipped": "•",
}
# Phase-1 design-assessment status → emoji.
ASSESS_EMOJI = {"ok": "✅", "warn": "⚠️", "missing": "❌"}


def _cell(text: Any) -> str:
    """Sanitise a value for a markdown table cell."""
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def load_design_assessment(source: str | Path | None) -> dict | None:
    """Load + validate a ``design_assessment.json`` from a file or a directory.

    ``source`` may be the JSON file itself, or a directory in which case both
    ``<dir>/design_assessment.json`` and ``<dir>/specs/design_assessment.json``
    are tried. Returns ``None`` if absent or malformed — callers degrade
    gracefully (the design table is simply omitted), never crash.
    """
    if source is None:
        return None
    p = Path(source)
    candidates = [p] if p.is_file() else [
        p / "design_assessment.json",
        p / "specs" / "design_assessment.json",
    ]
    for c in candidates:
        if not c.is_file():
            continue
        try:
            data = json.loads(c.read_text(encoding="utf-8"))
            if int(data.get("schema_version", 0)) != 1:
                return None
            secs = data.get("sections")
            if not isinstance(secs, list) or not secs:
                return None
            if not all(isinstance(s, dict) and s.get("name") and s.get("status")
                       for s in secs):
                return None
            return data
        except Exception:
            return None
    return None


def render_design_table(assessment: dict) -> str:
    """Table A — the Phase-1 7-section design scorecard."""
    rows = "\n".join(
        f"| {_cell(s.get('name'))} "
        f"| {ASSESS_EMOJI.get(str(s.get('status')).lower(), '•')} "
        f"| {_cell(s.get('note'))} |"
        for s in assessment.get("sections", [])
    )
    return ("## 📐 Design assessment (Phase 1)\n\n"
            "| Design section | Status | Note |\n|---|:--:|---|\n" + rows)


def render_checks_table(report: ValidationReport) -> str:
    """Table B — every check result with a status emoji and citation."""
    rows = []
    for r in report.results:
        detail = _cell(r.message)
        if r.citation:
            detail += f" — {_cell(r.citation)}"
        rows.append(
            f"| {STATUS_EMOJI.get(r.status.value, '•')} | {_cell(r.check_id)} "
            f"| {_cell(r.where)} | {detail} |"
        )
    body = "\n".join(rows) if rows else "| • | — | — | no checks ran |"
    return ("## 🔎 Checks\n\n"
            "| Status | Check | Where | Detail |\n|:--:|---|---|---|\n" + body)


def render_execution_section(report: ValidationReport) -> str | None:
    """The execution-evidence section (what ran, on what, how long), or None."""
    ex = report.execution_results
    if not ex:
        return None
    lines = [
        "## ▶ Execution",
        "_The bundle was run, not just inspected — real ingestion+scoring or "
        "notebook runs in the declared Docker image._",
        "",
    ]
    for r in ex:
        mark = STATUS_EMOJI.get(r.status.value, "·")
        lines.append(f"- {mark} **[{r.check_id}]** {_cell(r.message)}")
        for sub in _detail_lines(r.details):
            lines.append(f"    - {sub}")
    return "\n".join(lines)


def render_judged_section(report: ValidationReport) -> str:
    """Render only the LLM-judged advisory findings of a report."""
    findings = report.by_status(Status.FINDING)
    if not findings:
        return ("## ✨ LLM-judged findings\n\n"
                "✅ The judge found no contradictions between the pages and "
                "`competition.yaml`.")
    rows = "\n".join(
        f"| ⚠️ | {_cell(f.check_id)} | {_cell(f.where)} | {_cell(f.message)} |"
        for f in findings
    )
    return ("## ✨ LLM-judged findings (advisory)\n\n"
            "| | Check | Where | Finding |\n|:--:|---|---|---|\n" + rows)


def render_report_markdown(report: ValidationReport, *,
                           design_assessment: dict | None = None) -> str:
    """The full report: verdict, gate failures, design scorecard (if any),
    execution evidence, and the checks table. Shared by CLI + web."""
    verdict = "✅ PASS" if report.ok else "❌ FAIL"
    parts = [
        f"# Bundle validation — {verdict}",
        "",
        f"Bundle: `{report.bundle_dir}`",
        "Results: " + ", ".join(f"{v} {k}" for k, v in sorted(report.counts.items())),
    ]
    fails = report.by_status(Status.FAIL)
    if fails:
        parts.append("")
        parts.append("**Gate failures (fix before upload):**")
        parts += [f"- ❌ **[{_cell(r.check_id)}]** {_cell(r.message)}" for r in fails]
    if design_assessment:
        parts += ["", render_design_table(design_assessment)]
    ex = render_execution_section(report)
    if ex:
        parts += ["", ex]
    parts += ["", render_checks_table(report)]
    return "\n".join(parts)
