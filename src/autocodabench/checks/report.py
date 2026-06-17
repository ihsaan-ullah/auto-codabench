"""Aggregate check results into one report (dict and Markdown renderings).

The report preserves the three-status semantics of the check tiers rather
than collapsing them into one boolean: deterministic FAILs gate (``ok`` is
defined as their absence), judged FINDINGs advise, and
ATTESTATION_REQUIRED items surface as explicit unchecked boxes. Erasing
those distinctions here would undo the epistemic separation the check
framework exists to maintain.
"""
from __future__ import annotations

import inspect
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import REGISTRY, CheckResult, Status, Tier, tier_is_llm_judged
from .facts import CompetitionFacts

# Canonical sources behind the check citations, made clickable wherever a
# citation is shown. The book PDF is the project's hosted copy (same URL the
# authoring skills cite); the schema points at the Codabench docs.
_BOOK_URL = "https://ai-competitions-book.github.io/ai-competitions-book-full-project.pdf"
_CODABENCH_DOCS_URL = "https://github.com/codalab/codabench/tree/develop/documentation"


def citation_url(citation: str | None) -> str | None:
    """Map a citation string to a clickable source URL (or None)."""
    if not citation:
        return None
    c = citation.lower()
    if "pavão" in c or "pavao" in c:
        return _BOOK_URL
    if "codabench" in c or "schema" in c or "yaml-structure" in c:
        return _CODABENCH_DOCS_URL
    return None


@dataclass
class ValidationReport:
    bundle_dir: Path
    results: list[CheckResult]
    facts: CompetitionFacts = field(default_factory=CompetitionFacts)

    @property
    def ok(self) -> bool:
        """True iff no deterministic gate failed. Findings and pending
        attestations do not gate — they inform."""
        return not any(r.status == Status.FAIL for r in self.results)

    @property
    def counts(self) -> dict[str, int]:
        return dict(Counter(r.status.value for r in self.results))

    def by_status(self, *statuses: Status) -> list[CheckResult]:
        return [r for r in self.results if r.status in statuses]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_dir": str(self.bundle_dir),
            "ok": self.ok,
            "counts": self.counts,
            "facts": self.facts.to_dict(),
            "results": [r.to_dict() for r in self.results],
        }

    @property
    def execution_results(self) -> list[CheckResult]:
        """Results carrying execution evidence (a run was performed or reused)."""
        return [r for r in self.results if r.details is not None]

    def to_markdown(self, *, design_assessment: dict | None = None) -> str:
        """Render the report as markdown (status tables + execution evidence).

        Delegates to :mod:`autocodabench.checks.render` so the CLI and the web
        UI render identically. Pass ``design_assessment`` (a parsed
        ``design_assessment.json``) to prepend the Phase-1 design scorecard.
        """
        from .render import render_report_markdown
        return render_report_markdown(self, design_assessment=design_assessment)


def _detail_lines(details: dict[str, Any] | None) -> list[str]:
    """Render an execution check's structured evidence as a few bullet lines:
    provenance (executed now vs reused), the image and arch fit, duration,
    scores, and the data consumed."""
    if not details:
        return []
    out: list[str] = []

    src = details.get("source")
    phase = details.get("phase")
    if src == "reused":
        when = f" (run at {details['ran_at']})" if details.get("ran_at") else ""
        out.append(f"source: reused from the **{phase}** phase{when} — not re-run "
                   "(bundle unchanged since)")
    elif src == "executed":
        out.append(f"source: executed now (in the **{phase or 'validate'}** phase)")

    img = details.get("docker_image")
    if img:
        fit = ""
        emulated = details.get("emulated")
        host, iarch = details.get("host_arch"), details.get("image_arch")
        if emulated is True:
            fit = f" — ⚠ {iarch or '?'} under QEMU emulation on {host or '?'} (slow)"
        elif emulated is False:
            fit = f" — runs natively on {host or '?'}"
        out.append(f"condition: image `{img}`{fit}")

    dur = details.get("duration_s")
    if isinstance(dur, (int, float)):
        out.append(f"duration: {dur:.1f}s")

    scores = details.get("scores")
    if isinstance(scores, dict) and scores:
        rendered = ", ".join(f"{k}={v}" for k, v in list(scores.items())[:6])
        out.append(f"scores: {rendered}")
    cells = details.get("cells_executed")
    if isinstance(cells, int):
        out.append(f"cells executed: {cells}")

    data = details.get("data")
    if isinstance(data, dict):
        bits = []
        ref = data.get("reference_data")
        if ref:
            bits.append(f"reference_data: {len(ref)} file(s)")
        if data.get("input_data_present"):
            bits.append("input_data ✓")
        if data.get("public_data_present"):
            bits.append("public_data ✓")
        if bits:
            out.append("data: " + ", ".join(bits))

    logs = details.get("logs_dir")
    if logs:
        out.append(f"logs: `{logs}`")
    return out


def checklist_coverage() -> list[dict[str, Any]]:
    """The implemented-check inventory, grouped/ordered by validation *type*.

    Each row carries everything the user-facing tables need: the type (number +
    label), a user-friendly title, whether an LLM is involved
    (``llm_judged``), how the check is performed (``how``), and the citation
    with its clickable URL. The internal ``id`` and ``tier`` are kept for
    tooling but are not shown to users.
    """
    return [
        {
            "id": c.id,
            "tier": c.tier.value,
            "llm_judged": tier_is_llm_judged(c.tier),
            "type_no": c.dimension.number,
            "type": c.dimension.label,
            "title": c.title,
            "description": _check_description(c),
            "how": c.how or "",
            "citation": c.citation or "",
            "citation_url": citation_url(c.citation),
        }
        for c in sorted(REGISTRY.values(),
                        key=lambda c: (c.dimension.number, not tier_is_llm_judged(c.tier), c.id))
    ]


def _check_description(check) -> str:
    """A one-line, user-facing description of what the check verifies, taken
    from the check class's docstring (first paragraph)."""
    doc = inspect.getdoc(type(check)) or ""
    first = doc.split("\n\n", 1)[0].replace("\n", " ").strip()
    return first[:200].rstrip() + ("…" if len(first) > 200 else "")
