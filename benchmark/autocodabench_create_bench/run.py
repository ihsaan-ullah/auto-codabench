#!/usr/bin/env python3
"""create-bench — measure PDF-proposal → working-bundle translation fidelity.

A pure-SDK orchestrator (the successor to the old `claude -p` shell-out
harness). For one competition and one LLM backbone it:

  1. Plan + build + self-validate the bundle from the proposal PDF, by
     calling the library's own `create_async` (plan → build → execution
     checks). The model only ever sees `input/**` (proposal + sample_data).
  2. For each ground-truth submission, run the reformat-and-run phase
     (`reformat_and_run_async`) — adapt + score it through the built bundle.
     The model never sees `expected_result.json`.
  3. Deterministically audit each produced score against
     `expected_result.json` within tolerance (`bench.audit`).
  4. Emit a canonical `bench.results` record + a human `run_report.md`.

Data-leakage isolation is a code invariant here, not prompt discipline:
each phase only ever receives the paths it is allowed to see.

Usage (any OpenAI-compatible backbone works; Ollama is keyless/offline):
  python benchmark/autocodabench_create_bench/run.py --competition style-trans-fair --backend claude:claude-opus-4-8
  python benchmark/autocodabench_create_bench/run.py --competition style-trans-fair --backend ollama:llama3.1 --runs 3
  python benchmark/autocodabench_create_bench/run.py --competition style-trans-fair --backend openai:gpt-4o

Requires a Docker daemon (the bundle is executed exactly as Codabench does).
Results are written under the run's session dir AND copied to
benchmark/autocodabench_create_bench/results/<backbone-tag>/<run-id>.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPETITIONS = HERE / "competitions"
RESULTS = HERE / "results"

from autocodabench.agent.pipeline import create_async
from autocodabench.agent.reformat import reformat_and_run_async
from autocodabench.backends import resolve_backend
from autocodabench.bench import audit, missing_info, report, results
from autocodabench.checks.base import Status
from autocodabench.run_log import open_session

INSTRUMENT_VERSION = {"competition_set": "v1"}


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

def discover_submissions(comp_dir: Path) -> list[dict]:
    """Each ground-truth submission with its blind submission dir + target."""
    root = comp_dir / "ground_truth" / "sample_submissions"
    subs = []
    for sub in sorted(p for p in root.glob("*") if p.is_dir()):
        expected_path = sub / "expected_result.json"
        submission = sub / "submission"
        if not expected_path.is_file() or not submission.is_dir():
            continue
        subs.append({
            "label": sub.name,
            "submission_dir": submission,
            "expected": json.loads(expected_path.read_text(encoding="utf-8")),
        })
    return subs


def check_preconditions(comp_dir: Path) -> tuple[Path, list[dict]]:
    pdf = comp_dir / "input" / "report.pdf"
    sample_data = comp_dir / "input" / "sample_data"
    if not pdf.is_file():
        raise SystemExit(f"missing proposal PDF: {pdf}\n"
                         "(populate the instrument per its README — heavy data is gitignored)")
    subs = discover_submissions(comp_dir)
    if not subs:
        raise SystemExit(f"no ground-truth submissions with expected_result.json under {comp_dir}")
    return sample_data, subs


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------

def _exec_status(rep, check_id: str):
    for r in rep.results:
        if r.check_id == check_id:
            if r.status == Status.PASS:
                return True
            if r.status == Status.SKIPPED:
                return None
            return False
    return None


def _plan_sections_covered(plan_path: Path | None) -> int | None:
    if not plan_path or not plan_path.is_file():
        return None
    text = plan_path.read_text(encoding="utf-8", errors="replace").lower()
    keywords = ["task", "data", "metric", "baseline", "rule", "ethic", "schedule"]
    return sum(1 for k in keywords if k in text)


def _aggregate_missing_info(session_dir: Path) -> dict:
    reports = []
    for glob in ("**/missing_info_report.json", "**/missing_info_inventory.json"):
        for p in missing_info.discover_reports(session_dir, glob):
            r = missing_info.load_report(p)
            if r is not None:
                reports.append(r)
    return missing_info.aggregate(reports) if reports else {}


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

async def run_once(*, comp: str, comp_dir: Path, sample_data: Path,
                   subs: list[dict], backend, backend_spec: str | None,
                   model: str | None, hardware_tag: str | None) -> dict:
    pdf = comp_dir / "input" / "report.pdf"
    session = open_session(kind="create-bench")
    print(f"  session: {session.path}")

    # Phase-1 research capability (OpenAlex + Kaggle MCP + web search). Default
    # on; resolved against the backbone so the record states which sources this
    # LLM could actually reach — only the Claude backend can use external MCP /
    # web tools, and that asymmetry must be recorded for fair cross-backbone
    # comparison, not hidden.
    from autocodabench.agent.research import ResearchConfig, resolve as resolve_research
    research_cfg = ResearchConfig()
    research_resolved = resolve_research(research_cfg, backend=backend)
    print(f"  research: backend_supported={research_resolved.backend_supported} "
          f"effective={research_resolved.effective()}")

    # Phase 1-3: plan + build + self-validate, straight from the library.
    create = await create_async(
        idea=None, pdf=pdf, data=str(sample_data),
        backend=backend, model=model, validate=True, session=session,
        research=research_cfg)

    rep = create.validation
    metrics: dict = {
        "plan_ok": bool(create.plan and create.plan.ok),
        "plan_sections_covered": _plan_sections_covered(create.plan_path),
        "bundle_builds": create.bundle_dir is not None,
        "validate_ok": bool(rep.ok) if rep is not None else None,
        "validate_counts": rep.counts if rep is not None else None,
        "execution": {
            "baseline_pass": _exec_status(rep, "baseline-execution") if rep else None,
            "baseline_attempts": None,   # build self-validation attempts not surfaced (Stage 1)
            "notebook_pass": _exec_status(rep, "starting-kit-execution") if rep else None,
            "notebook_attempts": None,
        },
        "submissions": [],
        "score_agreement_rate": None,
    }

    # Phase 4: score each GT submission, then deterministically audit it.
    if create.bundle_dir is not None and create.build_dir is not None:
        for s in subs:
            out_dir = session.path / "reformat_run" / s["label"]
            rr = await reformat_and_run_async(
                bundle_dir=create.bundle_dir, build_run_dir=create.build_dir,
                submission_dir=s["submission_dir"], out_dir=out_dir,
                backend=backend, slug=Path(create.bundle_dir).name,
                label=s["label"], model=model)
            verdict = audit.audit_submission(rr.final or {"status": "fail", "scores": None},
                                             s["expected"], sub_label=s["label"])
            metrics["submissions"].append({
                "sub": s["label"],
                "reformat_status": "pass" if rr.ok else "fail",
                "reformat_attempts": (rr.final or {}).get("attempts_used"),
                "verdict": verdict["verdict"],
                "expected": verdict["expected_score"],
                "actual": verdict["actual_score"],
                "delta": verdict["delta"],
                "within_tolerance": verdict["within_tolerance"],
            })
            print(f"    {s['label']}: reformat={'ok' if rr.ok else 'fail'} "
                  f"verdict={verdict['verdict']} "
                  f"Δ={verdict['delta']}")

        within = [s for s in metrics["submissions"] if s["within_tolerance"]]
        metrics["score_agreement_rate"] = len(within) / len(metrics["submissions"])

    metrics["missing_info_totals"] = _aggregate_missing_info(session.path)

    record = results.new_result(
        benchmark="create", competition=comp,
        backend=results.backend_descriptor(backend, spec=backend_spec, model=model),
        metrics=metrics, run_id=session.session_id,
        cost_usd=create.total_cost_usd, hardware_tag=hardware_tag,
        instrument_version=INSTRUMENT_VERSION, git_sha=session.git_sha,
        research={
            "requested": research_cfg.to_dict(),
            "backend_supported": research_resolved.backend_supported,
            "effective": research_resolved.effective(),
            "sources": research_resolved.sources,
        })

    # Write into the session dir AND the contributable results partition.
    results.dump(record, session.path / "results.json")
    (session.path / "run_report.md").write_text(
        report.render_run_report(record), encoding="utf-8")
    tag = results.backend_tag(backend_spec)
    results.dump(record, RESULTS / tag / f"{session.session_id}.json")
    return record


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--competition", default="style-trans-fair",
                    help="instrument under competitions/ (default: style-trans-fair)")
    ap.add_argument("--backend", default=None,
                    help="claude:<model> (e.g. claude:claude-opus-4-8), ollama:<model>, "
                         "openai:<model>, URL#model. Claude requires an explicit model "
                         "so the leaderboard records exactly which one ran.")
    ap.add_argument("--model", default=None, help="model override for the backend")
    ap.add_argument("--runs", type=int, default=1, help="repetitions (creation is stochastic)")
    ap.add_argument("--hardware-tag", default=None,
                    help="optional free-text hardware label recorded in results (e.g. jean-zay-a100)")
    args = ap.parse_args(argv)

    comp_dir = COMPETITIONS / args.competition
    if not comp_dir.is_dir():
        print(f"unknown competition: {args.competition} (looked in {COMPETITIONS})",
              file=sys.stderr)
        return 2
    sample_data, subs = check_preconditions(comp_dir)
    from autocodabench.bench.cli import require_explicit_model
    require_explicit_model(args.backend, args.model)
    backend = resolve_backend(args.backend, model=args.model)
    print(f"create-bench · {args.competition} · backend={args.backend or 'claude'} "
          f"· {len(subs)} submission(s) · {args.runs} run(s)")

    for i in range(args.runs):
        print(f"\n[run {i + 1}/{args.runs}]")
        record = asyncio.run(run_once(
            comp=args.competition, comp_dir=comp_dir, sample_data=sample_data,
            subs=subs, backend=backend, backend_spec=args.backend,
            model=args.model, hardware_tag=args.hardware_tag))
        m = record["metrics"]
        print(f"  → builds={m['bundle_builds']} validate_ok={m['validate_ok']} "
              f"score_agreement={m['score_agreement_rate']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
