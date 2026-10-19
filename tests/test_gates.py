from dataclasses import FrozenInstanceError

import pytest

from scientific_extraction_harness.gates import GatePolicy, GateResult, evaluate_gates


def passing_inputs():
    return (
        {
            "false_approval_rate": 0.0,
            "holdout_f1": 0.90,
            "baseline_holdout_f1": 0.90,
            "unsupported_claim_precision": 0.98,
            "coverage": 1.0,
            "budget": {
                "input_bytes": 10,
                "candidates": 2,
                "runtime_seconds": 1,
                "memory_bytes": 10,
                "external_calls": 0,
            },
        },
        {
            "schema_valid": True,
            "provenance_complete": True,
            "leakage_detected": False,
            "reproducible": True,
        },
    )


def test_all_hard_gates_pass_without_side_effects():
    metrics, metadata = passing_inputs()
    result = evaluate_gates(metrics, metadata)
    assert isinstance(result, GateResult)
    assert result.passed is True
    assert result.approved is True  # status only; no approval mutation is performed
    assert result.failures == ()
    assert dict(result.gate_results) == {
        "schema": True, "provenance": True, "security": True,
        "holdout_regression": True, "unsupported_claims": True,
        "coverage": True, "budget": True, "reproducibility": True,
    }
    assert metrics["coverage"] == 1.0
    assert "approved" not in metadata


def test_missing_evidence_fails_closed_and_is_deterministic():
    metrics, metadata = passing_inputs()
    del metadata["reproducible"]
    first = evaluate_gates(metrics, metadata)
    second = evaluate_gates(metrics, metadata)
    assert first == second
    assert first.passed is False
    assert "reproducibility" in first.failures


def test_regression_and_budget_are_hard_failures():
    metrics, metadata = passing_inputs()
    metrics["holdout_f1"] = 0.87
    metrics["budget"]["candidates"] = 10001
    result = evaluate_gates(metrics, metadata)
    assert result.gate_passed("holdout_regression") is False
    assert result.gate_passed("budget") is False
    assert result.passed is False


def test_security_rejects_false_approval_and_leakage():
    metrics, metadata = passing_inputs()
    metrics["false_approval_rate"] = 0.001
    metadata["notes"] = "contact researcher@example.org"
    result = evaluate_gates(metrics, metadata)
    assert result.gate_passed("security") is False


def test_immutable_policy_and_result():
    policy = GatePolicy()
    with pytest.raises(FrozenInstanceError):
        policy.max_candidates = 1
    result = evaluate_gates(*passing_inputs(), policy=policy)
    with pytest.raises(TypeError):
        result.gate_results["schema"] = False
    with pytest.raises(FrozenInstanceError):
        result.passed = False


def test_modality_regression_is_checked_when_supplied():
    metrics, metadata = passing_inputs()
    metrics["modality_f1"] = {"text": 0.80}
    metrics["baseline_modality_f1"] = {"text": 0.90}
    result = evaluate_gates(metrics, metadata)
    assert result.gate_passed("holdout_regression") is False
