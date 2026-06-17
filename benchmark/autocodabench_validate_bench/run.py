#!/usr/bin/env python3
"""validate-bench — measure how well the validator catches authoring defects.

A pure-SDK orchestrator. It seeds each known defect from
``autocodabench.bench.defects`` into an otherwise-clean bundle, runs
``validate_bundle_path``, and records whether the expected check fired —
separating two tiers:

  - **deterministic** (code computes PASS/FAIL): backbone-independent sanity
    baseline. Fully keyless and Docker-free — runs with no ``--backend``.
  - **judged** (an LLM grades a rubric): the backbone-sensitive measurement.
    Needs ``--backend``; stochastic, so use ``--runs >= 3`` for reporting.

It also runs the validator on an unmutated bundle to measure the judged tier's
false-positive rate, then emits a canonical ``bench.results`` record
(``benchmark="validate"``) with precision/recall/F1 per tier.

Usage (the deterministic tier needs nothing; the judged tier takes any backbone):
  python benchmark/autocodabench_validate_bench/run.py                       # deterministic only, keyless
  python benchmark/autocodabench_validate_bench/run.py --backend claude:claude-opus-4-8 --runs 3
  python benchmark/autocodabench_validate_bench/run.py --backend ollama:llama3.1 --runs 3
  python benchmark/autocodabench_validate_bench/run.py --backend openai:gpt-4o-mini --runs 5

Results are written under the run's session dir AND copied to
benchmark/autocodabench_validate_bench/results/<backbone-tag>/<run-id>.json.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

from autocodabench.backends import resolve_backend
from autocodabench.bench import defects, results
from autocodabench.checks import validate_bundle_path
from autocodabench.run_log import open_session

INSTRUMENT_VERSION = {"defect_library": "v1"}
# The clean instrument is the shipped demo bundle (rebuilt from its fixture).
COMPETITION = defects.SLUG
# The judged check whose false-positive rate we probe on a clean bundle.
_JUDGED_CHECK = "judged-docs-config-consistency"


def _run_defects(clean: Path, workdir: Path, *, backend, judged_runs: int,
                 defect_list: list) -> list[dict]:
    """Seed every defect and record the catch count per tier."""
    rows: list[dict] = []
    for d in defect_list:
        judged = d.tier == "judged"
        if judged and backend is None:
            rows.append({"defect": d.id, "tier": d.tier, "expect_check": d.expect_check,
                         "runs": 0, "caught": None, "catch_rate": None,
                         "description": d.description, "note": "skipped — no --backend"})
            print(f"  {d.id:<32} {d.tier:<13} skipped (no backend)")
            continue
        n = judged_runs if judged else 1   # deterministic tier is deterministic
        caught = 0
        for i in range(n):
            seeded = defects.seed_defect(clean, d, workdir / f"{d.id}-{i}")
            report = validate_bundle_path(seeded, execute=False,
                                          judged=judged, backend=backend if judged else None)
            if defects.flagged(report, d.expect_check):
                caught += 1
        rows.append({"defect": d.id, "tier": d.tier, "expect_check": d.expect_check,
                     "runs": n, "caught": caught, "catch_rate": caught / n,
                     "description": d.description})
        print(f"  {d.id:<32} {d.tier:<13} {caught}/{n}")
    return rows


def _clean_false_positives(clean: Path, *, backend, runs: int) -> dict | None:
    """How often the judged tier flags an unmutated bundle (precision signal)."""
    if backend is None or runs <= 0:
        return None
    hits = 0
    for _ in range(runs):
        report = validate_bundle_path(clean, execute=False, judged=True, backend=backend)
        if defects.flagged(report, _JUDGED_CHECK):
            hits += 1
    print(f"  clean-bundle judged false positives: {hits}/{runs}")
    return {"runs": runs, "false_positives": hits, "fp_rate": hits / runs}


def _render_report(record: dict) -> str:
    m = record["metrics"]
    b = record["backend"]
    lines = [
        f"# validate-bench — backbone: `{b.get('spec') or b.get('name') or 'deterministic only'}`",
        "",
        f"- competition (clean instrument): `{record['competition']}`",
        f"- generated_at: {record['generated_at']}",
        f"- runs per judged condition: {m['runs_per_judged_condition']}",
        "",
        "## Per-tier precision / recall / F1",
        "",
        "| tier | defects | recall (catch) | precision | F1 | clean FP rate |",
        "|------|---------|----------------|-----------|----|---------------|",
    ]
    for tier in defects.TIERS:
        t = m["tiers"].get(tier)
        if not t:
            lines.append(f"| {tier} | — | skipped | — | — | — |")
            continue
        def f(x): return "—" if x is None else f"{x:.3f}"
        lines.append(f"| {tier} | {t['defects_evaluated']} | {f(t.get('recall'))} "
                     f"| {f(t.get('precision'))} | {f(t.get('f1'))} "
                     f"| {f(t.get('clean_false_positive_rate'))} |")
    lines += ["", "## Per-defect", "",
              "| defect | tier | expected check | caught |",
              "|--------|------|----------------|--------|"]
    for r in m["per_defect"]:
        caught = "skipped" if r["caught"] is None else f"{r['caught']}/{r['runs']}"
        lines.append(f"| {r['defect']} | {r['tier']} | `{r['expect_check']}` | {caught} |")
    return "\n".join(lines) + "\n"


def _build_instrument(workdir: Path, instrument: str | None):
    """Return ``(clean_bundle_dir, competition_label, candidate_defects, skipped)``.

    ``instrument`` is None for the shipped demo (all defects apply), or a path to
    a competition's ``ground_truth/bundle`` — in which case the defect set
    self-adapts to that bundle and the skipped defects are reported."""
    if instrument is None:
        clean = defects.build_clean_bundle(workdir)
        return clean, COMPETITION, list(defects.DEFECTS), []
    clean = defects.build_clean_bundle_from_dir(instrument, workdir)
    label = Path(instrument).resolve().parent.parent.name or Path(instrument).name
    applicable, skipped = defects.applicable_defects(clean, workdir / "_probe")
    return clean, label, applicable, skipped


def run_once(*, backend, backend_spec: str | None, model: str | None,
             judged_runs: int, hardware_tag: str | None,
             instrument: str | None = None) -> dict:
    session = open_session(kind="validate-bench")
    print(f"  session: {session.path}")
    with tempfile.TemporaryDirectory(prefix="validate-bench-") as tmp:
        workdir = Path(tmp)
        clean, competition, defect_list, skipped = _build_instrument(workdir, instrument)
        if skipped:
            print(f"  instrument '{competition}': {len(defect_list)} applicable defect(s), "
                  f"{len(skipped)} not applicable")
            for s in skipped:
                print(f"    - {s['defect']:<30} skipped: {s['reason']}")
        rows = _run_defects(clean, workdir, backend=backend, judged_runs=judged_runs,
                            defect_list=defect_list)
        clean_fp = _clean_false_positives(clean, backend=backend, runs=judged_runs)

    fp_count = clean_fp["false_positives"] if clean_fp else 0
    fp_runs = clean_fp["runs"] if clean_fp else 0
    metrics = {
        "tiers": defects.summarize(rows, clean_false_positives=fp_count, clean_runs=fp_runs),
        "per_defect": rows,
        "defects_not_applicable": skipped,
        "judged_false_positive": clean_fp,
        "n_defects": len(defect_list),
        "runs_per_judged_condition": judged_runs,
    }
    record = results.new_result(
        benchmark="validate", competition=competition,
        backend=results.backend_descriptor(
            backend, spec=backend_spec or "deterministic-only", model=model),
        metrics=metrics, run_id=session.session_id, hardware_tag=hardware_tag,
        instrument_version=INSTRUMENT_VERSION, git_sha=session.git_sha)

    results.dump(record, session.path / "results.json")
    (session.path / "run_report.md").write_text(_render_report(record), encoding="utf-8")
    tag = results.backend_tag(backend_spec or "deterministic-only")
    results.dump(record, RESULTS / tag / f"{session.session_id}.json")
    return record


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default=None,
                    help="LLM backbone for the judged tier: claude:<model> "
                         "(e.g. claude:claude-opus-4-8), ollama:<model>, openai:<model>, "
                         "URL#model. Claude requires an explicit model. "
                         "Omit --backend entirely to run the (keyless) deterministic tier only.")
    ap.add_argument("--model", default=None, help="model override for the backend")
    ap.add_argument("--runs", type=int, default=3,
                    help="repetitions per judged condition (judged tier is "
                         "stochastic; >=3 recommended). Default 3.")
    ap.add_argument("--hardware-tag", default=None,
                    help="optional free-text hardware label recorded in results")
    ap.add_argument("--instrument", default=None, metavar="BUNDLE_DIR",
                    help="path to a clean competition ground_truth/bundle to use as "
                         "the instrument instead of the shipped demo. Only the bundle "
                         "is copied (never sample_submissions/expected_result.json), and "
                         "the defect set self-adapts to it. Omit to use the demo.")
    args = ap.parse_args(argv)

    if args.backend:
        from autocodabench.bench.cli import require_explicit_model
        require_explicit_model(args.backend, args.model)
    backend = resolve_backend(args.backend, model=args.model) if args.backend else None
    print(f"validate-bench · backend={args.backend or 'deterministic-only'} "
          f"· instrument={args.instrument or 'demo'} · {args.runs} judged run(s)")
    record = run_once(backend=backend, backend_spec=args.backend, model=args.model,
                      judged_runs=args.runs, hardware_tag=args.hardware_tag,
                      instrument=args.instrument)
    t = record["metrics"]["tiers"]
    for tier in defects.TIERS:
        tm = t.get(tier)
        if tm:
            print(f"  → {tier}: recall={tm.get('recall')} precision={tm.get('precision')} "
                  f"f1={tm.get('f1')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
