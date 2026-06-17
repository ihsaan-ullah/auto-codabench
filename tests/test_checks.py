"""Tests for the check framework against the rebuilt demo bundle."""
import shutil

import yaml

from autocodabench.checks import (
    CompetitionFacts,
    Dimension,
    REGISTRY,
    Status,
    Tier,
    checklist_coverage,
    validate_bundle_path,
)


def _statuses(report, check_id):
    return [r.status for r in report.results if r.check_id == check_id]


def _set_yaml(bundle, mutate):
    p = bundle / "competition.yaml"
    comp = yaml.safe_load(p.read_text())
    mutate(comp)
    p.write_text(yaml.safe_dump(comp, sort_keys=False))


def test_demo_bundle_passes_gates(demo_bundle):
    report = validate_bundle_path(demo_bundle)
    assert report.ok
    assert Status.PASS in _statuses(report, "bundle-schema")


def test_zip_validation_equivalent(demo_bundle, tmp_path):
    zip_path = demo_bundle.parent / f"{demo_bundle.name}.zip"
    assert zip_path.is_file()
    report = validate_bundle_path(zip_path)
    assert report.ok


def test_schema_failure_gates(demo_bundle):
    (demo_bundle / "pages" / "overview.md").unlink()
    report = validate_bundle_path(demo_bundle)
    assert not report.ok
    assert Status.FAIL in _statuses(report, "bundle-schema")


def test_missing_starting_kit_is_finding_not_gate(demo_bundle):
    shutil.rmtree(demo_bundle / "starting_kit")
    report = validate_bundle_path(demo_bundle)
    assert report.ok  # advisory, not a gate
    assert Status.FINDING in _statuses(report, "starting-kit")


def test_single_phase_finding(demo_bundle):
    comp_path = demo_bundle / "competition.yaml"
    comp = yaml.safe_load(comp_path.read_text())
    comp["phases"] = comp["phases"][:1]
    comp_path.write_text(yaml.safe_dump(comp, sort_keys=False))
    report = validate_bundle_path(demo_bundle)
    assert Status.FINDING in _statuses(report, "two-phase-structure")
    assert Status.SKIPPED in _statuses(report, "final-phase-submission-limit")


def test_uncapped_dev_phase_finding(demo_bundle):
    comp_path = demo_bundle / "competition.yaml"
    comp = yaml.safe_load(comp_path.read_text())
    comp["phases"][0].pop("max_submissions_per_day")
    comp_path.write_text(yaml.safe_dump(comp, sort_keys=False))
    report = validate_bundle_path(demo_bundle)
    assert Status.FINDING in _statuses(report, "daily-submission-cap")


def test_facts_gate_skips_without_facts(demo_bundle):
    (demo_bundle / "competition_facts.yaml").unlink()
    report = validate_bundle_path(demo_bundle)
    assert _statuses(report, "test-set-size") == [Status.SKIPPED]
    assert _statuses(report, "external-data-rule") == [Status.SKIPPED]


def test_test_set_size_uses_declared_facts(demo_bundle, tmp_path):
    facts = tmp_path / "facts.yaml"
    facts.write_text("anticipated_error_rate: 0.2\ntest_set_size: 1000\n")
    report = validate_bundle_path(demo_bundle, facts_path=facts)
    assert _statuses(report, "test-set-size") == [Status.PASS]


def test_test_set_size_flags_undersized_set(demo_bundle):
    # The shipped facts declare E=0.2 → needs ≥500; the toy set has 40 rows.
    report = validate_bundle_path(demo_bundle)
    assert _statuses(report, "test-set-size") == [Status.FINDING]


def test_attestations_always_surface(demo_bundle):
    report = validate_bundle_path(demo_bundle)
    attested = [r for r in report.results if r.status == Status.ATTESTATION_REQUIRED]
    assert len(attested) >= 3
    # prizes=false in the shipped facts resolves the game-of-skill attestation
    assert _statuses(report, "attest-game-of-skill") == [Status.PASS]


