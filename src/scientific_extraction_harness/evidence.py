"""Minimal, reviewable evidence contract used by all extractors."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Literal


Modality = Literal["text", "table", "figure", "scan"]
Status = Literal["candidate", "approved", "rejected"]


@dataclass(frozen=True)
class EvidenceRecord:
    """One extracted datum with enough provenance for a reviewer to check it."""

    document_id: str
    page: int
    modality: Modality
    locator: str
    field: str
    value: str
    unit: str | None
    confidence: float
    status: Status = "candidate"
    reviewer_note: str | None = None

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            raise ValueError("document_id is required")
        if self.page < 1:
            raise ValueError("page must be at least 1")
        if not self.locator.strip():
            raise ValueError("locator is required")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def write_jsonl(records: list[EvidenceRecord], path: Path) -> None:
    """Write records deterministically for review and dataset conversion."""
    with path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True))
            output.write("\n")


def load_jsonl(path: Path) -> list[EvidenceRecord]:
    """Load and validate evidence records from JSON Lines."""
    with path.open(encoding="utf-8") as source:
        return [EvidenceRecord(**json.loads(line)) for line in source if line.strip()]
