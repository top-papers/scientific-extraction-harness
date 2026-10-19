"""Deterministic, fail-closed hard gates for candidate improvements.

The gate evaluator is deliberately a pure function.  It consumes already-produced
metrics and run metadata; it never approves records, mutates a pipeline, or
publishes an artifact.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from types import MappingProxyType
from typing import Any, Mapping

GATE_NAMES = (
    "schema", "provenance", "security", "holdout_regression",
    "unsupported_claims", "coverage", "budget", "reproducibility",
)

_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PRIVATE_URL = re.compile(r"https?://(?:localhost|127(?:\.\d{1,3}){3}|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?:[^\s\"']*)", re.I)
_TOKEN = re.compile(r"\b(?:bearer\s+|sk-|gh[pousr]_)[A-Za-z0-9._-]{8,}\b", re.I)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_freeze(v) for v in value)
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _lookup(source: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in source:
            return source[name]
        current: Any = source
        for part in name.split("."):
            if not isinstance(current, Mapping) or part not in current:
                current = None
                break
            current = current[part]
        if current is not None:
            return current
    return None


@dataclass(frozen=True)
class GatePolicy:
    """Immutable thresholds for the Phase 6 hard gates."""

    schema_version: str = "1"
    min_coverage: float = 1.0
    max_holdout_f1_regression: float = 0.02
    max_modality_regression: float = 0.05
    min_unsupported_claim_precision: float = 0.95
    max_false_approval_rate: float = 0.0
    max_input_bytes: int = 100 * 1024 * 1024
    max_candidates: int = 10_000
    max_runtime_seconds: float = 600.0
    max_memory_bytes: int = 2 * 1024 * 1024 * 1024
    max_external_calls: int = 0
    require_reproducibility: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, str) or not self.schema_version.strip():
            raise ValueError("schema_version is required")
        for name in ("min_coverage", "max_holdout_f1_regression", "max_modality_regression", "min_unsupported_claim_precision", "max_false_approval_rate", "max_runtime_seconds"):
            value = _number(getattr(self, name))
            if value is None or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")
        for name in ("max_input_bytes", "max_candidates", "max_memory_bytes", "max_external_calls"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.min_coverage > 1 or self.min_unsupported_claim_precision > 1 or self.max_false_approval_rate > 1:
            raise ValueError("rate thresholds must be between 0 and 1")


@dataclass(frozen=True)
class GateResult:
    """Immutable outcome of all gates; ``passed`` is true only when all pass."""

    passed: bool
    gate_results: Mapping[str, bool]
    failures: tuple[str, ...] = ()
    diagnostics: Mapping[str, str] = MappingProxyType({})
    policy: GatePolicy = GatePolicy()

    def __post_init__(self) -> None:
        results = {str(k): bool(v) for k, v in self.gate_results.items()}
        failures = tuple(str(item) for item in self.failures)
        diagnostics = {str(k): str(v) for k, v in self.diagnostics.items()}
        object.__setattr__(self, "gate_results", MappingProxyType(results))
        object.__setattr__(self, "failures", failures)
        object.__setattr__(self, "diagnostics", MappingProxyType(diagnostics))
        object.__setattr__(self, "passed", bool(self.passed) and all(results.get(name, False) for name in GATE_NAMES))

    @property
    def approved(self) -> bool:
        """Compatibility spelling; a gate result never performs approval."""
        return self.passed

    def gate_passed(self, name: str) -> bool:
        return bool(self.gate_results[name])


def _leakage(value: Any, key: str = "") -> bool:
    if isinstance(value, Mapping):
        for name, item in value.items():
            lowered = str(name).lower()
            if lowered in {"raw_transcript", "prompt", "secret", "token", "credential", "password"} and item:
                return True
            if _leakage(item, lowered):
                return True
        return False
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_leakage(item, key) for item in value)
    if isinstance(value, str):
        return bool(_EMAIL.search(value) or _PRIVATE_URL.search(value) or _TOKEN.search(value) or "raw transcript" in value.lower())
    return False


def _budget_ok(metrics: Mapping[str, Any], metadata: Mapping[str, Any], policy: GatePolicy) -> tuple[bool, str]:
    raw = _lookup(metadata, "budget", "budgets")
    if not isinstance(raw, Mapping):
        raw = _lookup(metrics, "budget", "budgets")
    if not isinstance(raw, Mapping):
        return False, "budget metrics are missing"
    checks = (("input_bytes", policy.max_input_bytes), ("candidates", policy.max_candidates),
              ("runtime_seconds", policy.max_runtime_seconds), ("memory_bytes", policy.max_memory_bytes),
              ("external_calls", policy.max_external_calls))
    for name, limit in checks:
        used = _lookup(raw, name, f"used_{name}")
        if _number(used) is None:
            return False, f"budget.{name} is missing or invalid"
        if float(used) > float(limit):
            return False, f"budget.{name} exceeds limit"
    return True, "within configured limits"


def evaluate_gates(metrics: Mapping[str, Any], candidate_metadata: Mapping[str, Any], policy: GatePolicy | None = None) -> GateResult:
    """Evaluate Phase 6 gates from supplied values, failing closed on omissions."""
    if not isinstance(metrics, Mapping) or not isinstance(candidate_metadata, Mapping):
        raise TypeError("metrics and candidate_metadata must be mappings")
    policy = policy or GatePolicy()
    m, meta = metrics, candidate_metadata
    results: dict[str, bool] = {}
    diagnostics: dict[str, str] = {}

    schema = _lookup(meta, "schema_valid", "schema_ok")
    results["schema"] = schema is True
    diagnostics["schema"] = "valid" if results["schema"] else "schema validation is missing or failed"

    provenance = _lookup(meta, "provenance_complete", "provenance_valid")
    results["provenance"] = provenance is True
    diagnostics["provenance"] = "complete" if results["provenance"] else "complete provenance is missing or failed"

    false_approval = _number(_lookup(m, "false_approval_rate", "false_approvals"))
    explicit_leak = _lookup(meta, "leakage_detected", "security_violation")
    results["security"] = false_approval is not None and false_approval <= policy.max_false_approval_rate and explicit_leak is False and not _leakage(meta)
    diagnostics["security"] = "no false approvals or leakage" if results["security"] else "false approval, leakage, or security evidence missing"

    current = _number(_lookup(m, "holdout_f1", "holdout.f1"))
    baseline = _number(_lookup(m, "baseline_holdout_f1", "baseline_f1"))
    delta = None if current is None or baseline is None else baseline - current
    modality = _lookup(m, "modality_f1", "holdout_modality_f1")
    modality_base = _lookup(m, "baseline_modality_f1", "baseline_holdout_modality_f1")
    modality_ok = True
    if modality is not None or modality_base is not None:
        modality_ok = isinstance(modality, Mapping) and isinstance(modality_base, Mapping)
        if modality_ok:
            modality_ok = all(_number(modality.get(k)) is not None and _number(modality_base.get(k)) is not None and float(modality_base[k]) - float(modality[k]) <= policy.max_modality_regression for k in set(modality) | set(modality_base))
    results["holdout_regression"] = delta is not None and delta <= policy.max_holdout_f1_regression and modality_ok
    diagnostics["holdout_regression"] = "within regression limits" if results["holdout_regression"] else "holdout baseline/current or modality metrics are missing or regressed"

    unsupported = _number(_lookup(m, "unsupported_claim_precision", "abstention_precision"))
    results["unsupported_claims"] = unsupported is not None and unsupported >= policy.min_unsupported_claim_precision
    diagnostics["unsupported_claims"] = "unsupported claims handled" if results["unsupported_claims"] else "unsupported-claim metric is missing or below threshold"

    coverage = _number(_lookup(m, "coverage", "provenance_coverage"))
    results["coverage"] = coverage is not None and coverage >= policy.min_coverage
    diagnostics["coverage"] = "coverage meets threshold" if results["coverage"] else "coverage is missing or below threshold"

    results["budget"], diagnostics["budget"] = _budget_ok(m, meta, policy)

    reproducible = _lookup(meta, "reproducible", "reproducibility")
    hashes = _lookup(meta, "candidate_hashes", "repeat_candidate_hashes")
    if reproducible is not None:
        reproducible_ok = reproducible is True
    elif isinstance(hashes, (list, tuple)) and len(hashes) == 2:
        reproducible_ok = hashes[0] == hashes[1]
    else:
        reproducible_ok = False
    results["reproducibility"] = reproducible_ok if policy.require_reproducibility else True
    diagnostics["reproducibility"] = "deterministic" if results["reproducibility"] else "reproducibility evidence is missing or differs"

    failures = tuple(name for name in GATE_NAMES if not results[name])
    return GateResult(not failures, results, failures, diagnostics, policy)

# Clear aliases for callers that prefer noun/verb naming.
evaluate = evaluate_gates
run_gates = evaluate_gates

__all__ = ["GATE_NAMES", "GatePolicy", "GateResult", "evaluate_gates", "evaluate", "run_gates"]