def test_unknown_fact_key_rejected(tmp_path):
    bad = tmp_path / "facts.yaml"
    bad.write_text("not_a_fact: 1\n")
    try:
        CompetitionFacts.from_yaml(bad)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "unknown fact keys" in str(e)


def test_checklist_coverage_lists_all_tiers():
    rows = checklist_coverage()
    tiers = {r["tier"] for r in rows}
    assert tiers == {t.value for t in Tier}
    assert all(r["citation"] for r in rows)


def test_every_check_declares_a_dimension_and_citation():
    """The §7.1 framework invariant: every registered check carries a
    validation dimension (a valid Dimension) and a citation."""
    valid = {d.value for d in Dimension}
    for c in REGISTRY.values():
        assert c.dimension.value in valid, f"{c.id} has no valid dimension"
        assert c.citation, f"{c.id} has no citation"


def test_metric_direction_passes_on_clean_demo(demo_bundle):
    # Demo sorts accuracy/balanced_accuracy descending — both higher-is-better.
    report = validate_bundle_path(demo_bundle)
    assert Status.FINDING not in _statuses(report, "metric-direction-semantics")
    assert Status.PASS in _statuses(report, "metric-direction-semantics")


def test_metric_direction_flags_inverted_sort(demo_bundle):
    _set_yaml(demo_bundle,
              lambda c: c["leaderboards"][0]["columns"][0].__setitem__("sorting", "asc"))
    report = validate_bundle_path(demo_bundle)
    assert Status.FINDING in _statuses(report, "metric-direction-semantics")
    assert report.ok  # advisory, not a gate


def test_leaderboard_key_collision_gates(demo_bundle):
    _set_yaml(demo_bundle, lambda c: c["leaderboards"][0]["columns"][1].__setitem__(
        "key", c["leaderboards"][0]["columns"][0]["key"]))
    report = validate_bundle_path(demo_bundle)
    assert Status.FAIL in _statuses(report, "leaderboard-well-formed")
    assert not report.ok


def test_reference_data_leak_gates(demo_bundle):
    (demo_bundle / "input_data").mkdir(exist_ok=True)
    shutil.copy(demo_bundle / "reference_data" / "truth.csv",
                demo_bundle / "input_data" / "truth.csv")
    report = validate_bundle_path(demo_bundle)
    assert Status.FAIL in _statuses(report, "reference-data-not-participant-visible")
    assert not report.ok


def test_docker_latest_tag_is_finding(demo_bundle):
    _set_yaml(demo_bundle,
              lambda c: c.__setitem__("docker_image", "codalab/codalab-legacy:latest"))
    report = validate_bundle_path(demo_bundle)
    assert Status.FINDING in _statuses(report, "docker-image-pinned")
    assert report.ok  # advisory, not a gate


# --- judged tier plumbing (keyless: a stub backend stands in for the LLM) ----

class _StubResult:
    def __init__(self, text):
        self.ok, self.error, self.status, self.final_text = True, None, "ok", text


class _StubBackend:
    def __init__(self, text):
        self._text = text

    async def run(self, task):
        return _StubResult(self._text)


def _run_judged(demo_bundle, text):
    import asyncio
    from autocodabench.checks.base import CheckContext
    from autocodabench.checks.judged import run_judged_checks
    ctx = CheckContext.from_bundle_dir(demo_bundle)
    return asyncio.run(run_judged_checks(ctx, _StubBackend(text)))


def test_all_judged_checks_registered():
    from autocodabench.checks.judged import JudgedCheck
    judged = [c for c in REGISTRY.values() if isinstance(c, JudgedCheck)]
    assert len(judged) >= 6  # docs-consistency + the five book-derived rubrics
    assert all(c.citation and c.dimension for c in judged)


def test_judged_findings_are_advisory_not_gates(demo_bundle):
    results = _run_judged(demo_bundle, '{"findings":[{"where":"terms.md","message":"x"}]}')
    assert len(results) >= 6
    # Judged checks emit FINDINGs only — never FAIL, so they never gate. Some
    # judged checks are fact-gated (e.g. the human-judging protocol) and SKIP
    # when the fact is undeclared — information, not a gate.
    assert Status.FAIL not in {r.status for r in results}
    ran = [r for r in results if r.status != Status.SKIPPED]
    assert ran and all(r.status == Status.FINDING for r in ran)


