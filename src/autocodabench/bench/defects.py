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
clean-bundle builder, and the precision/recall/F1 maths) live here so they are
unit-tested and importable; the runnable orchestrator is the thin
``benchmark/autocodabench_validate_bench/run.py``.

Privacy/leakage: nothing here touches a competition's ``ground_truth`` — the
clean bundle is the public demo bundle, mutated in a tempdir.
"""
from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
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
           lambda b: _edit_yaml(b, lambda c: c["phases"][0].__setitem__(
               "end", "2026-07-11 00:00:00")),
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
