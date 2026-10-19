"""Expert validation contracts for reviewed extraction artifacts.

This module is deliberately separate from :mod:`review`: the existing
ReviewEvent approval boundary is unchanged. Expert records are append-only
metadata that can authorize dataset export only when paired with an explicit
validation event.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Iterator
from uuid import uuid4

_EMAIL = re.compile(r"(?i)\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


class ExpertReviewError(ValueError):
    """Raised when an expert validation contract is invalid."""


def _required(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExpertReviewError(f"{name} is required")
    return value


def _pseudonym(value: str) -> str:
    value = _required(value, "reviewer_pseudonym")
    if _EMAIL.search(value):
        raise ExpertReviewError("reviewer_pseudonym must not be an email address")
    return value


@dataclass(frozen=True)
class ValidationScore:
    """An integer expert score from 0 through 10, with an optional comment."""

    score: int
    comment: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.score, bool) or not isinstance(self.score, int):
            raise ExpertReviewError("score must be an integer from 0 to 10")
        if not 0 <= self.score <= 10:
            raise ExpertReviewError("score must be an integer from 0 to 10")
        if self.comment is not None:
            if not isinstance(self.comment, str) or not self.comment.strip():
                raise ExpertReviewError("comment must be a non-empty string when supplied")
            if _EMAIL.search(self.comment) or len(self.comment) > 2000:
                raise ExpertReviewError("comment contains disallowed personal data or is too long")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationEvent:
    """An explicit, immutable authorization event for one expert review."""

    validation_event_id: str
    run_id: str
    candidate_id: str
    extraction_artifact_hash: str
    reviewer_pseudonym: str
    created_at: str
    event_type: str = "expert_validation"

    def __post_init__(self) -> None:
        for value, name in ((self.validation_event_id, "validation_event_id"),
                            (self.run_id, "run_id"), (self.candidate_id, "candidate_id"),
                            (self.extraction_artifact_hash, "extraction_artifact_hash")):
            _required(value, name)
        if not _HEX64.fullmatch(self.extraction_artifact_hash):
            raise ExpertReviewError("extraction_artifact_hash must be a SHA-256 hex digest")
        _pseudonym(self.reviewer_pseudonym)
        _required(self.created_at, "created_at")
        if self.event_type != "expert_validation":
            raise ExpertReviewError("event_type must be expert_validation")

    @classmethod
    def create(cls, run_id: str, candidate_id: str, extraction_artifact_hash: str,
               reviewer_pseudonym: str, *, validation_event_id: str | None = None,
               created_at: str | None = None) -> "ValidationEvent":
        return cls(validation_event_id or f"validation-{uuid4().hex}", run_id, candidate_id,
                   extraction_artifact_hash, reviewer_pseudonym,
                   created_at or datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ExpertReviewRecord:
    """Append-only expert score bound to an extraction artifact and event."""

    review_id: str
    run_id: str
    candidate_id: str
    extraction_artifact_hash: str
    reviewer_pseudonym: str
    score: int
    comment: str | None
    validation_event_id: str
    validated_at: str
    record_type: str = "expert_review"

    def __post_init__(self) -> None:
        _required(self.review_id, "review_id")
        _required(self.run_id, "run_id")
        _required(self.candidate_id, "candidate_id")
        if not _HEX64.fullmatch(self.extraction_artifact_hash):
            raise ExpertReviewError("extraction_artifact_hash must be a SHA-256 hex digest")
        _pseudonym(self.reviewer_pseudonym)
        ValidationScore(self.score, self.comment)
        _required(self.validation_event_id, "validation_event_id")
        _required(self.validated_at, "validated_at")
        if self.record_type != "expert_review":
            raise ExpertReviewError("record_type must be expert_review")

    @classmethod
    def create(cls, run_id: str, candidate_id: str, extraction_artifact_hash: str,
               reviewer_pseudonym: str, score: int, *, comment: str | None = None,
               validation_event: ValidationEvent, review_id: str | None = None,
               validated_at: str | None = None) -> "ExpertReviewRecord":
        if not isinstance(validation_event, ValidationEvent):
            raise ExpertReviewError("an explicit ValidationEvent is required")
        identity = (run_id, candidate_id, extraction_artifact_hash, reviewer_pseudonym)
        event_identity = (validation_event.run_id, validation_event.candidate_id,
                          validation_event.extraction_artifact_hash, validation_event.reviewer_pseudonym)
        if identity != event_identity:
            raise ExpertReviewError("validation event does not match review identity")
        return cls(review_id or f"expert-review-{uuid4().hex}", *identity, score, comment,
                   validation_event.validation_event_id,
                   validated_at or datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


# A descriptive compatibility alias for callers that use validation terminology.
ExpertValidationRecord = ExpertReviewRecord


class ExpertReviewStore:
    """Append-only JSONL store; existing review lines are never rewritten."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, record: ExpertReviewRecord) -> None:
        if not isinstance(record, ExpertReviewRecord):
            raise ExpertReviewError("only ExpertReviewRecord values can be appended")
        with self.path.open("a", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            output.write("\n")

    def records(self) -> Iterator[ExpertReviewRecord]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    yield ExpertReviewRecord(**json.loads(line))
                except (TypeError, ValueError, json.JSONDecodeError, KeyError) as exc:
                    raise ExpertReviewError(f"invalid expert review at line {line_number}") from exc

    def for_candidate(self, candidate_id: str, run_id: str | None = None) -> tuple[ExpertReviewRecord, ...]:
        return tuple(r for r in self.records() if r.candidate_id == candidate_id and (run_id is None or r.run_id == run_id))


# Convenient function name for code that does not need to know the class name.
def create_expert_review(*args: object, **kwargs: object) -> ExpertReviewRecord:
    return ExpertReviewRecord.create(*args, **kwargs)  # type: ignore[arg-type]
