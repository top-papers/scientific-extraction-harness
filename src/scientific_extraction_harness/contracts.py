"""Versioned contracts for auditable extraction runs.

These contracts deliberately keep extraction candidates separate from review
corrections.  In particular, an extractor may create a candidate, but may not
create an approved evidence record.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .evidence import EvidenceRecord

SCHEMA_VERSION = "1"


class ExtractorApprovalError(ValueError):
    """Raised when extraction code attempts to create an approved record."""


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")


def validate_extractor_record(record: EvidenceRecord) -> EvidenceRecord:
    """Guard the extraction boundary: extractors can only emit candidates."""
    if record.status == "approved":
        raise ExtractorApprovalError(
            "extractors may not create approved evidence records; use review correction"
        )
    return record


def make_candidate_evidence(**kwargs: Any) -> EvidenceRecord:
    """Construct evidence at the extractor boundary and enforce its status."""
    record = EvidenceRecord(**kwargs)
    return validate_extractor_record(record)


@dataclass(frozen=True)
class Run:
    """One reproducible extraction invocation."""

    run_id: str
    extractor: str
    input_documents: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)
    record_type: str = field(default="run", init=False)

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        _require_text(self.extractor, "extractor")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {self.schema_version}")
        if any(not isinstance(document, str) or not document.strip() for document in self.input_documents):
            raise ValueError("input_documents must contain non-empty strings")
        object.__setattr__(self, "input_documents", tuple(self.input_documents))

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["input_documents"] = list(self.input_documents)
        return result


@dataclass(frozen=True)
class Candidate:
    """An extractor-produced, necessarily non-approved evidence candidate."""

    candidate_id: str
    run_id: str
    evidence: EvidenceRecord
    schema_version: str = SCHEMA_VERSION
    record_type: str = field(default="candidate", init=False)

    def __post_init__(self) -> None:
        _require_text(self.candidate_id, "candidate_id")
        _require_text(self.run_id, "run_id")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {self.schema_version}")
        validate_extractor_record(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Correction:
    """A review-layer correction, which may transition evidence to approved."""

    correction_id: str
    run_id: str
    candidate_id: str
    evidence: EvidenceRecord
    rationale: str
    schema_version: str = SCHEMA_VERSION
    record_type: str = field(default="correction", init=False)

    def __post_init__(self) -> None:
        _require_text(self.correction_id, "correction_id")
        _require_text(self.run_id, "run_id")
        _require_text(self.candidate_id, "candidate_id")
        _require_text(self.rationale, "rationale")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {self.schema_version}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Contract = Run | Candidate | Correction


def contract_to_json(contract: Contract) -> str:
    """Serialize a contract deterministically for ledgers and fixtures."""
    import json

    return json.dumps(
        contract.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
