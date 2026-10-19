"""Dependency-free contracts shared by scientific extraction adapters.

Adapters are deliberately kept at the candidate boundary: they may suggest
 evidence, but review code is the only code allowed to approve it.  This
module contains no document parsing, model, or network integrations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Protocol, Sequence, Literal, runtime_checkable

from ..contracts import ExtractorApprovalError, validate_extractor_record
from ..evidence import EvidenceRecord
from ..ingest import IngestedDocument


DiagnosticKind = Literal["abstention", "error", "warning", "info"]


@dataclass(frozen=True)
class AdapterDiagnostic:
    """A structured explanation of an adapter outcome.

    ``details`` is metadata only; adapters must not put source text, prompts,
    credentials, or other sensitive data in it.
    """

    kind: DiagnosticKind
    code: str
    message: str
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in ("abstention", "error", "warning", "info"):
            raise ValueError(f"unsupported diagnostic kind: {self.kind}")
        if not self.code.strip():
            raise ValueError("diagnostic code is required")
        if not self.message.strip():
            raise ValueError("diagnostic message is required")
        object.__setattr__(self, "details", dict(self.details))


@dataclass(frozen=True)
class AdapterResult:
    """Candidates and diagnostics returned from one adapter invocation."""

    candidates: tuple[EvidenceRecord, ...] = ()
    diagnostics: tuple[AdapterDiagnostic, ...] = ()
    abstained: bool = False

    def __post_init__(self) -> None:
        candidates = tuple(self.candidates)
        diagnostics = tuple(self.diagnostics)
        # Validate at construction, rather than trusting individual adapters.
        # In particular this raises if an adapter attempts to emit approved.
        for record in candidates:
            validate_extractor_record(record)
        if self.abstained and not any(d.kind == "abstention" for d in diagnostics):
            raise ValueError("abstained results require an abstention diagnostic")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "diagnostics", diagnostics)

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        """Compatibility alias for callers that call outputs records."""
        return self.candidates

    @property
    def errors(self) -> tuple[AdapterDiagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.kind == "error")


def abstain(code: str, message: str, *, details: Mapping[str, object] | None = None) -> AdapterResult:
    """Return an explicit, successful abstention instead of an empty success."""
    diagnostic = AdapterDiagnostic("abstention", code, message, details or {})
    return AdapterResult(abstained=True, diagnostics=(diagnostic,))


def adapter_error(code: str, message: str, *, details: Mapping[str, object] | None = None) -> AdapterResult:
    """Build a structured adapter failure without exposing an exception."""
    diagnostic = AdapterDiagnostic("error", code, message, details or {})
    return AdapterResult(diagnostics=(diagnostic,))


def candidate(record: EvidenceRecord) -> EvidenceRecord:
    """Validate one adapter output and enforce the candidate-only boundary."""
    return validate_extractor_record(record)


@runtime_checkable
class ExtractionAdapter(Protocol):
    """Minimal local extraction adapter contract."""

    adapter_id: str
    adapter_version: str

    def extract(
        self,
        document: IngestedDocument,
        *,
        config: Mapping[str, object],
    ) -> AdapterResult: ...


def run_adapter(
    adapter: ExtractionAdapter,
    document: IngestedDocument,
    *,
    config: Mapping[str, object] | None = None,
) -> AdapterResult:
    """Invoke an adapter and turn ordinary failures into diagnostics.

    Approval attempts remain distinguishable through ``boundary-approved``;
    they are not converted into candidates or silently ignored.
    """
    try:
        result = adapter.extract(document, config=config or {})
        if not isinstance(result, AdapterResult):
            return adapter_error(
                "invalid-result",
                "adapter must return AdapterResult",
                details={"result_type": type(result).__name__},
            )
        return result
    except ExtractorApprovalError as exc:
        return adapter_error("boundary-approved", str(exc))
    except Exception as exc:  # adapter failures are part of the run record
        return adapter_error(
            "adapter-error",
            f"adapter failed: {exc}",
            details={"exception_type": type(exc).__name__},
        )


__all__ = [
    "AdapterDiagnostic",
    "AdapterResult",
    "DiagnosticKind",
    "ExtractionAdapter",
    "abstain",
    "adapter_error",
    "candidate",
    "run_adapter",
]
