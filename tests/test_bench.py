"""Keyless tests for the bench evaluation library + reformat JSON parsing."""
import json

from autocodabench.bench import audit, missing_info, report, results
from autocodabench.agent.reformat import _extract_last_json, _json_objects


# --- audit -----------------------------------------------------------------

EXPECTED = {"metric": "balanced_accuracy", "score": 0.90, "tolerance": 0.01}


def test_audit_pass_within_tolerance():
    final = {"status": "pass", "scores": {"balanced_accuracy": 0.905},
             "attempts_used": 1}
    v = audit.audit_submission(final, EXPECTED, sub_label="sub_1")
    assert v["verdict"] == audit.PASS
    assert v["within_tolerance"] is True
    assert abs(v["delta"] - 0.005) < 1e-9
    assert audit.audit_status(v) == "pass"


def test_audit_fail_outside_tolerance():
    final = {"status": "pass", "scores": {"balanced_accuracy": 0.80}}
    v = audit.audit_submission(final, EXPECTED)
    assert v["verdict"] == audit.FAIL
    assert v["within_tolerance"] is False
    assert audit.audit_status(v) == "fail"


def test_audit_no_score_when_status_fail():
    v = audit.audit_submission({"status": "fail", "scores": None,
                                "error": "boom"}, EXPECTED)
    assert v["verdict"] == audit.NO_SCORE
    assert v["within_tolerance"] is None
    assert "boom" in v["error_summary"]


def test_audit_metric_mismatch():
    final = {"status": "pass", "scores": {"accuracy": 0.9}}
    v = audit.audit_submission(final, EXPECTED)
    assert v["verdict"] == audit.METRIC_MISMATCH
    assert v["within_tolerance"] is False


def test_audit_primary_score_key_precedence():
    expected = {"metric": "Balanced Accuracy", "primary_score_key": "bal_acc",
                "score": 0.5, "tolerance": 0.0}
    final = {"status": "pass", "scores": {"bal_acc": 0.5}}
    v = audit.audit_submission(final, expected)
    assert v["metric_key"] == "bal_acc"
    assert v["verdict"] == audit.PASS


# --- results ---------------------------------------------------------------

class _FakeBackend:
    name = "openai-compatible"
    model = "llama3.1"
    base_url = "http://gpu-node-7:11434/v1"
    api_key = "secret-should-never-appear"


def test_backend_descriptor_has_host_no_key():
    d = results.backend_descriptor(_FakeBackend(), spec="ollama:llama3.1")
    assert d["endpoint_host"] == "gpu-node-7"
    assert d["model"] == "llama3.1"
    assert "secret-should-never-appear" not in json.dumps(d)


def test_new_result_validates_and_round_trips(tmp_path):
    r = results.new_result(
        benchmark="create", competition="style-trans-fair",
        backend=results.backend_descriptor(_FakeBackend(), spec="ollama:llama3.1"),
        metrics={"bundle_builds": True}, run_id="abc", cost_usd=0.0)
    assert results.validate(r) == []
    p = results.dump(r, tmp_path / "results.json")
    assert results.load(p)["competition"] == "style-trans-fair"


def test_validate_flags_bad_schema():
    bad = {"benchmark": "create", "backend": {}, "competition": "x",
           "metrics": {}, "generated_at": "now", "schema_version": 999}
    probs = results.validate(bad)
    assert any("schema_version" in p for p in probs)


# --- missing_info ----------------------------------------------------------

def test_aggregate_counts_across_reports():
    reports = [
        {"competition_sample_name": "c", "run_id": "1", "items": [
            {"section": "metric", "field": "direction", "severity": "critical",
             "impact_area": "bundle_functionality",
             "resolution": {"action": "inferred", "confidence": "low",
                            "would_block_correct_scoring": True}}]},
        {"competition_sample_name": "c", "run_id": "2", "items": []},
    ]
    agg = missing_info.aggregate(reports)
    assert agg["total_runs"] == 2
    assert agg["total_items"] == 1
    assert agg["by_severity"]["critical"] == 1
    assert len(agg["high_stakes_inferences"]) == 1


# --- report ----------------------------------------------------------------

def test_render_run_report_minimal():
    r = results.new_result(
        benchmark="create", competition="demo",
        backend={"spec": "claude", "name": "claude", "model": "x",
                 "endpoint_host": None},
        metrics={"bundle_builds": True, "submissions": []})
    md = report.render_run_report(r)
    assert "Create-bench run report" in md
    assert "No submissions scored" in md


# --- reformat JSON extraction ----------------------------------------------

def test_extract_last_json_prefers_final_object():
    text = ('Here is my reasoning {"not": "this"} and the result:\n'
            '```json\n{"status": "pass", "scores": {"acc": 0.9}}\n```\n')
    obj = _extract_last_json(text)
    assert obj["status"] == "pass"
    assert obj["scores"]["acc"] == 0.9


def test_json_objects_is_string_aware():
    # A brace inside a string must not break matching.
    text = '{"msg": "a } b", "n": 1}'
    objs = _json_objects(text)
    assert len(objs) == 1
    assert json.loads(objs[0])["n"] == 1


def test_extract_last_json_none_on_garbage():
    assert _extract_last_json("no json here") is None
    assert _extract_last_json("") is None
