"""Defect library + scoring for validate-bench.

validate-bench measures how well the validator catches authoring defects,
per LLM backbone. It seeds a known defect into an otherwise-clean bundle,
runs ``validate_bundle_path``, and checks whether the expected check fired.
Two tiers are reported separately:

- **deterministic** — backbone-independent (code computes PASS/FAIL). This
  tier is a sanity baseline and is fully keyless: the clean bundle is rebuilt
  from the shipped replay fixture, and the checks need neither an LLM nor
  Docker. It is exercised by the unit suite.
- **judged** — the backbone-sensitive measurement: an LLM grades a rubric, so
  the catch rate varies by model and run. Needs a backend.

The reusable pieces (the ``Defect`` dataclass, the ``DEFECTS`` library, the
clean-bundle builders, and the precision/recall/F1 maths) live here so they are
unit-tested and importable; the runnable orchestrator is the thin
``benchmark/autocodabench_validate_bench/run.py``.

Two instruments are supported. The default clean bundle is the public demo
(rebuilt from the replay fixture, keyless and Docker-free — the unit-tested
deterministic tier). Any imported competition's ``ground_truth/bundle`` can also
serve as a higher-fidelity instrument via :func:`build_clean_bundle_from_dir`;
:func:`corrupt_bundle` then turns it into many opaquely-labelled bad variants,
one per applicable defect, self-adapting to the instrument
(:func:`applicable_defects`).

Privacy/leakage: only the *bundle* directory is ever copied into the working
tempdir; a competition's ``ground_truth/sample_submissions/`` and
``expected_result.json`` are never placed where the validator — or any agent it
drives — can read them. The isolation is a property of *what is copied*, not of
prompt discipline.
"""
from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import yaml

# The clean bundle is the shipped demo, rebuilt deterministically from its
# recorded run (keyless, Docker-free) — the same fixture the `demo` command
# and the test suite use.
FIXTURE = (Path(__file__).resolve().parents[1]
           / "backends" / "fixtures" / "demo_bundle.jsonl")
SLUG = "demo-ai-text-detection"

TIERS = ("deterministic", "judged")


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------

def _edit_yaml(bundle: Path, mutate: Callable[[dict], None]) -> None:
    p = bundle / "competition.yaml"
    comp = yaml.safe_load(p.read_text())
    mutate(comp)
    p.write_text(yaml.safe_dump(comp, sort_keys=False, allow_unicode=True))


def _edit_text(bundle: Path, rel: str, old: str, new: str) -> None:
    p = bundle / rel
    text = p.read_text()
    if old not in text:
        raise ValueError(f"defect seed failed: {old!r} not found in {rel}")
    p.write_text(text.replace(old, new))


def _leak_reference_into_input(bundle: Path) -> None:
    """Copy a ground-truth file from reference_data/ into input_data/ — the
    cross-role leak that ``reference-data-not-participant-visible`` catches."""
    ref = bundle / "reference_data"
    files = [p for p in sorted(ref.rglob("*")) if p.is_file() and p.read_bytes()]
    if not files:
        raise ValueError("defect seed failed: no reference_data file to leak")
    dest = bundle / "input_data"
    dest.mkdir(exist_ok=True)
    shutil.copy(files[0], dest / files[0].name)


def _collide_leaderboard_keys(comp: dict) -> None:
    cols = comp["leaderboards"][0]["columns"]
    cols[1]["key"] = cols[0]["key"]      # duplicate column key


def _overwrite(bundle: Path, rel: str, text: str) -> None:
    """Replace a page file wholesale with a deliberately deficient version —
    used to seed judged-tier defects with a clear, catchable regression."""
    p = bundle / rel
    if not p.is_file():
        raise ValueError(f"defect seed failed: {rel} not present")
    p.write_text(text, encoding="utf-8")


