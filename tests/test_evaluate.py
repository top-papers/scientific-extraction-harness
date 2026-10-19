from __future__ import annotations

import pytest

from scientific_extraction_harness import (
    CaseManifest, EvaluationManifestError, EvidenceRecord, compare_to_baseline,
    evaluate, locator_is_valid, records_match,
)


def record(value="42", *, locator="table 1, row 2"):
    return EvidenceRecord("paper", 2, "table", locator, "temperature", value, "C", .9)


def manifest():
    return CaseManifest.from_mapping({
        "manifest_version": "1",
        "cases": [
            {"case_id": "u", "split": "unit", "gold": [record().to_dict()]},
            {"case_id": "c", "split": "calibration", "gold": []},
            {"case_id": "h", "split": "holdout", "gold": [record().to_dict()]},
            {"case_id": "a", "split": "adversarial", "unsupported_claim": True,
             "expected_abstention": True},
        ],
    })


def test_manifest_requires_explicit_holdout_and_keeps_it_out_of_tuning():
    assert {c.case_id for c in manifest().tuning_cases()} == {"u", "c", "a"}
    with pytest.raises(EvaluationManifestError, match="holdout"):
        CaseManifest.from_mapping({"manifest_version": "1", "cases": []})


def test_exact_match_and_metrics_and_signals():
    report = evaluate(manifest(), {"u": [record()], "h": [record()], "a": []})
    assert report.splits["unit"].f1 == 1
    assert report.splits["holdout"].recall == 1
    assert report.splits["adversarial"].abstention_rate == 1
    assert report.splits["adversarial"].unsupported_claim_signal == 1
    assert records_match(record(), record())
    assert not records_match(record(), record(value="43"))


def test_locator_validity_and_regression_comparison():
    assert locator_is_valid(record())
    current = evaluate(manifest(), {"u": [record()], "h": [record()]})
    baseline = evaluate(manifest(), {})
    regression = compare_to_baseline(current, baseline)
    assert regression.passed is True
    assert regression.deltas["holdout.f1"] > 0


def test_unknown_prediction_case_rejected():
    with pytest.raises(EvaluationManifestError, match="unknown"):
        evaluate(manifest(), {"not-a-case": []})
