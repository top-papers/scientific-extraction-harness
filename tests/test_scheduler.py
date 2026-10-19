from datetime import datetime, timezone
import json
import threading

import pytest

from scientific_extraction_harness import (
    CandidateManifest, GatePolicy, ReviewEvent, Schedule, Scheduler, SchedulerError,
)


NOW = "2026-01-01T00:00:00+00:00"
METRICS = {
    "false_approval_rate": 0.0, "holdout_f1": 0.9, "baseline_holdout_f1": 0.9,
    "unsupported_claim_precision": 1.0, "coverage": 1.0,
    "budget": {"input_bytes": 1, "candidates": 1, "runtime_seconds": 1,
                "memory_bytes": 1, "external_calls": 0},
}
META = {"schema_valid": True, "provenance_complete": True, "leakage_detected": False,
        "reproducible": True}


def manifest():
    return CandidateManifest(None, "threshold", "test hypothesis", ("config.toml",), "a" * 64, {})


def scheduler(tmp_path, **kwargs):
    return Scheduler(tmp_path / "state.json", Schedule(enabled=True, due_at=NOW), **kwargs)


def test_disabled_by_default_and_force_does_not_bypass(tmp_path):
    s = Scheduler(tmp_path / "state.json")
    assert s.run(manifest(), METRICS, META, GatePolicy(), now=NOW, force=True) is None


def test_due_at_and_interval(tmp_path):
    m = manifest()
    assert scheduler(tmp_path).run(m, METRICS, META, GatePolicy(), now="2025-12-31T23:59:59+00:00") is None
    s = scheduler(tmp_path, max_runs=2)
    first = s.run(m, METRICS, META, GatePolicy(), now=NOW)
    assert first is not None
    interval = Scheduler(tmp_path / "interval.json", Schedule(enabled=True, interval_seconds=60), max_runs=2)
    assert interval.run(m, METRICS, META, GatePolicy(), now=NOW) is not None
    assert interval.run(m, METRICS, META, GatePolicy(), now="2026-01-01T00:00:59+00:00") is None
    assert interval.run(m, METRICS, META, GatePolicy(), now="2026-01-01T00:01:00+00:00") is not None


def test_idempotency_returns_same_persisted_packet(tmp_path):
    s = scheduler(tmp_path)
    first = s.run(manifest(), METRICS, META, GatePolicy(), now=NOW)
    second = s.run(manifest(), METRICS, META, GatePolicy(), now=NOW)
    assert second == first
    assert len(json.loads((tmp_path / "state.json").read_text())["runs"]) == 1


def test_max_runs(tmp_path):
    s = Scheduler(tmp_path / "state.json", Schedule(enabled=True, interval_seconds=1), max_runs=1)
    assert s.run(manifest(), METRICS, META, GatePolicy(), now=NOW) is not None
    assert s.run(manifest(), METRICS, META, GatePolicy(), now="2026-01-01T00:00:01+00:00") is None


def test_lock_timeout_and_no_overlap(tmp_path):
    s = scheduler(tmp_path, lock_timeout=0)
    s.lock_path.parent.mkdir(parents=True, exist_ok=True)
    s.lock_path.write_text("held")
    with pytest.raises(SchedulerError, match="lock timeout"):
        s.run(manifest(), METRICS, META, GatePolicy(), now=NOW)
    s.lock_path.unlink()


def test_corrupt_state_fails_closed(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json")
    with pytest.raises(SchedulerError, match="corrupt"):
        scheduler(tmp_path).run(manifest(), METRICS, META, GatePolicy(), now=NOW)


def test_human_gate_and_no_auto_promotion(tmp_path):
    s = scheduler(tmp_path)
    packet = s.run(manifest(), METRICS, META, GatePolicy(), now=NOW)
    assert packet.recommendation == "promote"
    assert not (tmp_path / "promoted").exists()
    event = ReviewEvent.create(packet.run_id, packet.candidate_id, "approve", "reviewer-1", note="reviewed")
    receipt = s.approve(packet, event)
    assert receipt.reviewer_id == "reviewer-1"


def test_missing_note_rejected(tmp_path):
    s = scheduler(tmp_path)
    packet = s.run(manifest(), METRICS, META, GatePolicy(), now=NOW)
    with pytest.raises(Exception):
        ReviewEvent.create(packet.run_id, packet.candidate_id, "approve", "reviewer-1", note="")


def test_replay_mismatch_and_stale_approval(tmp_path):
    s = scheduler(tmp_path)
    packet = s.run(manifest(), METRICS, META, GatePolicy(), now=NOW)
    event = ReviewEvent.create(packet.run_id, packet.candidate_id, "approve", "reviewer", note="ok", review_event_id="fixed")
    s.approve(packet, event)
    with pytest.raises(SchedulerError, match="replayed"):
        s.approve(packet, event)
    mismatch = ReviewEvent.create("other-run", packet.candidate_id, "approve", "reviewer", note="ok")
    with pytest.raises(SchedulerError, match="run"):
        s.approve(packet, mismatch)
    other = scheduler(tmp_path / "other")
    other_packet = other.run(manifest(), METRICS, META, GatePolicy(), now=NOW)
    empty_scheduler = scheduler(tmp_path / "empty")
    with pytest.raises(SchedulerError, match="stale"):
        empty_scheduler.approve(other_packet, event)


def test_failure_behavior_invalid_inputs(tmp_path):
    s = scheduler(tmp_path)
    with pytest.raises(TypeError):
        s.run(object(), METRICS, META, GatePolicy(), now=NOW)
    with pytest.raises(SchedulerError):
        s.run(manifest(), METRICS, META, GatePolicy(), now="not-a-time")
