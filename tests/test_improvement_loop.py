import pytest

from scientific_extraction_harness import (
    CandidateManifest,
    CandidateRegistry,
    GatePolicy,
    ImprovementController,
    ImprovementDecision,
    ReviewPacket,
)


def make_manifest(**overrides):
    values = {
        "parent_id": None,
        "mutation_kind": "config",
        "hypothesis": "A tighter threshold reduces false positives.",
        "changed_files": ("configs/default.toml",),
        "config_hash": "a" * 64,
        "budget": {"max_candidates": 100},
    }
    values.update(overrides)
    return CandidateManifest(**values)


def passing_metrics():
    return {
        "holdout_f1": 0.91,
        "baseline_holdout_f1": 0.90,
        "unsupported_claim_precision": 0.98,
        "coverage": 1.0,
        "false_approval_rate": 0.0,
        "budget": {
            "input_bytes": 10,
            "candidates": 2,
            "runtime_seconds": 1,
            "memory_bytes": 10,
            "external_calls": 0,
        },
    }


def passing_metadata():
    return {
        "schema_valid": True,
        "provenance_complete": True,
        "leakage_detected": False,
        "reproducible": True,
    }


def test_controller_returns_immutable_promote_decision_and_deltas():
    decision = ImprovementController().decide(
        make_manifest(), passing_metrics(), passing_metadata(), GatePolicy()
    )
    assert isinstance(decision, ImprovementDecision)
    assert decision.recommendation == "promote"
    assert decision.metric_deltas["holdout_f1"] == pytest.approx(0.01)
    with pytest.raises(TypeError):
        decision.metric_deltas["new"] = 1
    with pytest.raises((AttributeError, TypeError)):
        decision.recommendation = "reject"


def test_missing_evidence_is_needs_review_and_fail_closed():
    decision = ImprovementController().decide(
        make_manifest(), {}, {}, GatePolicy()
    )
    assert not decision.gate_result.passed
    assert set(decision.gate_result.failures)
    assert decision.recommendation == "needs_review"


def test_explicit_gate_failure_is_rejected():
    metrics = passing_metrics()
    metadata = passing_metadata()
    metadata["leakage_detected"] = True
    decision = ImprovementController().decide(make_manifest(), metrics, metadata, GatePolicy())
    assert decision.recommendation == "reject"
    assert "security" in decision.gate_result.failures


def test_registry_is_checked_without_mutating_or_promoting(tmp_path):
    registry = CandidateRegistry(tmp_path / "candidates.jsonl")
    manifest = make_manifest()
    registry.register(manifest)
    packet = ImprovementController(registry).review_packet(
        manifest, passing_metrics(), passing_metadata(), GatePolicy()
    )
    assert isinstance(packet, ReviewPacket)
    assert packet.decision.recommendation == "promote"
    assert registry.list() == [manifest]
    assert "approved" not in packet.recommendation


def test_unregistered_manifest_is_rejected_by_controller(tmp_path):
    with pytest.raises(ValueError, match="not registered"):
        ImprovementController(CandidateRegistry(tmp_path / "candidates.jsonl")).decide(
            make_manifest(), passing_metrics(), passing_metadata(), GatePolicy()
        )
