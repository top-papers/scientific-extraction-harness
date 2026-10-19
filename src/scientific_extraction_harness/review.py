"""Append-only human review events and the candidate approval boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Iterator, Literal
from uuid import uuid4

from .evidence import EvidenceRecord, Status

ReviewAction = Literal["approve", "reject", "correct"]

_EMAIL = re.compile(r"(?i)\b[^\s@]+@[^\s@]+\.[^\s@]+\b")


class ReviewError(ValueError):
    """Raised when a review event would violate the review contract."""


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewError(f"{name} is required")
    return value


def _safe_reviewer_id(value: str) -> str:
    value = _text(value, "reviewer_id")
    if _EMAIL.search(value):
        raise ReviewError("reviewer_id must be a pseudonym, not an email address")
    return value


def _safe_note(value: str | None, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise ReviewError("note is required")
        return None
    if not isinstance(value, str) or not value.strip():
        if required:
            raise ReviewError("note is required")
        return None
    if _EMAIL.search(value):
        raise ReviewError("note must not contain an email address")
    # Notes are metadata, not a place to copy source passages.
    if len(value) > 2000:
        raise ReviewError("note is too long; raw source text is not allowed")
    return value


@dataclass(frozen=True)
class ReviewEvent:
    """One immutable review action; it never mutates the candidate it refers to."""

    review_event_id: str
    run_id: str
    candidate_id: str
    action: ReviewAction
    reviewer_id: str
    note: str | None = None
    created_at: str = ""
    replacement: EvidenceRecord | None = None
    record_type: str = "review_event"

    def __post_init__(self) -> None:
        _text(self.review_event_id, "review_event_id")
        _text(self.run_id, "run_id")
        _text(self.candidate_id, "candidate_id")
        _safe_reviewer_id(self.reviewer_id)
        if self.action not in ("approve", "reject", "correct"):
            raise ReviewError("action must be approve, reject, or correct")
        _safe_note(self.note, required=self.action == "approve")
        if not self.created_at:
            raise ReviewError("created_at is required")
        if self.action == "correct":
            if not isinstance(self.replacement, EvidenceRecord):
                raise ReviewError("correct requires an EvidenceRecord replacement")
            if self.replacement.status != "approved":
                raise ReviewError("correct replacement must have explicit approved status")
            _validate_provenance(self.replacement)
        elif self.replacement is not None:
            raise ReviewError("replacement is only valid for correct")
        object.__setattr__(self, "record_type", "review_event")

    @classmethod
    def create(cls, run_id: str, candidate_id: str, action: ReviewAction, reviewer_id: str,
               *, note: str | None = None, replacement: EvidenceRecord | None = None,
               created_at: str | None = None, review_event_id: str | None = None) -> "ReviewEvent":
        return cls(review_event_id or f"rev-{uuid4().hex}", run_id, candidate_id, action,
                   reviewer_id, note, created_at or datetime.now().astimezone().isoformat(), replacement)

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        if self.replacement is not None:
            result["replacement"] = self.replacement.to_dict()
        return result


def _validate_provenance(record: EvidenceRecord) -> None:
    if not record.document_id.strip() or record.page < 1 or not record.modality or not record.locator.strip():
        raise ReviewError("replacement must include complete provenance")


@dataclass(frozen=True)
class ReviewResult:
    status: Status
    record: EvidenceRecord
    review_event_id: str
    run_id: str
    candidate_id: str


def apply_review_event(
    candidate: EvidenceRecord,
    event: ReviewEvent,
    *,
    candidate_id: str | None = None,
    run_id: str | None = None,
) -> ReviewResult:
    """Apply an event to a candidate without rewriting it.

    ``candidate_id`` and ``run_id`` identify the application context. They are
    required when applying an event directly, preventing an event for another
    candidate from being replayed against this record. ``ReviewStore.apply``
    supplies both values through this same boundary.
    """
    if not isinstance(candidate, EvidenceRecord):
        raise ReviewError("candidate must be an EvidenceRecord")
    if candidate_id is None or run_id is None:
        raise ReviewError("candidate_id and run_id are required to apply a review event")
    _text(candidate_id, "candidate_id")
    _text(run_id, "run_id")
    if event.candidate_id != candidate_id or event.run_id != run_id:
        raise ReviewError("review event identity does not match application context")
    if candidate.status != "candidate":
        raise ReviewError("review events can only be applied to candidate records")
    if event.action == "correct":
        record = event.replacement
        assert record is not None
    else:
        status: Status = "approved" if event.action == "approve" else "rejected"
        record = EvidenceRecord(**{**candidate.to_dict(), "status": status, "reviewer_note": event.note})
    return ReviewResult(record.status, record, event.review_event_id, event.run_id, event.candidate_id)


class ReviewStore:
    """Dependency-free JSONL store. Existing lines are never rewritten."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, event: ReviewEvent) -> None:
        with self.path.open("a", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            output.write("\n")

    def events(self) -> Iterator[ReviewEvent]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                    replacement = payload.get("replacement")
                    if replacement is not None:
                        payload["replacement"] = EvidenceRecord(**replacement)
                    yield ReviewEvent(**payload)
                except (TypeError, ValueError, json.JSONDecodeError, KeyError) as exc:
                    raise ReviewError(f"invalid review event at line {line_number}") from exc

    def for_candidate(self, candidate_id: str, run_id: str | None = None) -> tuple[ReviewEvent, ...]:
        return tuple(event for event in self.events() if event.candidate_id == candidate_id and (run_id is None or event.run_id == run_id))

    def apply(self, candidate: EvidenceRecord, *, candidate_id: str, run_id: str) -> ReviewResult | None:
        result: ReviewResult | None = None
        for event in self.for_candidate(candidate_id, run_id):
            result = apply_review_event(candidate, event, candidate_id=candidate_id, run_id=run_id)
        return result