def _shrink_dev_phase(comp: dict) -> None:
    """Shrink the development phase to 10 days *relative to its own start*, so
    the mutation is portable across instruments (no hard-coded dates)."""
    phase = comp["phases"][0]
    start = phase.get("start")
    parsed = None
    if isinstance(start, datetime):
        parsed = start
    elif isinstance(start, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(start.strip(), fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError("phase[0] start not a parseable date")
    phase["end"] = (parsed + timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True)
class Defect:
    """One known authoring defect and the check expected to catch it."""
    id: str
    tier: str                       # "deterministic" | "judged"
    expect_check: str               # check id that should flag it
    apply: Callable[[Path], None]   # mutate the bundle in place
    description: str


# ---------------------------------------------------------------------------
# Defect library — grow this; each entry is one measured row.
# ---------------------------------------------------------------------------

DEFECTS: list[Defect] = [
    # --- deterministic tier (backbone-independent sanity baseline) -----------
    Defect("missing-page", "deterministic", "bundle-schema",
           lambda b: (b / "pages" / "overview.md").unlink(),
           "a page referenced from competition.yaml is deleted"),
    Defect("unwritten-leaderboard-key", "deterministic", "bundle-schema",
           lambda b: _edit_text(b, "scoring_program/score.py",
                                '"balanced_accuracy"', '"bal_acc"'),
           "scoring program stops writing a leaderboard column key"),
    Defect("no-daily-cap", "deterministic", "daily-submission-cap",
           lambda b: _edit_yaml(b, lambda c: c["phases"][0].pop("max_submissions_per_day")),
           "development phase loses its per-day submission cap"),
    Defect("short-dev-phase", "deterministic", "dev-phase-duration",
           lambda b: _edit_yaml(b, _shrink_dev_phase),
           "development phase shrunk to 10 days"),
    Defect("no-sorting", "deterministic", "leaderboard-sorting",
           lambda b: _edit_yaml(b, lambda c: c["leaderboards"][0]["columns"][0].pop("sorting")),
           "primary leaderboard column loses its sorting direction"),
    Defect("final-unlimited", "deterministic", "final-phase-submission-limit",
           lambda b: _edit_yaml(b, lambda c: c["phases"][1].__setitem__("max_submissions", 50)),
           "final phase allows 50 total submissions"),
    Defect("kit-missing", "deterministic", "starting-kit",
           lambda b: shutil.rmtree(b / "starting_kit"),
           "starting kit removed"),
    Defect("single-phase", "deterministic", "two-phase-structure",
           lambda b: _edit_yaml(b, lambda c: c.__setitem__("phases", c["phases"][:1])),
           "final phase dropped (single-phase competition)"),
    Defect("docker-unpinned", "deterministic", "docker-image-pinned",
           lambda b: _edit_yaml(b, lambda c: c.pop("docker_image")),
           "docker image no longer pinned"),
    Defect("docker-latest-tag", "deterministic", "docker-image-pinned",
           lambda b: _edit_yaml(b, lambda c: c.__setitem__(
               "docker_image", "codalab/codalab-legacy:latest")),
           "docker image pinned only to a floating :latest tag"),
    Defect("metric-sorting-inverted", "deterministic", "metric-direction-semantics",
           lambda b: _edit_yaml(b, lambda c: c["leaderboards"][0]["columns"][0]
                                .__setitem__("sorting", "asc")),
           "accuracy column sorted ascending (ranks the worst submission first)"),
    Defect("leaderboard-key-collision", "deterministic", "leaderboard-well-formed",
           lambda b: _edit_yaml(b, _collide_leaderboard_keys),
           "two leaderboard columns share one key (one is silently overwritten)"),
    Defect("reference-leaked-to-input", "deterministic",
           "reference-data-not-participant-visible",
           _leak_reference_into_input,
           "a ground-truth file is copied into the participant-visible input_data/"),
    # --- judged tier (the backbone-sensitive measurement) --------------------
    Defect("caps-contradiction", "judged", "judged-docs-config-consistency",
           lambda b: _edit_text(b, "pages/overview.md",
                                "max 5 submissions/day", "max 20 submissions/day"),
           "overview page promises 20 submissions/day; config enforces 5"),
    Defect("metric-direction-contradiction", "judged", "judged-docs-config-consistency",
           lambda b: _edit_text(
               b, "pages/evaluation.md",
               "The primary metric is **balanced accuracy**",
               "The primary metric is **balanced accuracy** — LOWER values rank "
               "higher on the leaderboard (ascending order),"),
           "evaluation page claims lower-is-better; leaderboard sorts descending"),
    Defect("phase-dates-contradiction", "judged", "judged-docs-config-consistency",
           lambda b: _edit_text(b, "pages/overview.md",
                                "## Phases",
                                "## Phases\n\nThe development phase runs from "
                                "2027-07-01 to 2027-08-15."),
           "overview page states 2027 phase dates; config says 2026"),
    # New judged checks — each page is overwritten with a clearly deficient
    # version so the LLM has an unambiguous regression to catch.
    Defect("vague-task", "judged", "judged-task-framing",
           lambda b: _overwrite(b, "pages/overview.md",
               "# Competition\n\nMake some predictions for our dataset.\n\n"
               "## Submission format\n\nUpload a zip with `predictions.csv` "
               "(one label `0`/`1` per line, in evaluation order).\n\n"
               "## Phases\n\n1. **Development** — max 5 submissions/day.\n"
               "2. **Final** — max 3 submissions total."),
           "overview guts the scientific question and motivation (vague task)"),
    Defect("no-submission-format", "judged", "judged-submission-instructions",
           lambda b: _overwrite(b, "pages/overview.md",
               "# AI-Generated Text Detection (demo)\n\nClassify whether a text "
               "was written by a human or a language model.\n\n## Phases\n\n"
               "1. **Development** — max 5 submissions/day.\n"
               "2. **Final** — max 3 submissions total."),
           "overview removes the submission-format section entirely"),
    Defect("unexplained-metric", "judged", "judged-evaluation-explained",
           lambda b: _overwrite(b, "pages/evaluation.md",
               "# Evaluation\n\nThe primary metric is balanced accuracy.\n"),
           "evaluation page names the metric but explains nothing (no range, "
           "no direction, no tie-break)"),
    Defect("sparse-data-doc", "judged", "judged-data-description",
           lambda b: _overwrite(b, "pages/data.md",
               "# Data\n\nThere is a dataset.\n"),
           "data page is gutted (no size, splits, visibility, policy, or license)"),
    Defect("gutted-rules", "judged", "judged-rules-completeness",
           lambda b: _overwrite(b, "pages/terms.md",
               "# Terms\n\nBe nice and have fun.\n"),
           "terms page drops eligibility, tie-break, IP, and anti-fraud clauses"),
]


def defects_for_tier(tier: str | None = None) -> list[Defect]:
    """The defect library, optionally filtered to one tier."""
    if tier is None:
        return list(DEFECTS)
    return [d for d in DEFECTS if d.tier == tier]


# ---------------------------------------------------------------------------
# Clean bundle + seeding
# ---------------------------------------------------------------------------

def build_clean_bundle(workdir: Path) -> Path:
    """Rebuild the shipped demo bundle into ``workdir`` and return its path.

    Keyless and Docker-free — replays the recorded authoring run against the
    real core, exactly like ``autocodabench demo``.
    """
    from ..backends import ReplayBackend
    from ..backends.base import AgentTask
    out = Path(workdir) / "clean"
    result = asyncio.run(ReplayBackend(FIXTURE, out_dir=out).run(AgentTask(prompt="seed")))
    if not result.ok:
        raise RuntimeError(f"clean-bundle replay failed: {result.error}")
    return out / SLUG


def build_clean_bundle_from_dir(src_bundle_dir: str | Path, workdir: Path) -> Path:
    """Copy an arbitrary clean bundle directory into ``workdir`` and return it.

    This is the generalised instrument: the validate-bench can run against any
    clean bundle, not only the demo. The intended high-fidelity instrument is a
    real competition's ``ground_truth/bundle`` — and the data-leakage isolation
    is preserved *by construction*, because only the bundle directory is copied;
    the sibling ``sample_submissions/`` and ``expected_result.json`` are never
    placed where the validator (or any agent it drives) can read them.
    """
    src = Path(src_bundle_dir).expanduser().resolve()
    if not (src / "competition.yaml").is_file():
        raise ValueError(f"not a bundle (no competition.yaml): {src}")
    out = Path(workdir) / "clean"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(src, out)
    return out


def applicable_defects(clean: Path, workdir: Path,
                       candidates: list[Defect] | None = None) -> tuple[list[Defect], list[dict]]:
    """Select the defects that can be measured on ``clean``, with reasons for
    the rest — so an arbitrary instrument self-adapts and nothing is silently
    dropped.

    A candidate is *applicable* iff (a) its mutation applies without error on a
    throwaway copy, and (b) its target check does **not** already fire on the
    unmutated bundle (the specificity precondition — a check that already
    findings on the clean instrument cannot demonstrate a catch). Returns
    ``(applicable, skipped)`` where each skipped item is
    ``{"defect", "expect_check", "reason"}``.
    """
    from ..checks import validate_bundle_path
    cands = candidates if candidates is not None else list(DEFECTS)
    clean_report = validate_bundle_path(clean, execute=False)
    applicable: list[Defect] = []
    skipped: list[dict] = []
    for d in cands:
        if flagged(clean_report, d.expect_check):
            skipped.append({"defect": d.id, "expect_check": d.expect_check,
                            "reason": "target check already fires on the clean bundle"})
            continue
        try:
            seed_defect(clean, d, workdir / f"_probe-{d.id}")
        except Exception as e:  # mutation not applicable to this instrument
            skipped.append({"defect": d.id, "expect_check": d.expect_check,
                            "reason": f"mutation not applicable: {e}"})
            continue
        applicable.append(d)
    return applicable, skipped


def seed_defect(clean: Path, defect: Defect, dest: Path) -> Path:
    """Copy the clean bundle to ``dest`` and apply one defect. Returns ``dest``."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(clean, dest)
    defect.apply(dest)
    return dest


def flagged(report, check_id: str) -> bool:
    """True if ``check_id`` fired (FAIL or FINDING) in a validation report."""
    from ..checks import Status
    return any(r.check_id == check_id and r.status in (Status.FAIL, Status.FINDING)
               for r in report.results)


@dataclass(frozen=True)
class CorruptedVariant:
    """One opaquely-labelled corrupted copy of a clean bundle.

    ``label`` is what a *checking* agent is shown — deliberately opaque (``case-03``),
    never the defect kind, so the flaw cannot be inferred from the path. The
    ``defect_id`` / ``expect_check`` fields are the *answer key*: they belong to
    the deterministic auditor that scores the checker, and must not be exposed to
    the agent under evaluation.
    """
    label: str
    path: Path
    defect_id: str
    expect_check: str
    tier: str
    description: str


def corrupt_bundle(clean: Path, dest_root: Path,
                   candidates: list[Defect] | None = None,
                   *, label_prefix: str = "case") -> tuple[list[CorruptedVariant], list[dict]]:
    """Corrupt one clean bundle into many bad variants — one per applicable
    defect — under ``dest_root`` with opaque labels.

    This is the entry point for measuring a checker against *any* imported
    ground-truth bundle: point ``clean`` at the bundle (built via
    :func:`build_clean_bundle_from_dir`), and each returned variant is the clean
    bundle plus exactly one seeded flaw, in a neutrally-named directory. The
    defect set self-adapts to the instrument (:func:`applicable_defects`), so a
    new bundle yields results without bespoke wiring; the second return value
    lists the defects that did not apply, with reasons, so coverage is never
    silently truncated.

    Returns ``(variants, skipped)``. The variants carry the answer key; keep it
    away from the agent being evaluated.
    """
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    probe = dest_root / "_probe"
    try:
        applic, skipped = applicable_defects(clean, probe, candidates)
    finally:
        if probe.exists():
            shutil.rmtree(probe, ignore_errors=True)
    variants: list[CorruptedVariant] = []
    for i, d in enumerate(applic, 1):
        label = f"{label_prefix}-{i:02d}"
        path = seed_defect(clean, d, dest_root / label)
        variants.append(CorruptedVariant(
            label=label, path=path, defect_id=d.id,
            expect_check=d.expect_check, tier=d.tier, description=d.description))
    return variants, skipped


# ---------------------------------------------------------------------------
# Metrics — precision / recall / F1 per tier
# ---------------------------------------------------------------------------

def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    if precision and recall and (precision + recall):
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0 if (precision is not None and recall is not None) else None
    return {"precision": precision, "recall": recall, "f1": f1,
            "tp": tp, "fp": fp, "fn": fn}


def summarize(rows: list[dict], clean_false_positives: int = 0,
              clean_runs: int = 0) -> dict:
    """Fold per-defect rows into per-tier precision/recall/F1.

    ``rows`` items: ``{"defect","tier","runs","caught"}`` where ``caught`` is
    the number of runs in which the expected check fired (``None`` = skipped).
    Recall = caught / runs (did we catch the seeded defect). Precision uses
    clean-bundle false positives as the FP count (flags raised when there was
    nothing to flag). ``clean_false_positives``/``clean_runs`` describe the
    judged tier's behaviour on an unmutated bundle.
    """
    out: dict = {}
    for tier in TIERS:
        tier_rows = [r for r in rows if r["tier"] == tier and r.get("caught") is not None]
        if not tier_rows:
            out[tier] = None
            continue
        tp = sum(r["caught"] for r in tier_rows)
        total = sum(r["runs"] for r in tier_rows)
        fn = total - tp
        fp = clean_false_positives if tier == "judged" else 0
        m = _prf(tp, fp, fn)
        m["defects_evaluated"] = len(tier_rows)
        m["catch_rate"] = tp / total if total else None
        if tier == "judged" and clean_runs:
            m["clean_false_positive_rate"] = clean_false_positives / clean_runs
        out[tier] = m
    return out
