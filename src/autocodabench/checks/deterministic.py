"""Deterministic checks — code computes the verdict; no LLM, no network.

This is the only tier permitted to gate: ``ValidationReport.ok`` is
defined as the absence of a deterministic FAIL, because a gate must be
reproducible and contestable, and only a code-computed verdict is both.
Citations are chapter handles into Pavão et al. (2024), *AI Competitions
and Benchmarks: The Science Behind the Contests*, matching the
competition-design knowledge skill, or the Codabench bundle schema docs.
"""
from __future__ import annotations

import csv
import hashlib
import math
import re
from datetime import datetime

from ..core.bundle_io import validate_bundle
from .base import (
    Check,
    CheckContext,
    CheckResult,
    Dimension,
    Severity,
    Status,
    Tier,
    register,
)

_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def _parse_date(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


@register
class SchemaLint(Check):
    """The structural gate: competition.yaml parses, every referenced file
    exists, programs carry runnable metadata, leaderboard keys are written
    by the scoring program."""

    id = "bundle-schema"
    how = "Parses competition.yaml and checks every referenced file, program metadata, and leaderboard key against the Codabench schema."
    title = "Bundle schema and file references"
    dimension = Dimension.STRUCTURAL
    severity = Severity.BLOCKER
    citation = "Codabench bundle schema (Yaml-Structure.md)"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        report = validate_bundle(ctx.bundle_dir.name, str(ctx.bundle_dir.parent))
        issues = report.get("issues") or []
        if not issues:
            return [self.passed("competition.yaml parses; all referenced files exist; "
                                "programs and leaderboard keys are consistent")]
        out: list[CheckResult] = []
        for issue in issues:
            status = Status.FAIL if issue.get("severity") == "error" else Status.FINDING
            sev = Severity.BLOCKER if issue.get("severity") == "error" else Severity.WARNING
            out.append(self._result(status, issue.get("message", ""),
                                    where=issue.get("where"), severity=sev))
        return out


@register
class TwoPhaseStructure(Check):
    """Single-phase competitions overfit the public leaderboard."""

    id = "two-phase-structure"
    how = "Counts the phases declared in competition.yaml."
    title = "Development + final phase structure"
    dimension = Dimension.METHODOLOGICAL
    citation = "Pavão et al. (Ch. 5, Ch. 11)"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        phases = ctx.phases()
        if not phases:
            return [self.skipped("no phases declared (schema lint reports this)")]
        if len(phases) >= 2:
            return [self.passed(f"{len(phases)} phases declared (development + final)")]
        return [self.finding(
            "single-phase competition — without a final phase on a private test "
            "set, the public leaderboard is the final ranking and overfits")]


@register
class DevPhaseDuration(Check):
    """A development phase shorter than ~40 days only reaches people who
    were already working on the problem."""

    id = "dev-phase-duration"
    how = "Parses the first phase's start/end dates and computes the span in days."
    title = "Development phase ≥ 40 days"
    dimension = Dimension.METHODOLOGICAL
    citation = "Pavão et al. (Ch. 13)"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        phases = ctx.phases()
        if not phases:
            return [self.skipped("no phases declared")]
        first = phases[0]
        start, end = _parse_date(first.get("start")), _parse_date(first.get("end"))
        if start is None or end is None:
            return [self.skipped("first phase start/end not parseable as dates",
                                 where="phases[0]")]
        days = (end - start).days
        if days >= 40:
            return [self.passed(f"development phase runs {days} days", where="phases[0]")]
        return [self.finding(
            f"development phase runs only {days} days — below the ~40-day floor "
            f"for participants who weren't already working on the problem",
            where="phases[0]")]


@register
class DailySubmissionCap(Check):
    """Uncapped development submissions invite brute-force leaderboard
    overfitting; 5–10/day is the typical guard."""

    id = "daily-submission-cap"
    how = "Reads max_submissions_per_day on each development phase."
    title = "Daily submission cap on development phases"
    dimension = Dimension.METHODOLOGICAL
    citation = "Pavão et al. (Ch. 5)"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        phases = ctx.phases()
        if len(phases) < 1:
            return [self.skipped("no phases declared")]
        out: list[CheckResult] = []
        dev_phases = phases[:-1] if len(phases) > 1 else phases
        for i, p in enumerate(dev_phases):
            cap = p.get("max_submissions_per_day")
            where = f"phases[{i}]"
            if cap is None:
                out.append(self.finding(
                    f"phase '{p.get('name', i)}' has no max_submissions_per_day — "
                    "uncapped daily submissions enable leaderboard probing", where=where))
            elif isinstance(cap, int) and cap > 10:
                out.append(self.finding(
                    f"phase '{p.get('name', i)}' allows {cap} submissions/day — "
                    "above the typical 5–10 anti-overfitting range", where=where))
            else:
                out.append(self.passed(
                    f"phase '{p.get('name', i)}' caps submissions at {cap}/day", where=where))
        return out


@register
class FinalPhaseSubmissionLimit(Check):
    """The final phase exists to close the overfit loophole: 1–3 total
    submissions on the never-seen private set."""

    id = "final-phase-submission-limit"
    how = "Reads max_submissions on the final phase."
    title = "Final phase total-submission limit ≤ 3"
    dimension = Dimension.METHODOLOGICAL
    citation = "Pavão et al. (Ch. 5)"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        phases = ctx.phases()
        if len(phases) < 2:
            return [self.skipped("no final phase declared (see two-phase-structure)")]
        final = phases[-1]
        where = f"phases[{len(phases) - 1}]"
        limit = final.get("max_submissions")
        if limit is None:
            return [self.finding(
                f"final phase '{final.get('name', '?')}' has no max_submissions — "
                "unlimited final submissions re-open the overfit loophole", where=where)]
        if isinstance(limit, int) and limit <= 3:
            return [self.passed(f"final phase allows {limit} total submissions", where=where)]
        return [self.finding(
            f"final phase allows {limit} total submissions — above the 1–3 norm",
            where=where)]


@register
class LeaderboardSortingDeclared(Check):
    """Every ranked column must declare its direction; a missing `sorting`
    silently inverts metrics where lower is better."""

    id = "leaderboard-sorting"
    how = "Checks each ranked leaderboard column declares a sorting direction."
    title = "Leaderboard columns declare sorting direction"
    dimension = Dimension.DOCUMENTATION
    citation = "Pavão et al. (Ch. 4); Codabench Yaml-Structure.md"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        if not ctx.comp:
            return [self.skipped("competition.yaml not parseable")]
        out: list[CheckResult] = []
        for i, lb in enumerate(ctx.comp.get("leaderboards") or []):
            if not isinstance(lb, dict):
                continue
            for j, col in enumerate(lb.get("columns") or []):
                if not isinstance(col, dict) or "computation" in col:
                    continue
                where = f"leaderboards[{i}].columns[{j}]"
                if col.get("sorting") in ("asc", "desc"):
                    out.append(self.passed(
                        f"column '{col.get('key')}' sorts {col['sorting']}", where=where))
                else:
                    out.append(self.finding(
                        f"column '{col.get('key')}' declares no sorting direction — "
                        "the ranking direction of the metric is ambiguous", where=where))
        return out or [self.skipped("no leaderboard columns declared")]


@register
class StartingKitPresent(Check):
    """Participants who cannot submit in their first hour mostly never
    submit; the kit is the single biggest participation lever."""

    id = "starting-kit"
    how = "Looks for files shipped under starting_kit/."
    title = "Runnable starting kit shipped"
    dimension = Dimension.DOCUMENTATION
    citation = "Pavão et al. (Ch. 5, Ch. 13)"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        kit = ctx.bundle_dir / "starting_kit"
        files = [p for p in kit.rglob("*") if p.is_file()] if kit.is_dir() else []
        if files:
            return [self.passed(f"starting_kit/ ships {len(files)} file(s)")]
        return [self.finding(
            "no starting_kit/ contents — participants have nothing to download, "
            "run, and submit in their first hour")]


@register
class BaselineSolutionsPresent(Check):
    """Two baselines: a trivial one bounds the metric, a competent one
    signals whether there is room above it."""

    id = "baseline-solutions"
    how = "Counts solution folders and checks they are declared in competition.yaml."
    title = "Baseline solutions shipped (trivial + competent)"
    dimension = Dimension.EXECUTABLE
    citation = "Pavão et al. (Ch. 5)"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        sol_root = ctx.bundle_dir / "solutions"
        dirs = [p for p in sol_root.iterdir() if p.is_dir()] if sol_root.is_dir() else []
        declared = (ctx.comp or {}).get("solutions") or []
        if not dirs:
            return [self.finding(
                "no baseline solution under solutions/ — the bundle cannot be "
                "smoke-tested end-to-end and participants have no reference score")]
        if not declared:
            return [self.finding(
                f"solutions/ contains {len(dirs)} folder(s) but competition.yaml "
                "declares no solutions: block — Codabench will not run them",
                where="competition.yaml:solutions")]
        if len(dirs) == 1:
            return [self.finding(
                "one baseline shipped — consider two (a trivial constant/random "
                "baseline to bound the metric, and a competent off-the-shelf one)",
                severity=Severity.INFO)]
        return [self.passed(f"{len(dirs)} baseline solutions shipped and declared")]


@register
class DockerImagePinned(Check):
    """Silent dependency drift breaks reproducibility — pin the image."""

    id = "docker-image-pinned"
    how = "Reads docker_image and checks it carries an explicit (non-:latest) version tag."
    title = "Worker docker image pinned"
    dimension = Dimension.EXECUTABLE
    citation = "Pavão et al. (Ch. 11)"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        if not ctx.comp:
            return [self.skipped("competition.yaml not parseable")]
        image = ctx.comp.get("docker_image")
        if not image:
            return [self.finding(
                "no docker_image declared — submissions will run on whatever default "
                "the queue uses, which can change under you",
                where="competition.yaml")]
        # An explicit tag is what makes "every candidate is judged in the same
        # way" true; a bare reference or ':latest' silently drifts (Ch. 11).
        ref = str(image)
        tag = ref.rsplit("/", 1)[-1].partition(":")[2]  # tag after the final colon
        if not tag or tag == "latest":
            return [self.finding(
                f"docker_image '{image}' has no explicit version tag "
                f"({'`:latest` floats' if tag == 'latest' else 'no tag'}) — pin a "
                "fixed tag so the scoring environment cannot drift under you",
                where="competition.yaml")]
        return [self.passed(f"docker_image pinned to an explicit tag: {image}")]


@register
class TestSetSize(Check):
    """The 100/E rule: to resolve top systems at anticipated error rate E,
    you need roughly 100/E test examples."""

    id = "test-set-size"
    how = "Compares the reference/test row count against 100 / anticipated-error-rate."
    title = "Test set sized for the anticipated error rate (100/E)"
    dimension = Dimension.METHODOLOGICAL
    citation = "Pavão et al. (Ch. 4)"
    requires_facts = ("anticipated_error_rate",)

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        e = ctx.facts.anticipated_error_rate
        assert e is not None  # guaranteed by requires_facts
        if not (0 < e < 1):
            return [self.skipped(f"anticipated_error_rate={e} is not a rate in (0, 1)")]
        needed = math.ceil(100 / e)

        size = ctx.facts.test_set_size
        counted_from = "facts.test_set_size"
        if size is None:
            size = self._count_reference_rows(ctx)
            counted_from = "reference_data row count"
        if size is None:
            return [self.skipped(
                "cannot determine test-set size — declare test_set_size in "
                "competition_facts.yaml")]
        if size >= needed:
            return [self.passed(
                f"test set has {size} examples ({counted_from}) ≥ 100/E = {needed} "
                f"for E={e}")]
        return [self.finding(
            f"test set has {size} examples ({counted_from}) but the 100/E rule "
            f"needs ≥ {needed} for anticipated error rate {e} — score differences "
            "near the top will be noise")]

    @staticmethod
    def _count_reference_rows(ctx: CheckContext) -> int | None:
        ref = ctx.bundle_dir / "reference_data"
        if not ref.is_dir():
            return None
        csvs = sorted(ref.glob("*.csv"))
        if len(csvs) != 1:
            return None  # ambiguous — require the declared fact
        with csvs[0].open(newline="", encoding="utf-8", errors="replace") as f:
            return sum(1 for row in csv.reader(f) if row)


@register
class ExternalDataRuleStated(Check):
    """Undeclared external data is the most common post-hoc disqualification
    fight; the rule must be written down either way."""

    id = "external-data-rule"
    how = "Scans the pages for an external-data / pre-training policy and cross-checks the declared fact."
    title = "External-data rule declared and documented"
    dimension = Dimension.DOCUMENTATION
    citation = "Pavão et al. (Ch. 5)"
    requires_facts = ("external_data_allowed",)

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        allowed = ctx.facts.external_data_allowed
        # Deterministic half: the pages must mention the rule at all.
        pages_dir = ctx.bundle_dir / "pages"
        text = ""
        if pages_dir.is_dir():
            for p in pages_dir.glob("*.md"):
                text += p.read_text(encoding="utf-8", errors="replace").lower()
        if "external data" in text or "external dataset" in text or "pre-trained" in text or "pretrained" in text:
            return [self.passed(
                f"external-data policy (declared: allowed={allowed}) is mentioned "
                "in the competition pages")]
        return [self.finding(
            f"facts declare external_data_allowed={allowed} but no competition "
            "page mentions external data or pre-training — participants will "
            "make incompatible assumptions")]


# ---------------------------------------------------------------------------
# Metric-direction semantics (D5) — the official-template defect catcher.
# ---------------------------------------------------------------------------

# Metric-name tokens whose natural ranking direction is known. Matching is on
# whole alphanumeric tokens of the column key/title (so "mae" never matches
# inside "image"); only a confident, unambiguous match yields a verdict.
_HIGHER_IS_BETTER = frozenset({
    "accuracy", "acc", "balanced", "f1", "fbeta", "auc", "auroc", "roc",
    "precision", "recall", "sensitivity", "specificity", "iou", "jaccard",
    "dice", "map", "ndcg", "r2", "bleu", "rouge", "kappa", "mcc", "gain",
})
_LOWER_IS_BETTER = frozenset({
    "error", "err", "loss", "logloss", "rmse", "mae", "mse", "rmsle", "mape",
    "smape", "wer", "cer", "fid", "perplexity", "ppl", "regret", "brier",
    "fpr", "fnr", "distance",
})


def _metric_direction(name: str) -> str | None:
    """'higher'/'lower'/None for a column key+title, by whole-token match.

    Returns None when no known metric token is present or when both a
    higher- and a lower-is-better token appear (ambiguous → no verdict)."""
    tokens = set(re.split(r"[^a-z0-9]+", name.lower()))
    hi = bool(tokens & _HIGHER_IS_BETTER)
    lo = bool(tokens & _LOWER_IS_BETTER)
    if hi == lo:                     # neither, or both → not confident
        return None
    return "higher" if hi else "lower"


@register
class MetricDirectionSemantics(Check):
    """The declared sort direction must match the named metric's known
    direction. The official Codabench template ships an accuracy column sorted
    ascending — a silent inversion that ranks the worst submission first; this
    is the deterministic check that catches it without an LLM."""

    id = "metric-direction-semantics"
    how = "Looks up the metric name's known ranking direction and compares it to the column's sorting."
    title = "Sort direction matches the named metric's semantics"
    dimension = Dimension.DOCUMENTATION
    citation = "Pavão et al. (Ch. 4)"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        if not ctx.comp:
            return [self.skipped("competition.yaml not parseable")]
        out: list[CheckResult] = []
        for i, lb in enumerate(ctx.comp.get("leaderboards") or []):
            if not isinstance(lb, dict):
                continue
            for j, col in enumerate(lb.get("columns") or []):
                if not isinstance(col, dict) or "computation" in col:
                    continue
                sorting = col.get("sorting")
                if sorting not in ("asc", "desc"):
                    continue  # leaderboard-sorting owns the missing-direction case
                name = f"{col.get('key', '')} {col.get('title', '')}"
                direction = _metric_direction(name)
                if direction is None:
                    continue
                where = f"leaderboards[{i}].columns[{j}]"
                wrong = (direction == "higher" and sorting == "asc") or \
                        (direction == "lower" and sorting == "desc")
                key = col.get("key") or col.get("title")
                if wrong:
                    better = "higher-is-better" if direction == "higher" else "lower-is-better"
                    want = "desc" if direction == "higher" else "asc"
                    out.append(self.finding(
                        f"column '{key}' looks {better} but sorts {sorting} — the "
                        f"leaderboard would rank the worst submission first; expected "
                        f"sorting: {want}", where=where))
                else:
                    out.append(self.passed(
                        f"column '{key}' sorts {sorting}, consistent with its "
                        f"{'higher' if direction == 'higher' else 'lower'}-is-better metric",
                        where=where))
        return out or [self.skipped(
            "no leaderboard column names a metric with a known ranking direction")]


# ---------------------------------------------------------------------------
# Leaderboard well-formedness (D1) — structural lints beyond the schema linter.
# ---------------------------------------------------------------------------

@register
class LeaderboardWellFormed(Check):
    """Each leaderboard must carry a key, and its columns must have unique keys
    and unique indices — collisions silently drop or overwrite a ranked
    column on the platform."""

    id = "leaderboard-well-formed"
    how = "Checks each leaderboard declares a key and that its column keys and indices are unique."
    title = "Leaderboard has a key; column keys and indices are unique"
    dimension = Dimension.STRUCTURAL
    citation = "Pavão et al. (Ch. 11); Codabench Yaml-Structure.md"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        if not ctx.comp:
            return [self.skipped("competition.yaml not parseable")]
        boards = [lb for lb in (ctx.comp.get("leaderboards") or []) if isinstance(lb, dict)]
        if not boards:
            return [self.skipped("no leaderboards declared")]
        out: list[CheckResult] = []
        for i, lb in enumerate(boards):
            where = f"leaderboards[{i}]"
            if not lb.get("key"):
                out.append(self.finding(
                    "leaderboard declares no key — the platform cannot address "
                    "this leaderboard", where=where))
            cols = [c for c in (lb.get("columns") or []) if isinstance(c, dict)]
            keys = [c.get("key") for c in cols if c.get("key") is not None]
            dup_keys = sorted({k for k in keys if keys.count(k) > 1})
            if dup_keys:
                out.append(self.failed(
                    f"duplicate column key(s) {dup_keys} — a ranked column will be "
                    "silently overwritten", where=where, severity=Severity.BLOCKER))
            indices = [c.get("index") for c in cols if c.get("index") is not None]
            dup_idx = sorted({x for x in indices if indices.count(x) > 1})
            if dup_idx:
                out.append(self.finding(
                    f"duplicate column index/indices {dup_idx} — column ordering is "
                    "ambiguous", where=where))
            if not dup_keys and not dup_idx and lb.get("key"):
                out.append(self.passed(
                    f"leaderboard '{lb.get('key')}' has {len(cols)} column(s) with "
                    "unique keys and indices", where=where))
        return out


# ---------------------------------------------------------------------------
# Cross-role data isolation (D1/D4) — ground truth must stay hidden.
# ---------------------------------------------------------------------------

_JUNK_NAMES = {".gitkeep", ".gitignore", ".ds_store"}


def _file_hashes(root: Path) -> dict[str, str]:
    """Map content-hash → first relative path, for every substantive file under
    ``root``. Empty and placeholder files (``.gitkeep``, ``.DS_Store``) are
    skipped so they cannot produce a spurious cross-role match."""
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if not p.is_file() or p.name.lower() in _JUNK_NAMES:
            continue
        data = p.read_bytes()
        if not data:
            continue
        h = hashlib.sha256(data).hexdigest()
        out.setdefault(h, str(p.relative_to(root)))
    return out


@register
class ReferenceDataNotParticipantVisible(Check):
    """Files in the hidden reference (ground-truth) role must not also appear,
    byte-for-byte, under a participant-visible role (public_data / input_data).
    An identical reference file in a visible role is leaked ground truth."""

    id = "reference-data-not-participant-visible"
    how = "Hashes reference_data files and checks none appear byte-for-byte under public_data/ or input_data/."
    title = "Reference (ground-truth) data is not exposed in a participant role"
    dimension = Dimension.DATA
    citation = "Pavão et al. (Ch. 11, Ch. 3)"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        ref = _file_hashes(ctx.bundle_dir / "reference_data")
        if not ref:
            return [self.skipped("no reference_data/ to check")]
        leaked: list[str] = []
        for role in ("public_data", "input_data"):
            visible = _file_hashes(ctx.bundle_dir / role)
            for h, rel in ref.items():
                if h in visible:
                    leaked.append(f"reference_data/{rel} == {role}/{visible[h]}")
        if leaked:
            shown = "; ".join(sorted(leaked)[:5])
            return [self.failed(
                "ground-truth file(s) from reference_data/ also appear, byte-for-byte, "
                f"in a participant-visible role — leaked labels: {shown}",
                where="reference_data/", severity=Severity.BLOCKER)]
        return [self.passed(
            f"none of the {len(ref)} reference_data file(s) appear in public_data/ "
            "or input_data/")]
