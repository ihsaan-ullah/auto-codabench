"""Aggregate check results into one report (dict and Markdown renderings).

The report preserves the three-status semantics of the check tiers rather
than collapsing them into one boolean: deterministic FAILs gate (``ok`` is
defined as their absence), judged FINDINGs advise, and
ATTESTATION_REQUIRED items surface as explicit unchecked boxes. Erasing
those distinctions here would undo the epistemic separation the check
framework exists to maintain.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import REGISTRY, CheckResult, Status, Tier
from .facts import CompetitionFacts


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

    def to_markdown(self) -> str:
        lines: list[str] = []
        verdict = "✅ PASS" if self.ok else "❌ FAIL"
        lines.append(f"# Bundle validation — {verdict}")
        lines.append("")
        lines.append(f"Bundle: `{self.bundle_dir}`")
        counts = self.counts
        lines.append("Results: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
        lines.append("")

        # Execution summary — "what ran, on what data, from which phase, for how
        # long, under which condition" — rendered up front when runs happened.
        ex_rows = self.execution_results
        if ex_rows:
            lines.append("## Execution")
            lines.append("_The bundle was run, not just inspected. Each row is a "
                         "real ingestion+scoring or notebook run in the declared "
                         "Docker image._")
            lines.append("")
            for r in ex_rows:
                mark = {"pass": "✓", "fail": "✗", "finding": "⚠",
                        "skipped": "•"}.get(r.status.value, "·")
                lines.append(f"- {mark} **[{r.check_id}]** {r.message}")
                for sub in _detail_lines(r.details):
                    lines.append(f"    - {sub}")
            lines.append("")

        def section(title: str, rows: list[CheckResult], note: str | None = None) -> None:
            if not rows:
                return
            lines.append(f"## {title}")
            if note:
                lines.append(f"_{note}_")
            lines.append("")
            for r in rows:
                where = f" `{r.where}`" if r.where else ""
                cite = f" — {r.citation}" if r.citation else ""
                lines.append(f"- **[{r.check_id}]**{where} {r.message}{cite}")
            lines.append("")

        section("Gate failures", self.by_status(Status.FAIL),
                "Deterministic checks that block upload — fix these.")
        section("Findings (advisory)", self.by_status(Status.FINDING),
                "Design risks and LLM-judged observations. They do not gate, "
                "but each one is a known failure mode with a citation.")
        section("Attestations required", self.by_status(Status.ATTESTATION_REQUIRED),
                "Only a human can certify these. Unchecked ≠ done.")
        section("Skipped", self.by_status(Status.SKIPPED),
                "Checks that need declared facts or were inapplicable.")
        section("Passed", self.by_status(Status.PASS))
        return "\n".join(lines)


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


def checklist_coverage() -> list[dict[str, str]]:
    """The implemented-check inventory: id, tier, title, citation.

    This is the docs/paper 'checklist coverage' table — what the validator
    actually covers, by tier, with sources.
    """
    return [
        {
            "id": c.id,
            "tier": c.tier.value,
            "title": c.title,
            "citation": c.citation or "",
        }
        for c in sorted(REGISTRY.values(), key=lambda c: (c.tier.value, c.id))
    ]
