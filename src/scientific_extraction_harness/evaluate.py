"""Dependency-free evaluation for versioned synthetic extraction cases.

The evaluator intentionally treats holdout cases as an evaluation-only split.  It
never learns thresholds or normalisation rules from a manifest.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .evidence import EvidenceRecord

EVALUATOR_SCHEMA_VERSION = "1"
SPLITS = frozenset({"unit", "calibration", "holdout", "adversarial"})


class EvaluationManifestError(ValueError):
    """Raised when a case manifest is malformed or mixes protected splits."""


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    split: str
    gold: tuple[EvidenceRecord, ...] = ()
    unsupported_claim: bool = False
    expected_abstention: bool = False

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise EvaluationManifestError("case_id is required")
        if self.split not in SPLITS:
            raise EvaluationManifestError(f"unsupported split: {self.split!r}")
        if not isinstance(self.gold, tuple):
            object.__setattr__(self, "gold", tuple(self.gold))


@dataclass(frozen=True)
class CaseManifest:
    manifest_version: str
    cases: tuple[EvaluationCase, ...]

    def __post_init__(self) -> None:
        if self.manifest_version != EVALUATOR_SCHEMA_VERSION:
            raise EvaluationManifestError("unsupported evaluator manifest_version")
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise EvaluationManifestError("case_id values must be unique")
        if not any(case.split == "holdout" for case in self.cases):
            raise EvaluationManifestError("manifest must contain an explicit holdout split")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "CaseManifest":
        if not isinstance(payload, Mapping):
            raise EvaluationManifestError("case manifest must be an object")
        if set(payload) - {"manifest_version", "cases"}:
            raise EvaluationManifestError("unknown case manifest field")
        raw_cases = payload.get("cases")
        if not isinstance(raw_cases, list):
            raise EvaluationManifestError("cases must be a list")
        cases: list[EvaluationCase] = []
        for raw in raw_cases:
            if not isinstance(raw, Mapping):
                raise EvaluationManifestError("each case must be an object")
            allowed = {"case_id", "split", "gold", "unsupported_claim", "expected_abstention"}
            if set(raw) - allowed:
                raise EvaluationManifestError("unknown case field")
            gold = tuple(_record(value) for value in raw.get("gold", []))
            cases.append(EvaluationCase(
                case_id=str(raw.get("case_id", "")), split=str(raw.get("split", "")),
                gold=gold, unsupported_claim=bool(raw.get("unsupported_claim", False)),
                expected_abstention=bool(raw.get("expected_abstention", False)),
            ))
        return cls(str(payload.get("manifest_version", "")), tuple(cases))

    @classmethod
    def load(cls, path: Path) -> "CaseManifest":
        return cls.from_mapping(json.loads(Path(path).read_text(encoding="utf-8")))

    def cases_for(self, split: str) -> tuple[EvaluationCase, ...]:
        if split not in SPLITS:
            raise EvaluationManifestError(f"unsupported split: {split!r}")
        return tuple(case for case in self.cases if case.split == split)

    def tuning_cases(self) -> tuple[EvaluationCase, ...]:
        """Return only non-holdout cases; holdout cannot be supplied to tuning."""
        return tuple(case for case in self.cases if case.split != "holdout")


def _record(value: Any) -> EvidenceRecord:
    if isinstance(value, EvidenceRecord):
        return value
    if not isinstance(value, Mapping):
        raise EvaluationManifestError("gold records must be objects")
    try:
        return EvidenceRecord(**dict(value))
    except (TypeError, ValueError) as exc:
        raise EvaluationManifestError(f"invalid gold record: {exc}") from exc


def _records(value: Iterable[EvidenceRecord] | None) -> tuple[EvidenceRecord, ...]:
    return tuple(value or ())


def records_match(predicted: EvidenceRecord, gold: EvidenceRecord) -> bool:
    """Exact, deterministic match over value, unit, field, and all provenance."""
    return (
        predicted.field == gold.field and predicted.value == gold.value
        and predicted.unit == gold.unit and predicted.document_id == gold.document_id
        and predicted.page == gold.page and predicted.modality == gold.modality
        and predicted.locator == gold.locator
    )


def locator_is_valid(record: EvidenceRecord) -> bool:
    """Check the provenance fields available without opening source documents."""
    return (
        isinstance(record.document_id, str) and bool(record.document_id.strip())
        and isinstance(record.page, int) and not isinstance(record.page, bool) and record.page >= 1
        and isinstance(record.modality, str) and record.modality in {"text", "table", "figure", "scan"}
        and isinstance(record.locator, str) and bool(record.locator.strip())
    )


@dataclass(frozen=True)
class SplitMetrics:
    split: str
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    locator_validity: float
    abstention_rate: float
    unsupported_claim_signal: float
    cases: int


@dataclass(frozen=True)
class EvaluationReport:
    schema_version: str
    splits: dict[str, SplitMetrics]

    def metric(self, split: str, name: str) -> float:
        return float(getattr(self.splits[split], name))


def _score(split: str, cases: Sequence[EvaluationCase], predictions: Mapping[str, Iterable[EvidenceRecord]]) -> SplitMetrics:
    tp = fp = fn = valid = total = abstentions = unsupported_hits = 0
    for case in cases:
        predicted = _records(predictions.get(case.case_id))
        total += len(predicted)
        valid += sum(locator_is_valid(record) for record in predicted)
        if not predicted:
            abstentions += 1
        if case.unsupported_claim:
            unsupported_hits += int(not predicted)
        unmatched_gold = list(case.gold)
        for record in predicted:
            match = next((i for i, gold in enumerate(unmatched_gold) if records_match(record, gold)), None)
            if match is None:
                fp += 1
            else:
                tp += 1
                unmatched_gold.pop(match)
        fn += len(unmatched_gold)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    count = len(cases)
    return SplitMetrics(split, tp, fp, fn, precision, recall, f1,
                        valid / total if total else 1.0,
                        abstentions / count if count else 0.0,
                        unsupported_hits / sum(c.unsupported_claim for c in cases) if any(c.unsupported_claim for c in cases) else 0.0,
                        count)


def evaluate(manifest: CaseManifest, predictions: Mapping[str, Iterable[EvidenceRecord]]) -> EvaluationReport:
    """Score predictions against every split, including the protected holdout."""
    unknown = set(predictions) - {case.case_id for case in manifest.cases}
    if unknown:
        raise EvaluationManifestError(f"predictions contain unknown case IDs: {sorted(unknown)}")
    return EvaluationReport(EVALUATOR_SCHEMA_VERSION, {
        split: _score(split, manifest.cases_for(split), predictions) for split in sorted(SPLITS)
    })


@dataclass(frozen=True)
class RegressionReport:
    regressions: tuple[str, ...]
    deltas: dict[str, float]

    @property
    def passed(self) -> bool:
        return not self.regressions


def compare_to_baseline(current: EvaluationReport, baseline: EvaluationReport, *, max_regression: float = 0.0) -> RegressionReport:
    """Compare metrics without tuning; positive ``max_regression`` permits a budget."""
    if max_regression < 0:
        raise ValueError("max_regression must be non-negative")
    deltas: dict[str, float] = {}
    regressions: list[str] = []
    for split in sorted(current.splits):
        if split not in baseline.splits:
            continue
        for name in ("precision", "recall", "f1", "locator_validity", "unsupported_claim_signal"):
            delta = current.metric(split, name) - baseline.metric(split, name)
            key = f"{split}.{name}"
            deltas[key] = delta
            if delta < -max_regression:
                regressions.append(key)
    return RegressionReport(tuple(regressions), deltas)


# Explicit alias makes the public API discoverable to callers using the noun form.
EvaluationManifest = CaseManifest
load_case_manifest = CaseManifest.load
