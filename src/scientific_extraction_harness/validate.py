"""Dependency-free validation at the extraction/review boundary.

Validation is deliberately conservative: malformed objects, unsupported source
modalities, unresolved adapter abstentions, and approval attempts are rejected
rather than repaired or silently accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Iterable

from .adapters.base import AdapterResult
from .evidence import EvidenceRecord

ALLOWED_MODALITIES = frozenset({"text", "table", "figure", "scan"})
ALLOWED_STATUSES = frozenset({"candidate", "approved", "rejected"})


@dataclass(frozen=True)
class ValidationIssue:
    """One machine-readable validation failure."""

    code: str
    message: str
    path: str = ""
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValueError("validation issue code is required")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("validation issue message is required")
        object.__setattr__(self, "details", dict(self.details))


@dataclass(frozen=True)
class ValidationResult:
    """Validation outcome; ``valid`` is false whenever any issue exists."""

    valid: bool
    issues: tuple[ValidationIssue, ...] = ()
    records: tuple[EvidenceRecord, ...] = ()

    def __post_init__(self) -> None:
        issues = tuple(self.issues)
        records = tuple(self.records)
        if self.valid != (not issues):
            raise ValueError("valid must reflect whether issues are present")
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "records", records)

    @property
    def ok(self) -> bool:
        """Convenient alias for callers using an ``ok`` result convention."""
        return self.valid


class Validator:
    """Validate evidence records and adapter outputs without coercion.

    By default this is an extraction-boundary validator: approved records are
    rejected, so an adapter cannot bypass human review. Set ``allow_approved``
    explicitly for a review-layer consumer.
    """

    def __init__(
        self,
        *,
        allowed_modalities: Iterable[str] = ALLOWED_MODALITIES,
        allow_approved: bool = False,
    ) -> None:
        self.allowed_modalities = frozenset(allowed_modalities)
        self.allow_approved = allow_approved

    def validate(self, value: EvidenceRecord | AdapterResult) -> ValidationResult:
        if isinstance(value, EvidenceRecord):
            return self.validate_record(value)
        if isinstance(value, AdapterResult):
            return self.validate_adapter_result(value)
        return self._result((self._issue("invalid-input", "expected EvidenceRecord or AdapterResult"),))

    def validate_record(self, record: EvidenceRecord) -> ValidationResult:
        if not isinstance(record, EvidenceRecord):
            return self._result((self._issue("invalid-record", "expected EvidenceRecord"),))
        issues: list[ValidationIssue] = []
        self._check_text(record.document_id, "document_id", issues)
        if not isinstance(record.page, int) or isinstance(record.page, bool) or record.page < 1:
            issues.append(self._issue("invalid-page", "page must be a positive integer", "page"))
        if not isinstance(record.modality, str) or record.modality not in self.allowed_modalities:
            issues.append(self._issue("unsupported-modality", "modality is not allowed", "modality", {"value": record.modality}))
        self._check_text(record.locator, "locator", issues)
        self._check_text(record.field, "field", issues)
        self._check_text(record.value, "value", issues)
        if not isinstance(record.confidence, (int, float)) or isinstance(record.confidence, bool) or not 0 <= record.confidence <= 1:
            issues.append(self._issue("invalid-confidence", "confidence must be a number between 0 and 1", "confidence"))
        if record.status not in ALLOWED_STATUSES:
            issues.append(self._issue("invalid-status", "status is not recognized", "status"))
        elif record.status == "approved" and not self.allow_approved:
            issues.append(self._issue("status-boundary", "approved evidence cannot cross the extraction boundary", "status"))
        return self._result(tuple(issues), (record,) if not issues else ())

    def validate_adapter_result(self, result: AdapterResult) -> ValidationResult:
        if not isinstance(result, AdapterResult):
            return self._result((self._issue("invalid-result", "expected AdapterResult"),))
        issues: list[ValidationIssue] = []
        records: list[EvidenceRecord] = []
        for index, record in enumerate(result.candidates):
            outcome = self.validate_record(record)
            issues.extend(self._at_path(issue, f"candidates[{index}]") for issue in outcome.issues)
            if outcome.valid:
                records.append(record)
        for index, diagnostic in enumerate(result.diagnostics):
            if diagnostic.kind == "error":
                issues.append(self._issue("adapter-error", diagnostic.message, f"diagnostics[{index}]", {"code": diagnostic.code}))
            elif diagnostic.kind == "abstention":
                code = "ambiguous-evidence" if "ambiguous" in diagnostic.code else "missing-evidence"
                issues.append(self._issue(code, diagnostic.message, f"diagnostics[{index}]", {"code": diagnostic.code}))
        if result.abstained and not result.diagnostics:
            issues.append(self._issue("missing-evidence", "adapter abstained without a diagnostic", "abstained"))
        return self._result(tuple(issues), tuple(records) if not issues else ())

    @staticmethod
    def _check_text(value: object, name: str, issues: list[ValidationIssue]) -> None:
        if not isinstance(value, str) or not value.strip():
            issues.append(ValidationIssue(f"missing-{name}", f"{name} is required", name))

    @staticmethod
    def _issue(code: str, message: str, path: str = "", details: Mapping[str, object] | None = None) -> ValidationIssue:
        return ValidationIssue(code, message, path, details or {})

    @staticmethod
    def _at_path(issue: ValidationIssue, prefix: str) -> ValidationIssue:
        return ValidationIssue(issue.code, issue.message, f"{prefix}.{issue.path}" if issue.path else prefix, issue.details)

    @staticmethod
    def _result(issues: tuple[ValidationIssue, ...], records: tuple[EvidenceRecord, ...] = ()) -> ValidationResult:
        return ValidationResult(not issues, issues, records)


__all__ = ["ALLOWED_MODALITIES", "ValidationIssue", "ValidationResult", "Validator"]
