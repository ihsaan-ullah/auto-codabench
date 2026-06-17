"""Keyless tests for the validate-bench defect library.

The deterministic tier is backbone- and Docker-free: the clean bundle is
rebuilt from the shipped replay fixture, and the targeted checks run without
an LLM. So the whole deterministic tier is exercised here — both that each
seeded defect is *caught* and that the same check does *not* fire on the clean
bundle (specificity / no false positives).
"""
import tempfile
from pathlib import Path

import pytest

from autocodabench.bench import defects
from autocodabench.checks import validate_bundle_path


@pytest.fixture(scope="module")
def clean_bundle():
    with tempfile.TemporaryDirectory(prefix="defects-test-") as tmp:
        yield defects.build_clean_bundle(Path(tmp))


def test_clean_bundle_built(clean_bundle):
    assert clean_bundle.is_dir()
    assert (clean_bundle / "competition.yaml").is_file()


@pytest.mark.parametrize("defect", defects.defects_for_tier("deterministic"),
                         ids=lambda d: d.id)
def test_deterministic_defect_caught_and_specific(defect, clean_bundle, tmp_path):
    # The check must NOT fire on the clean bundle…
    clean_report = validate_bundle_path(clean_bundle, execute=False, judged=False)
    assert not defects.flagged(clean_report, defect.expect_check), (
        f"{defect.expect_check} fired on the clean bundle (false positive)")
    # …and MUST fire once the defect is seeded.
    seeded = defects.seed_defect(clean_bundle, defect, tmp_path / defect.id)
    seeded_report = validate_bundle_path(seeded, execute=False, judged=False)
    assert defects.flagged(seeded_report, defect.expect_check), (
        f"{defect.expect_check} did not catch defect {defect.id}")


def test_every_defect_targets_a_registered_check():
    from autocodabench.checks import REGISTRY
    for d in defects.DEFECTS:
        assert d.expect_check in REGISTRY, f"{d.id} targets unknown check {d.expect_check}"


# ---------------------------------------------------------------------------
# Generalised instrument: corrupt any clean bundle into opaque bad variants
# ---------------------------------------------------------------------------

def test_build_clean_bundle_from_dir_copies_a_bundle(clean_bundle, tmp_path):
    copied = defects.build_clean_bundle_from_dir(clean_bundle, tmp_path)
    assert (copied / "competition.yaml").is_file()
    assert copied.resolve() != clean_bundle.resolve()  # a copy, not the original


def test_applicable_defects_self_adapt_and_report_skips(clean_bundle, tmp_path):
    det = defects.defects_for_tier("deterministic")
    applicable, skipped = defects.applicable_defects(clean_bundle, tmp_path, det)
    # On the clean demo every deterministic defect both applies and is specific.
    assert {d.id for d in applicable} == {d.id for d in det}
    assert skipped == []


def test_corrupt_bundle_labels_are_opaque_and_carry_an_answer_key(clean_bundle, tmp_path):
    det = defects.defects_for_tier("deterministic")
    variants, skipped = defects.corrupt_bundle(clean_bundle, tmp_path / "cases", det)
    assert len(variants) == len(det)
    for v in variants:
        # The label a checker sees must not leak the flaw kind…
        assert v.label.startswith("case-")
        assert v.defect_id not in v.label and v.expect_check not in v.label
        # …and the variant must be a real, corrupted bundle copy.
        assert (v.path / "competition.yaml").is_file()
    # The probe scratch dir is cleaned up; only the case-NN variants remain.
    leftover = [p.name for p in (tmp_path / "cases").iterdir() if p.is_dir()]
    assert all(name.startswith("case-") for name in leftover)
    # The answer key actually catches its flaw (sanity: harness measures truth).
    from autocodabench.checks import validate_bundle_path
    v0 = variants[0]
    report = validate_bundle_path(v0.path, execute=False)
    assert defects.flagged(report, v0.expect_check)


# ---------------------------------------------------------------------------
# summarize() — precision / recall / F1 maths (pure, no bundle needed)
# ---------------------------------------------------------------------------

def test_summarize_perfect_deterministic():
    rows = [{"defect": "a", "tier": "deterministic", "runs": 1, "caught": 1},
            {"defect": "b", "tier": "deterministic", "runs": 1, "caught": 1}]
    out = defects.summarize(rows)
    det = out["deterministic"]
    assert det["recall"] == 1.0 and det["precision"] == 1.0 and det["f1"] == 1.0
    assert det["tp"] == 2 and det["fn"] == 0 and det["fp"] == 0
    assert out["judged"] is None


def test_summarize_judged_with_misses_and_false_positives():
    rows = [{"defect": "x", "tier": "judged", "runs": 4, "caught": 3},   # 3 TP, 1 FN
            {"defect": "y", "tier": "judged", "runs": 4, "caught": 1}]   # 1 TP, 3 FN
    out = defects.summarize(rows, clean_false_positives=2, clean_runs=4)
    j = out["judged"]
    assert j["tp"] == 4 and j["fn"] == 4 and j["fp"] == 2
    assert j["recall"] == pytest.approx(4 / 8)
    assert j["precision"] == pytest.approx(4 / 6)
    assert j["clean_false_positive_rate"] == pytest.approx(2 / 4)
    assert 0 < j["f1"] < 1


def test_summarize_skips_unrun_tier():
    rows = [{"defect": "j", "tier": "judged", "runs": 0, "caught": None}]
    assert defects.summarize(rows)["judged"] is None
