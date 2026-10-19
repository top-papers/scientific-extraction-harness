import pytest

from scientific_extraction_harness.expert_review import ExpertReviewRecord, ValidationEvent
from scientific_extraction_harness.yaml_export import YAMLExportError, export_reviewed_dataset


def reviewed():
    event = ValidationEvent.create("run", "candidate", "a" * 64, "reviewer-1", validation_event_id="event-1", created_at="2026-01-01T00:00:00Z")
    return event, ExpertReviewRecord.create("run", "candidate", "a" * 64, "reviewer-1", 9, comment="verified", validation_event=event, review_id="review-1", validated_at="2026-01-01T00:00:01Z")


def test_export_is_deterministic_and_quoted():
    event, review = reviewed()
    kwargs = dict(article_hash="b" * 64, extraction_candidates=[{"value": "yes: no", "field": "x"}], provenance={"page": 2})
    first = export_reviewed_dataset(**kwargs, review=review, validation_event=event)
    second = export_reviewed_dataset(**kwargs, review=review, validation_event=event)
    assert first == second
    assert '"yes: no"' in first
    assert first.endswith("\n")


def test_export_requires_matching_validation_event_and_rejects_secrets():
    event, review = reviewed()
    with pytest.raises(YAMLExportError):
        export_reviewed_dataset(article_hash="b" * 64, extraction_candidates=[], provenance={"api_key": "no"}, review=review, validation_event=event)
    other = ValidationEvent.create("run", "candidate", "c" * 64, "reviewer-1")
    with pytest.raises(YAMLExportError):
        export_reviewed_dataset(article_hash="b" * 64, extraction_candidates=[], provenance={}, review=review, validation_event=other)
