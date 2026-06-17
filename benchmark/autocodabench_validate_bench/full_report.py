#!/usr/bin/env python3
"""validate-bench — consolidated coverage report across instruments and tiers.

Measures, for the autocodabench validator:

  • DETERMINISTIC tier (keyless, free, reproducible): per-defect catch and
    per-tier recall on TWO instruments — the shipped demo bundle and a real
    competition's ground_truth/bundle (default: style-trans-fair). The defect
    set self-adapts to each instrument; defects that do not apply are reported
    with reasons (no silent truncation).

  • JUDGED tier (needs --backend; LLM grades a rubric, so it is stochastic):
    per-defect catch rate over N runs (the consistency signal) and the
    per-check false-positive rate on the clean bundle. To stay cheap, each
    judged defect is scored by calling ONLY its target check (one LLM call),
    not the whole judged tier.

Data-leakage isolation is preserved by construction: only the bundle directory
is copied into a tempdir; a competition's sample_submissions/expected_result are
never placed where the validator can read them.

Usage:
  python benchmark/autocodabench_validate_bench/full_report.py                       # deterministic only
  python benchmark/autocodabench_validate_bench/full_report.py --backend claude:claude-opus-4-8 --judged-runs 3
  python benchmark/autocodabench_validate_bench/full_report.py --instrument <path/to/ground_truth/bundle>
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_GT = (REPO / "benchmark" / "autocodabench_create_bench" / "competitions"
              / "style-trans-fair" / "ground_truth" / "bundle")

from autocodabench.bench import defects
from autocodabench.checks import REGISTRY, Status, checklist_coverage, validate_bundle_path
from autocodabench.checks.base import CheckContext
from autocodabench.checks.judged import JudgedCheck


# --------------------------------------------------------------------------
# Deterministic tier — keyless
# --------------------------------------------------------------------------

def _deterministic_on(clean: Path, workdir: Path, label: str) -> dict:
    det = defects.defects_for_tier("deterministic")
    applicable, skipped = defects.applicable_defects(clean, workdir / "_probe", det)
    rows = []
    for d in applicable:
        seeded = defects.seed_defect(clean, d, workdir / f"{label}-{d.id}")
        report = validate_bundle_path(seeded, execute=False)
        rows.append({"defect": d.id, "expect_check": d.expect_check,
                     "caught": defects.flagged(report, d.expect_check),
                     "description": d.description})
    caught = sum(1 for r in rows if r["caught"])
    return {"label": label, "rows": rows, "skipped": skipped,
            "n": len(rows), "caught": caught,
            "recall": (caught / len(rows)) if rows else None}


# --------------------------------------------------------------------------
# Judged tier — needs a backend; one LLM call per (check, sample)
# --------------------------------------------------------------------------

def _judged_fires(check: JudgedCheck, bundle_dir: Path, backend) -> bool:
    ctx = CheckContext.from_bundle_dir(bundle_dir)
    results = asyncio.run(check.run_judged(ctx, backend))
    return any(r.status == Status.FINDING for r in results)


def _judged_report(clean: Path, workdir: Path, backend, runs: int) -> dict:
    judged_checks = {c.id: c for c in REGISTRY.values() if isinstance(c, JudgedCheck)}
    # Per-check false positives on the clean bundle (precision signal).
    clean_fp = {}
    for cid, check in judged_checks.items():
        fires = sum(1 for _ in range(runs) if _judged_fires(check, clean, backend))
        clean_fp[cid] = {"runs": runs, "false_positives": fires, "fp_rate": fires / runs}
        print(f"  clean FP  {cid:<34} {fires}/{runs}")
    # Per-defect recall over N runs (catch consistency).
    rows = []
    for d in defects.defects_for_tier("judged"):
        check = judged_checks.get(d.expect_check)
        if check is None:
            continue
        caught = 0
        for i in range(runs):
            seeded = defects.seed_defect(clean, d, workdir / f"judged-{d.id}-{i}")
            if _judged_fires(check, seeded, backend):
                caught += 1
        rows.append({"defect": d.id, "expect_check": d.expect_check,
                     "runs": runs, "caught": caught, "catch_rate": caught / runs,
                     "description": d.description})
        print(f"  recall    {d.id:<34} {caught}/{runs}")
    return {"runs": runs, "clean_fp": clean_fp, "rows": rows}


# --------------------------------------------------------------------------
# Coverage matrix (dimension × tier) from the live registry
# --------------------------------------------------------------------------

def _coverage_matrix() -> tuple[list[str], list[str], dict]:
    rows = checklist_coverage()
    dims = [t for _, t in sorted({(r["type_no"], r["type"]) for r in rows})]
    tiers = ["deterministic", "judged", "attestation"]
    grid = {(d, t): 0 for d in dims for t in tiers}
    for r in rows:
        grid[(r["type"], r["tier"])] += 1
    return dims, tiers, grid


# --------------------------------------------------------------------------
# Report rendering
# --------------------------------------------------------------------------

def _render(det_results: list[dict], judged: dict | None, *, backend_spec: str | None,
            generated_at: str) -> str:
    L = ["# autocodabench validator — coverage report", "",
         f"_Generated: {generated_at}_  ·  "
         f"backbone (judged tier): `{backend_spec or 'not run'}`", "",
         "This report measures how reliably `autocodabench validate` catches "
         "seeded authoring defects, by tier, on each instrument. Deterministic "
         "checks are backbone-independent and run keylessly; judged checks are "
         "LLM-graded and reported with a per-defect catch rate over repeated runs "
         "(consistency) plus the clean-bundle false-positive rate.", ""]

    # Coverage matrix
    dims, tiers, grid = _coverage_matrix()
    total = sum(grid.values())
    L += [f"## 1. Suite coverage ({total} checks)", "",
          "Checks per validation dimension × epistemic tier.", "",
          "| Dimension | " + " | ".join(t[:4] for t in tiers) + " | total |",
          "|---|" + "|".join(":--:" for _ in tiers) + "|:--:|"]
    for d in dims:
        cells = [str(grid[(d, t)] or "·") for t in tiers]
        L.append(f"| {d} | " + " | ".join(cells) + f" | {sum(grid[(d,t)] for t in tiers)} |")
    L.append("")

    # Deterministic tier
    L += ["## 2. Deterministic tier — per-instrument catch (keyless)", ""]
    for res in det_results:
        rec = "—" if res["recall"] is None else f"{res['recall']:.3f}"
        L += [f"### Instrument: `{res['label']}`  ·  recall {res['caught']}/{res['n']} = {rec}", "",
              "| defect | target check | caught |",
              "|---|---|:--:|"]
        for r in res["rows"]:
            L.append(f"| {r['defect']} | `{r['expect_check']}` | "
                     f"{'✅' if r['caught'] else '❌'} |")
        if res["skipped"]:
            L += ["", f"_Not applicable to this instrument ({len(res['skipped'])}):_ "
                  + "; ".join(f"`{s['defect']}` ({s['reason']})" for s in res["skipped"])]
        L.append("")

    # Judged tier
    L += ["## 3. Judged tier — catch rate + consistency", ""]
    if judged is None:
        L += ["_Not run — pass `--backend` (e.g. `claude:claude-opus-4-8`) to "
              "measure the LLM-judged tier._", ""]
    else:
        n = judged["runs"]
        L += [f"Each judged defect was seeded and validated **{n} times**; the catch "
              f"rate is the consistency signal. Clean-bundle false positives are over "
              f"{n} runs.", "",
              "**Per-defect recall (catch rate over runs):**", "",
              "| defect | target check | catch rate |",
              "|---|---|:--:|"]
        rec_sum = 0.0
        for r in judged["rows"]:
            rec_sum += r["catch_rate"]
            L.append(f"| {r['defect']} | `{r['expect_check']}` | "
                     f"{r['caught']}/{r['runs']} = {r['catch_rate']:.2f} |")
        if judged["rows"]:
            L += ["", f"_Mean judged recall: {rec_sum/len(judged['rows']):.3f}._"]
        L += ["", "**Per-check clean-bundle false-positive rate:**", "",
              "| judged check | FP rate |", "|---|:--:|"]
        for cid, fp in judged["clean_fp"].items():
            L.append(f"| `{cid}` | {fp['false_positives']}/{fp['runs']} = {fp['fp_rate']:.2f} |")
        L.append("")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default=None,
                    help="LLM backbone for the judged tier (e.g. claude:claude-opus-4-8). "
                         "Omit to run the deterministic tier only.")
    ap.add_argument("--model", default=None)
    ap.add_argument("--judged-runs", type=int, default=3,
                    help="repetitions per judged condition (consistency). Default 3.")
    ap.add_argument("--instrument", default=str(DEFAULT_GT),
                    help="path to a ground_truth/bundle used as the second instrument")
    ap.add_argument("--out", default=str(HERE / "COVERAGE_REPORT.md"))
    args = ap.parse_args(argv)

    backend = None
    if args.backend:
        from autocodabench.backends import resolve_backend
        from autocodabench.bench.cli import require_explicit_model
        require_explicit_model(args.backend, args.model)
        backend = resolve_backend(args.backend, model=args.model)

    det_results: list[dict] = []
    judged = None
    with tempfile.TemporaryDirectory(prefix="coverage-") as tmp:
        wd = Path(tmp)
        print("deterministic · demo instrument")
        demo = defects.build_clean_bundle(wd / "demo-build")
        det_results.append(_deterministic_on(demo, wd / "demo", "demo"))

        gt = Path(args.instrument)
        if (gt / "competition.yaml").is_file():
            label = gt.resolve().parent.parent.name or gt.name
            print(f"deterministic · {label} instrument")
            clean_gt = defects.build_clean_bundle_from_dir(gt, wd / "gt-build")
            det_results.append(_deterministic_on(clean_gt, wd / "gt", label))
        else:
            print(f"(skipping second instrument — not a bundle: {gt})")

        if backend is not None:
            print(f"judged · demo instrument · {args.judged_runs} run(s) each")
            judged = _judged_report(demo, wd / "demo-judged", backend, args.judged_runs)

    import datetime as _dt  # only for the report stamp (not used in logic)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md = _render(det_results, judged, backend_spec=args.backend, generated_at=stamp)
    Path(args.out).write_text(md, encoding="utf-8")
    print(f"\nwrote {args.out}")
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