def test_judged_empty_findings_pass(demo_bundle):
    results = _run_judged(demo_bundle, '{"findings":[]}')
    # Checks that actually ran pass; fact-gated checks SKIP (never silently pass).
    ran = [r for r in results if r.status != Status.SKIPPED]
    assert ran and all(r.status == Status.PASS for r in ran)


def test_attestations_get_llm_tailored_detail(demo_bundle):
    """With a backend, attestations stay human-confirmed (📋) but carry a
    bundle-tailored note instead of the generic statement; deterministic
    auto-pass (prizes=false) is preserved without an LLM verdict."""
    import asyncio
    from autocodabench.checks.base import CheckContext
    from autocodabench.checks.attestations import run_attestation_assessments
    ctx = CheckContext.from_bundle_dir(
        demo_bundle, facts=CompetitionFacts.discover(demo_bundle))
    note = "The data page states CC0 but no persistent DOI — add one before launch."
    results = asyncio.run(run_attestation_assessments(ctx, _StubBackend(note)))
    att = [r for r in results if r.status == Status.ATTESTATION_REQUIRED]
    assert att and all(note in r.message for r in att)  # tailored, not generic
    gos = [r for r in results if r.check_id == "attest-game-of-skill"]
    assert gos and gos[0].status == Status.PASS  # prizes=false → auto-pass, no LLM


def test_judged_validate_replaces_attestations_no_duplicates(demo_bundle):
    from autocodabench.checks import REGISTRY, Tier
    report = validate_bundle_path(demo_bundle, judged=True,
                                  backend=_StubBackend('{"findings":[]}'))
    att_ids = [r.check_id for r in report.results
               if REGISTRY.get(r.check_id) and REGISTRY[r.check_id].tier == Tier.ATTESTATION]
    assert att_ids and len(att_ids) == len(set(att_ids))  # replaced, not duplicated


def test_terminal_render_is_box_tables_by_type(demo_bundle):
    """The CLI prints box tables grouped by validation type; the markdown (web)
    splits the same way with hyperlinked citations."""
    from autocodabench.checks import render_report_terminal
    report = validate_bundle_path(demo_bundle)
    txt = render_report_terminal(report)
    assert "Bundle validation —" in txt
    assert "[1. Structural]" in txt                 # grouped by type
    assert "LLM?" in txt                            # LLM-as-a-judge column
    assert "│" in txt and "┌" in txt                # box table
    assert "autocodabench checks" in txt            # pointer at the end
    # User-friendly: internal ids are not shown.
    assert "bundle-schema" not in txt
    assert "Bundle schema and file references" in txt
    # Markdown: per-type sections + LLM column + a clickable citation.
    md = report.to_markdown()
    assert "## 🔎 Checks" in md and "### 1. Structural" in md
    assert "| Status | Short Description | LLM-as-a-judge | Detail |" in md
    assert "](https://" in md  # hyperlinked citation


def test_report_markdown_renders(demo_bundle):
    report = validate_bundle_path(demo_bundle)
    md = report.to_markdown()
    assert "Bundle validation" in md
    # Unified status-table format (shared by CLI + web): a Checks table with
    # status emoji; attestations surface as 📋 rows rather than a prose header.
    assert "## 🔎 Checks" in md
    assert "📋" in md


def test_report_markdown_design_scorecard(demo_bundle):
    """A passed-in design assessment renders the Phase-1 scorecard (Table A)."""
    report = validate_bundle_path(demo_bundle)
    assessment = {
        "schema_version": 1,
        "sections": [
            {"id": 1, "key": "task", "name": "Task formulation",
             "status": "ok", "note": "clear"},
            {"id": 2, "key": "data", "name": "Data & splits",
             "status": "missing", "note": "no split"},
        ],
    }
    md = report.to_markdown(design_assessment=assessment)
    assert "Design assessment" in md
    assert "Task formulation" in md
    assert "❌" in md  # the 'missing' section
