"""Local, deterministic extraction orchestration.

The pipeline is intentionally a thin boundary around existing adapters,
validation, and normalization.  It never approves or repairs evidence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from time import monotonic
from typing import Any, Iterable, Mapping, Sequence

from .adapters.base import AdapterDiagnostic, AdapterResult, ExtractionAdapter, run_adapter
from .contracts import Candidate, SCHEMA_VERSION
from .evidence import EvidenceRecord
from .normalize import NormalizationResult, NormalizationRule, normalize_record
from .validate import ValidationIssue, ValidationResult, Validator


@dataclass(frozen=True)
class PipelineBudget:
    """Hard limits for one invocation. ``None`` means no limit."""

    max_candidates: int | None = None
    max_input_bytes: int | None = None
    max_runtime_seconds: float | None = None

    def __post_init__(self) -> None:
        for name in ("max_candidates", "max_input_bytes"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")
        if self.max_runtime_seconds is not None and (
            isinstance(self.max_runtime_seconds, bool) or self.max_runtime_seconds < 0
        ):
            raise ValueError("max_runtime_seconds must be non-negative or None")

    @classmethod
    def from_config(cls, config: Mapping[str, object] | None) -> "PipelineBudget":
        config = config or {}
        value = config.get("budget", config.get("budgets", {}))
        source = value if isinstance(value, Mapping) else config
        return cls(
            max_candidates=source.get("max_candidates"),
            max_input_bytes=source.get("max_input_bytes"),
            max_runtime_seconds=source.get("max_runtime_seconds"),
        )


@dataclass(frozen=True)
class PipelineResult:
    """Complete, structured outcome of a fail-closed pipeline run."""

    run_id: str
    seed: int
    ok: bool
    candidates: tuple[Candidate, ...] = ()
    adapter_results: tuple[AdapterResult, ...] = ()
    validations: tuple[ValidationResult, ...] = ()
    normalized: Mapping[str, NormalizationResult] = field(default_factory=dict)
    issues: tuple[ValidationIssue, ...] = ()
    diagnostics: tuple[AdapterDiagnostic, ...] = ()
    errors: tuple[str, ...] = ()
    budget: PipelineBudget = field(default_factory=PipelineBudget)
    budget_exceeded: bool = False
    external_calls: bool = False
    elapsed_seconds: float = 0.0

    @property
    def incomplete(self) -> bool:
        return not self.ok

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id, "seed": self.seed, "ok": self.ok,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "issues": [asdict(issue) for issue in self.issues],
            "diagnostics": [asdict(item) for item in self.diagnostics],
            "errors": list(self.errors), "budget_exceeded": self.budget_exceeded,
            "external_calls": self.external_calls, "elapsed_seconds": self.elapsed_seconds,
            "normalized": {key: value.to_dict() for key, value in self.normalized.items()},
        }


def _candidate_hash(run_id: str, seed: int, adapter: ExtractionAdapter, record: EvidenceRecord) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION, "run_id": run_id, "seed": seed,
        "adapter_id": str(getattr(adapter, "adapter_id", type(adapter).__name__)),
        "adapter_version": str(getattr(adapter, "adapter_version", "unknown")),
        "evidence": record.to_dict(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def run_extract(
    document: Any,
    adapters: ExtractionAdapter | Sequence[ExtractionAdapter],
    *,
    run_id: str,
    seed: int = 0,
    config: Mapping[str, object] | None = None,
    validator: Validator | None = None,
    normalization_rules: Iterable[NormalizationRule] | None = None,
    normalize: bool = False,
    budget: PipelineBudget | None = None,
) -> PipelineResult:
    """Run local adapters, validate atomically, and optionally normalize.

    Any adapter failure, validation issue, forbidden external-call request, or
    budget violation makes the whole result incomplete and emits no candidates.
    Runtime is checked before and after adapter calls; Python cannot safely
    interrupt an arbitrary adapter in the middle of a call.
    """
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id is required")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    cfg = dict(config or {})
    selected_budget = budget or PipelineBudget.from_config(cfg)
    started = monotonic()
    external = bool(cfg.get("external_calls", cfg.get("allow_external_calls", False)))
    adapter_list = (adapters,) if not isinstance(adapters, Sequence) or isinstance(adapters, (str, bytes)) else tuple(adapters)
    diagnostics: list[AdapterDiagnostic] = []
    errors: list[str] = []
    validations: list[ValidationResult] = []
    results: list[AdapterResult] = []
    raw_records: list[tuple[ExtractionAdapter, EvidenceRecord]] = []
    exceeded = False

    content = getattr(document, "content", None)
    if isinstance(content, (bytes, bytearray)) and selected_budget.max_input_bytes is not None and len(content) > selected_budget.max_input_bytes:
        exceeded = True
        errors.append("max_input_bytes exceeded")
    if external:
        errors.append("external calls are disabled")
    if not adapter_list:
        errors.append("at least one adapter is required")

    if not errors:
        for adapter in adapter_list:
            if selected_budget.max_runtime_seconds is not None and monotonic() - started > selected_budget.max_runtime_seconds:
                exceeded = True
                errors.append("max_runtime_seconds exceeded")
                break
            result = run_adapter(adapter, document, config=cfg)
            results.append(result)
            diagnostics.extend(result.diagnostics)
            validation = (validator or Validator()).validate(result)
            validations.append(validation)
            raw_records.extend((adapter, record) for record in validation.records)
            if not validation.valid:
                errors.append("adapter result failed validation")
            if selected_budget.max_candidates is not None and len(raw_records) > selected_budget.max_candidates:
                exceeded = True
                errors.append("max_candidates exceeded")
                break
            if selected_budget.max_runtime_seconds is not None and monotonic() - started > selected_budget.max_runtime_seconds:
                exceeded = True
                errors.append("max_runtime_seconds exceeded")
                break

    elapsed = monotonic() - started
    if selected_budget.max_runtime_seconds is not None and elapsed > selected_budget.max_runtime_seconds and "max_runtime_seconds exceeded" not in errors:
        exceeded = True
        errors.append("max_runtime_seconds exceeded")

    ok = not errors and bool(validations) and all(item.valid for item in validations)
    candidates: list[Candidate] = []
    normalized: dict[str, NormalizationResult] = {}
    if ok:
        rules = tuple(normalization_rules or cfg.get("normalization_rules", ()))
        for adapter, record in raw_records:
            candidate_id = _candidate_hash(run_id, seed, adapter, record)
            candidates.append(Candidate(candidate_id, run_id, record))
            if normalize:
                normalized[candidate_id] = normalize_record(record, rules)
    else:
        # Fail closed: a partial run must never look exportable.
        candidates = []
    issues = tuple(issue for result in validations for issue in result.issues)
    return PipelineResult(
        run_id=run_id, seed=seed, ok=ok, candidates=tuple(candidates),
        adapter_results=tuple(results), validations=tuple(validations), normalized=normalized,
        issues=issues, diagnostics=tuple(diagnostics), errors=tuple(dict.fromkeys(errors)),
        budget=selected_budget, budget_exceeded=exceeded, external_calls=external,
        elapsed_seconds=elapsed,
    )


__all__ = ["PipelineBudget", "PipelineResult", "run_extract"]
