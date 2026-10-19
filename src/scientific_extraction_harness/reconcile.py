"""Cross-modal reconciliation without discarding disagreement."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Iterable, Mapping

from .evidence import EvidenceRecord


@dataclass(frozen=True)
class ReconciliationCandidate:
    candidate_id: str
    value: str
    modality: str
    confidence: float = 0.0
    document_id: str = ""
    page: int = 1
    locator: str = ""
    unit: str | None = None
    source_table: bool = False

    @classmethod
    def from_evidence(cls, record: EvidenceRecord, candidate_id: str | None = None) -> "ReconciliationCandidate":
        return cls(candidate_id or _candidate_id(record), record.value, record.modality, record.confidence,
                   record.document_id, record.page, record.locator, record.unit)

    def __post_init__(self) -> None:
        if not self.candidate_id.strip(): raise ValueError("candidate_id is required")
        if not self.modality.strip(): raise ValueError("modality is required")
        if not 0 <= self.confidence <= 1: raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class ConflictSet:
    conflict_set_id: str
    candidate_ids: tuple[str, ...]
    values: tuple[str, ...]
    reason: str = "competing-values"


@dataclass(frozen=True)
class ReconciliationResult:
    candidates: tuple[ReconciliationCandidate, ...]
    conflict_sets: tuple[ConflictSet, ...]
    agreement: float
    agreement_pairs: tuple[tuple[str, str], ...] = ()
    selected_candidate_id: str | None = None
    selection_reason: str | None = None
    abstained: bool = False

    @property
    def conflicts(self) -> tuple[ConflictSet, ...]:
        return self.conflict_sets


def _candidate_id(record: EvidenceRecord) -> str:
    raw = f"{record.document_id}|{record.page}|{record.modality}|{record.locator}|{record.field}|{record.value}"
    return "candidate:" + sha256(raw.encode()).hexdigest()[:16]


def _coerce(item: ReconciliationCandidate | EvidenceRecord | Mapping[str, Any], index: int) -> ReconciliationCandidate:
    if isinstance(item, ReconciliationCandidate): return item
    if isinstance(item, EvidenceRecord): return ReconciliationCandidate.from_evidence(item)
    data = dict(item)
    data.setdefault("candidate_id", f"candidate:{index + 1}")
    return ReconciliationCandidate(**data)


def reconcile(candidates: Iterable[ReconciliationCandidate | EvidenceRecord | Mapping[str, Any]], *, review_metadata: Mapping[str, Any] | None = None) -> ReconciliationResult:
    """Return all observations, explicit conflicts, and non-averaged agreement.

    A source-table candidate is selected only when review metadata explicitly
    records a human review decision (``source_table_precedence``). This helper
    never turns a candidate into an approved evidence record.
    """
    items = tuple(_coerce(c, i) for i, c in enumerate(candidates))
    if not items:
        return ReconciliationResult((), (), 1.0, abstained=True)
    groups: dict[tuple[str, str | None], list[ReconciliationCandidate]] = {}
    for item in items:
        groups.setdefault((item.value.strip(), item.unit), []).append(item)
    conflict_sets: list[ConflictSet] = []
    value_groups: dict[str, list[ReconciliationCandidate]] = {}
    for item in items: value_groups.setdefault(item.value.strip(), []).append(item)
    if len(value_groups) > 1:
        conflict_sets.append(ConflictSet(
            "conflict:" + sha256("|".join(i.candidate_id for i in items).encode()).hexdigest()[:16],
            tuple(i.candidate_id for i in items), tuple(value_groups.keys())))
    pairs: list[tuple[str, str]] = []
    for index, left in enumerate(items):
        for right in items[index + 1:]:
            if left.value.strip() == right.value.strip() and left.unit == right.unit:
                pairs.append((left.candidate_id, right.candidate_id))
    total_pairs = len(items) * (len(items) - 1) // 2
    agreement = (len(pairs) / total_pairs) if total_pairs else 1.0
    selected = None
    reason = None
    metadata = review_metadata or {}
    if metadata.get("source_table_precedence") is True:
        reviewed_id = metadata.get("reviewed_candidate_id")
        eligible = [i for i in items if i.source_table or i.modality == "table"]
        chosen = next((i for i in eligible if reviewed_id in (None, i.candidate_id)), None)
        if chosen is not None:
            selected, reason = chosen.candidate_id, "explicitly-reviewed-source-table-precedence"
    return ReconciliationResult(items, tuple(conflict_sets), agreement, tuple(pairs), selected, reason, bool(conflict_sets) and selected is None)


reconcile_candidates = reconcile

__all__ = ["ReconciliationCandidate", "ConflictSet", "ReconciliationResult", "reconcile", "reconcile_candidates"]
