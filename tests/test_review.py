from pathlib import Path

import pytest

from scientific_extraction_harness import (
    EvidenceRecord,
    ReviewError,
    ReviewEvent,
    ReviewStore,
    apply_review_event,
)


def candidate() -> EvidenceRecord:
    return EvidenceRecord("doc", 2, "text", "paragraph:4", "mass", "2", "kg", 0.8)


def test_approve_requires_pseudonymous_reviewer_and_note() -> None:
    with pytest.raises(ReviewError):
        ReviewEvent.create("run-1", "candidate-1", "approve", "reviewer-1")
    with pytest.raises(ReviewError, match="email"):
        ReviewEvent.create("run-1", "candidate-1", "approve", "reviewer@example.test", note="checked")


def test_apply_review_preserves_candidate_and_lineage() -> None:
    original = candidate()
    event = ReviewEvent.create("run-1", "candidate-1", "approve", "expert-1", note="checked provenance", created_at="2026-10-19T00:00:00Z")
    result = apply_review_event(original, event, candidate_id="candidate-1", run_id="run-1")
    assert result.status == "approved"
    assert result.record.status == "approved"
    assert original.status == "candidate"
    assert (result.run_id, result.candidate_id) == ("run-1", "candidate-1")


def test_correct_requires_provenance_and_returns_replacement() -> None:
    replacement = EvidenceRecord("doc", 3, "figure", "figure:2/series:a", "mass", "3", "kg", 0.9, "approved")
    event = ReviewEvent.create("run-1", "candidate-1", "correct", "expert-1", replacement=replacement)
    result = apply_review_event(candidate(), event, candidate_id="candidate-1", run_id="run-1")
    assert result.record == replacement
    assert result.record is not candidate()


def test_apply_rejects_mismatched_event_identity() -> None:
    event = ReviewEvent.create("run-1", "candidate-1", "reject", "expert-1", note="ambiguous")
    with pytest.raises(ReviewError, match="identity"):
        apply_review_event(candidate(), event, candidate_id="candidate-2", run_id="run-1")
    with pytest.raises(ReviewError, match="identity"):
        apply_review_event(candidate(), event, candidate_id="candidate-1", run_id="run-2")


def test_correct_requires_approved_replacement_status() -> None:
    replacement = EvidenceRecord("doc", 3, "figure", "figure:2/series:a", "mass", "3", "kg", 0.9)
    with pytest.raises(ReviewError, match="approved status"):
        ReviewEvent.create("run-1", "candidate-1", "correct", "expert-1", replacement=replacement)


def test_store_apply_binds_identity_and_preserves_candidate(tmp_path: Path) -> None:
    path = tmp_path / "review.jsonl"
    store = ReviewStore(path)
    store.append(ReviewEvent.create("run-1", "candidate-1", "approve", "expert-1", note="checked"))
    original = candidate()
    result = store.apply(original, candidate_id="candidate-1", run_id="run-1")
    assert result is not None and result.record.status == "approved"
    assert original.status == "candidate"


def test_store_is_append_only_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "review.jsonl"
    store = ReviewStore(path)
    event = ReviewEvent.create("run-1", "candidate-1", "reject", "expert-1", note="ambiguous")
    store.append(event)
    first = path.read_text(encoding="utf-8")
    store.append(ReviewEvent.create("run-1", "candidate-1", "approve", "expert-1", note="resolved"))
    assert path.read_text(encoding="utf-8").startswith(first)
    assert len(store.for_candidate("candidate-1", "run-1")) == 2
