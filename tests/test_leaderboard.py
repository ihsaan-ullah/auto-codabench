"""Keyless tests for leaderboard aggregation (pure data → data → markdown)."""
from autocodabench.bench import leaderboard, results


def _create_record(spec, agreement, builds):
    return results.new_result(
        benchmark="create", competition="style-trans-fair",
        backend={"spec": spec, "name": "x", "model": None, "endpoint_host": None},
        metrics={"score_agreement_rate": agreement, "bundle_builds": builds,
                 "validate_ok": True})


def _validate_record(spec, recall, precision, f1):
    return results.new_result(
        benchmark="validate", competition="demo-ai-text-detection",
        backend={"spec": spec, "name": "x", "model": None, "endpoint_host": None},
        metrics={"tiers": {
            "deterministic": {"recall": 1.0},
            "judged": {"recall": recall, "precision": precision, "f1": f1,
                       "clean_false_positive_rate": 0.0}}})


def test_aggregate_means_across_runs_per_backbone():
    records = [
        _create_record("claude", 1.0, True),
        _create_record("claude", 0.5, True),     # same backbone → averaged
        _create_record("ollama:llama3.1", 0.0, False),
    ]
    agg = leaderboard.aggregate(records)
    assert agg["n_records"] == 3 and agg["n_skipped"] == 0
    by = {r["backend"]: r for r in agg["create"]}
    assert by["claude"]["runs"] == 2
    assert by["claude"]["score_agreement_rate"] == 0.75   # (1.0 + 0.5)/2
    assert by["claude"]["build_rate"] == 1.0
    assert by["ollama:llama3.1"]["build_rate"] == 0.0
    # Sorted best-first.
    assert agg["create"][0]["backend"] == "claude"


def test_aggregate_validate_tier_and_sorting():
    records = [
        _validate_record("claude", 0.9, 0.9, 0.9),
        _validate_record("weak:model", 0.2, 0.5, 0.3),
    ]
    agg = leaderboard.aggregate(records)
    rows = agg["validate"]
    assert rows[0]["backend"] == "claude"          # higher F1 first
    assert rows[0]["judged_f1"] == 0.9
    assert rows[0]["deterministic_recall"] == 1.0


def test_aggregate_skips_invalid_records():
    bad = {"not": "a record"}
    agg = leaderboard.aggregate([_create_record("claude", 1.0, True), bad])
    assert agg["n_records"] == 1 and agg["n_skipped"] == 1


def test_render_markdown_has_both_sections_and_handles_empty():
    md = leaderboard.render_markdown(leaderboard.aggregate([]))
    assert "create-bench" in md and "validate-bench" in md
    assert "(no runs yet)" in md
    md2 = leaderboard.render_markdown(
        leaderboard.aggregate([_create_record("claude", 1.0, True)]))
    assert "`claude`" in md2


def test_discover_results_skips_gitkeep(tmp_path):
    root = tmp_path / "benchmark"
    d = root / "autocodabench_create_bench" / "results" / "claude"
    d.mkdir(parents=True)
    (d / ".gitkeep").write_text("")
    results.dump(_create_record("claude", 1.0, True), d / "run1.json")
    found = leaderboard.discover_results(root)
    assert len(found) == 1 and found[0].name == "run1.json"
