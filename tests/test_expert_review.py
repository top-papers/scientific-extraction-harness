import pytest

from scientific_extraction_harness.expert_review import (
    ExpertReviewRecord, ExpertReviewStore, ExpertReviewError, ValidationEvent, ValidationScore,
)


def test_score_rejects_bool_and_out_of_range():
    for value in (True, False, -1, 11, 1.5):
        with pytest.raises(ExpertReviewError):
            ValidationScore(value)  # type: ignore[arg-type]


def test_review_is_bound_to_explicit_event_and_append_only(tmp_path):
    digest = "a" * 64
    event = ValidationEvent.create("run", "candidate", digest, "reviewer-1", validation_event_id="event-1", created_at="2026-01-01T00:00:00Z")
    record = ExpertReviewRecord.create("run", "candidate", digest, "reviewer-1", 8, comment="checked", validation_event=event, review_id="review-1", validated_at="2026-01-01T00:00:01Z")
    path = tmp_path / "expert.jsonl"
    store = ExpertReviewStore(path)
    store.append(record)
    store.append(record)
    assert tuple(store.records()) == (record, record)


def test_review_rejects_mismatched_validation_event():
    event = ValidationEvent.create("run", "candidate", "a" * 64, "reviewer-1")
    with pytest.raises(ExpertReviewError):
        ExpertReviewRecord.create("other-run", "candidate", "a" * 64, "reviewer-1", 5, validation_event=event)
