"""The Check contract: one validation concern, one registered component.

Three tiers, three different epistemic standings — never conflated:

- ``DETERMINISTIC`` — code computes the verdict. PASS/FAIL gate.
- ``JUDGED`` — an LLM grades a rubric. Emits advisory FINDINGs, never gates.
- ``ATTESTATION`` — only a human can know (external review happened, legal
  signed off). Surfaced as an unchecked box in the report, never silently
  assumed.

Every check cites its source (a Pavão et al. chapter handle or the
Codabench schema), so each line of the report is a cited claim.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .facts import CompetitionFacts


class Tier(str, enum.Enum):
    DETERMINISTIC = "deterministic"
    JUDGED = "judged"
    ATTESTATION = "attestation"


class Dimension(str, enum.Enum):
    """The *type* of correctness a check inspects — the orthogonal axis to the
    tier. The report groups checks by type so an organizer reads them by what
    they concern. The six types are numbered for display (``1. Structural`` …
    ``6. Governance``); see ``docs/validation-checklist-proposal.md`` (§2).
    """
    STRUCTURAL = "Structural"          # parses, uploads, internally consistent
    EXECUTABLE = "Executable"          # runs and reproduces its claimed scores
    METHODOLOGICAL = "Methodological"  # phases, submission economy, sizing
    DATA = "Data & leakage"            # splits disjoint, no target/leakage exposure
    DOCUMENTATION = "Documentation"    # pages complete, unambiguous, consistent
    GOVERNANCE = "Governance"          # review, license, persistence, ethics

    @property
    def number(self) -> int:
        """1-based type number, by declaration order."""
        return list(Dimension).index(self) + 1

    @property
    def label(self) -> str:
        """Display label, e.g. ``2. Executable``."""
        return f"{self.number}. {self.value}"


def tier_is_llm_judged(tier: "Tier") -> bool:
    """Whether a check's verdict comes from (or is assisted by) an LLM.

    User-facing surfaces show this as an ``LLM-as-a-judge: Yes/No`` column
    instead of the internal tier name: deterministic checks compute their own
    verdict in code (No); judged checks grade a rubric with an LLM (Yes); and
    attestation checks — human-only criteria — are *assisted* by an LLM that
    offers a guided suggestion rather than being left as a blank box (Yes).
    """
    return tier != Tier.DETERMINISTIC


class Severity(str, enum.Enum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


class Status(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"                  # deterministic tier only
    FINDING = "finding"            # advisory — judged tier or soft deterministic
    ATTESTATION_REQUIRED = "attestation_required"
    SKIPPED = "skipped"            # missing fact / inapplicable


@dataclass
class CheckResult:
    check_id: str
    status: Status
    severity: Severity
    message: str
    where: str | None = None       # locator inside the bundle, if any
    citation: str | None = None
    # Structured evidence for checks that *did something* — e.g. an execution
    # check records which image/data/duration/scores a run used and whether the
    # result was executed now or reused from an earlier phase. Rendered by the
    # report; absent (None) for ordinary static checks.
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "status": self.status.value,
            "severity": self.severity.value,
            "message": self.message,
            "where": self.where,
            "citation": self.citation,
            "details": self.details,
        }


@dataclass
class CheckContext:
    """Everything a check may look at. Built once per validation run."""

    bundle_dir: Path
    comp: dict[str, Any] | None            # parsed competition.yaml (None if unreadable)
    facts: CompetitionFacts = field(default_factory=CompetitionFacts)
    # When True, execution checks (``requires_execution``) are run: they
    # actually execute the bundle's baseline / starting-kit inside Docker
    # (reusing the build phase's runs when unchanged). Off by default so a
    # plain, keyless, static validation stays fast and Docker-free.
    execute: bool = False

    @classmethod
    def from_bundle_dir(cls, bundle_dir: Path, facts: CompetitionFacts | None = None,
                        *, execute: bool = False) -> "CheckContext":
        comp: dict[str, Any] | None = None
        yaml_path = bundle_dir / "competition.yaml"
        if yaml_path.is_file():
            try:
                loaded = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                comp = loaded if isinstance(loaded, dict) else None
            except yaml.YAMLError:
                comp = None
        return cls(bundle_dir=bundle_dir, comp=comp,
                   facts=facts or CompetitionFacts(), execute=execute)

    @property
    def root_dir(self) -> str:
        """The directory the bundle lives in — what the runner needs as
        ``root_dir`` to resolve and execute this exact bundle (rather than one
        under the active run dir)."""
        return str(self.bundle_dir.parent)

    def phases(self) -> list[dict[str, Any]]:
        if not self.comp:
            return []
        return [p for p in (self.comp.get("phases") or []) if isinstance(p, dict)]


class Check:
    """Base class. Subclass, set the class attrs, implement ``run``."""

    id: str = ""
    title: str = ""
    tier: Tier = Tier.DETERMINISTIC
    dimension: Dimension = Dimension.STRUCTURAL
    severity: Severity = Severity.WARNING
    citation: str | None = None
    # One brief, user-facing sentence on *how* the check is performed (what the
    # code looks at / runs). Surfaced in the `autocodabench checks` table so an
    # organizer understands the mechanism, not just the intent.
    how: str = ""
    # The section of the published challenge-proposal template (Pavão et al.,
    # "Challenge design roadmap") this check covers, e.g. "T3" (Data) or "T5"
    # (Metrics & evaluation). Documentation-only traceability: surfaced in
    # ``checks --json`` / ``checklist_coverage()`` so coverage can be audited
    # against that external standard, but NOT rendered as a table column. Empty
    # for platform-integrity checks with no proposal-template counterpart. See
    # ``docs/validation-checklist-proposal.md`` (§11).
    template_section: str = ""
    # Fact names that must be present in CompetitionFacts; otherwise the
    # check reports SKIPPED with an actionable message instead of guessing.
    requires_facts: tuple[str, ...] = ()
    # When True, the check executes the bundle (Docker) and only runs when the
    # validation was asked to execute (``CheckContext.execute``). Static checks
    # leave this False and always run.
    requires_execution: bool = False

    def _details(self, status: Status, message: str, details: dict[str, Any],
                 *, where: str | None = None,
                 severity: Severity | None = None) -> "CheckResult":
        r = self._result(status, message, where=where, severity=severity)
        r.details = details
        return r

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # pragma: no cover
        raise NotImplementedError

    # -- result helpers -----------------------------------------------------

    def _result(self, status: Status, message: str, *, where: str | None = None,
                severity: Severity | None = None) -> CheckResult:
        return CheckResult(
            check_id=self.id,
            status=status,
            severity=severity or self.severity,
            message=message,
            where=where,
            citation=self.citation,
        )

    def passed(self, message: str, **kw: Any) -> CheckResult:
        return self._result(Status.PASS, message, **kw)

    def failed(self, message: str, **kw: Any) -> CheckResult:
        return self._result(Status.FAIL, message, **kw)

    def finding(self, message: str, **kw: Any) -> CheckResult:
        return self._result(Status.FINDING, message, **kw)

    def skipped(self, message: str, **kw: Any) -> CheckResult:
        return self._result(Status.SKIPPED, message, **kw)

    def attestation(self, message: str, **kw: Any) -> CheckResult:
        return self._result(Status.ATTESTATION_REQUIRED, message, **kw)

    def missing_facts(self, ctx: CheckContext) -> list[str]:
        return [f for f in self.requires_facts if getattr(ctx.facts, f, None) is None]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

REGISTRY: dict[str, Check] = {}


def register(cls: type[Check]) -> type[Check]:
    """Class decorator: instantiate and register a check by its id."""
    inst = cls()
    if not inst.id:
        raise ValueError(f"{cls.__name__} has no id")
    if inst.id in REGISTRY:
        raise ValueError(f"duplicate check id: {inst.id}")
    REGISTRY[inst.id] = inst
    return cls


def checks_for(tiers: set[Tier] | None = None) -> list[Check]:
    out = [c for c in REGISTRY.values() if tiers is None or c.tier in tiers]
    return sorted(out, key=lambda c: (c.tier.value, c.id))


def run_checks(ctx: CheckContext, tiers: set[Tier] | None = None) -> list[CheckResult]:
    """Run all registered checks for the requested tiers (judged excluded —
    judged checks are async and dispatched by :mod:`autocodabench.checks.api`)."""
    results: list[CheckResult] = []
    for check in checks_for(tiers):
        if check.tier == Tier.JUDGED:
            continue
        if check.requires_execution and not ctx.execute:
            # Execution checks are silent (not even SKIPPED) when execution was
            # not requested, so a plain static report is unchanged.
            continue
        missing = check.missing_facts(ctx)
        if missing:
            results.append(check.skipped(
                f"requires facts not provided: {', '.join(missing)} — add them to "
                f"competition_facts.yaml to enable this check"))
            continue
        results.extend(check.run(ctx))
    return results
