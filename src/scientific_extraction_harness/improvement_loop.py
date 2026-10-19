"""Offline, fail-closed decisions for candidate improvements.

This module is intentionally a decision/reporting boundary.  It does not run
candidate code, invoke models or services, mutate a registry, approve data, or
promote a candidate.  A ``promote`` recommendation is only a recommendation
for a human review workflow.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Any, Mapping

from .gates import GatePolicy, GateResult, evaluate_gates
from .improvement import CandidateManifest, CandidateRegistry


RECOMMENDATIONS = frozenset({"promote", "reject", "needs_review"})


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_freeze(v) for v in value)
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _metric_deltas(metrics: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return deterministic candidate-minus-baseline deltas.

    Metrics use the evaluator's existing ``baseline_<name>`` convention.  A
    nested modality mapping is also handled for the common F1 metrics.  Missing
    or non-numeric pairs are deliberately omitted rather than guessed.
    """
    result: dict[str, Any] = {}
    for key, current in metrics.items():
        if str(key).startswith("baseline_"):
            continue
        baseline_key = f"baseline_{key}"
        if baseline_key in metrics:
            baseline = metrics[baseline_key]
            current_number, baseline_number = _number(current), _number(baseline)
            if current_number is not None and baseline_number is not None:
                result[str(key)] = current_number - baseline_number
            elif isinstance(current, Mapping) and isinstance(baseline, Mapping):
                nested: dict[str, float] = {}
                for name in sorted(set(current) | set(baseline)):
                    c, b = _number(current.get(name)), _number(baseline.get(name))
                    if c is not None and b is not None:
                        nested[str(name)] = c - b
                if nested:
                    result[str(key)] = nested
    return MappingProxyType({key: _freeze(value) for key, value in result.items()})


@dataclass(frozen=True)
class ImprovementDecision:
    """Immutable, non-approving outcome of one offline gate evaluation."""

    candidate_id: str
    parent_id: str | None
    hypothesis: str
    gate_result: GateResult
    metric_deltas: Mapping[str, Any]
    recommendation: str

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id:
            raise ValueError("candidate_id is required")
        if not isinstance(self.hypothesis, str) or not self.hypothesis.strip():
            raise ValueError("hypothesis is required")
        if not isinstance(self.gate_result, GateResult):
            raise TypeError("gate_result must be a GateResult")
        if self.recommendation not in RECOMMENDATIONS:
            raise ValueError("invalid recommendation")
        object.__setattr__(self, "metric_deltas", _freeze(self.metric_deltas))


@dataclass(frozen=True)
class ReviewPacket:
    """Immutable packet for a human reviewer; never an approval record."""

    candidate_id: str
    parent_id: str | None
    hypothesis: str
    gate_result: GateResult
    metric_deltas: Mapping[str, Any]
    recommendation: str
    decision: ImprovementDecision

    def __post_init__(self) -> None:
        if not isinstance(self.decision, ImprovementDecision):
            raise TypeError("decision must be an ImprovementDecision")
        if self.candidate_id != self.decision.candidate_id:
            raise ValueError("packet and decision candidate_id differ")
        if self.recommendation not in RECOMMENDATIONS:
            raise ValueError("invalid recommendation")
        object.__setattr__(self, "metric_deltas", _freeze(self.metric_deltas))


class ImprovementController:
    """Build decisions using only supplied manifests, metrics, and metadata."""

    def __init__(self, registry: CandidateRegistry | None = None) -> None:
        self.registry = registry

    def decide(
        self,
        manifest: CandidateManifest,
        metrics: Mapping[str, Any],
        candidate_metadata: Mapping[str, Any],
        policy: GatePolicy,
    ) -> ImprovementDecision:
        if not isinstance(manifest, CandidateManifest):
            raise TypeError("manifest must be a CandidateManifest")
        if not isinstance(metrics, Mapping) or not isinstance(candidate_metadata, Mapping):
            raise TypeError("metrics and candidate_metadata must be mappings")
        if not isinstance(policy, GatePolicy):
            raise TypeError("policy must be a GatePolicy")
        if self.registry is not None:
            registered = self.registry.get(manifest.candidate_id)
            if registered != manifest:
                raise ValueError("candidate manifest is not registered")

        gates = evaluate_gates(metrics, candidate_metadata, policy)
        # Missing evidence is not a safe rejection of the candidate's content;
        # it is a request for a reviewer to supply/inspect the missing evidence.
        # Explicitly failed safety, regression, or budget evidence remains reject.
        missing = any(
            "missing" in gates.diagnostics.get(name, "").lower()
            for name in gates.failures
        )
        # Distinguish absent evidence from an observed unsafe/regressed result.
        # The latter must never be softened into a review-only recommendation.
        explicit_security_failure = (
            candidate_metadata.get("leakage_detected") is True
            or candidate_metadata.get("security_violation") is True
            or (_number(metrics.get("false_approval_rate")) is not None
                and _number(metrics.get("false_approval_rate")) > policy.max_false_approval_rate)
        )
        explicit_regression = (
            _number(metrics.get("holdout_f1")) is not None
            and _number(metrics.get("baseline_holdout_f1")) is not None
            and _number(metrics["baseline_holdout_f1"]) - _number(metrics["holdout_f1"]) > policy.max_holdout_f1_regression
        )
        recommendation = "promote" if gates.passed else (
            "reject" if explicit_security_failure or explicit_regression else
            ("needs_review" if missing else "reject")
        )
        return ImprovementDecision(
            candidate_id=manifest.candidate_id,
            parent_id=manifest.parent_id,
            hypothesis=manifest.hypothesis,
            gate_result=gates,
            metric_deltas=_metric_deltas(metrics),
            recommendation=recommendation,
        )

    def review_packet(self, *args: Any, **kwargs: Any) -> ReviewPacket:
        decision = self.decide(*args, **kwargs)
        return ReviewPacket(
            candidate_id=decision.candidate_id,
            parent_id=decision.parent_id,
            hypothesis=decision.hypothesis,
            gate_result=decision.gate_result,
            metric_deltas=decision.metric_deltas,
            recommendation=decision.recommendation,
            decision=decision,
        )


def decide_improvement(*args: Any, **kwargs: Any) -> ImprovementDecision:
    """Convenience API for callers without a registry."""
    return ImprovementController().decide(*args, **kwargs)


__all__ = [
    "RECOMMENDATIONS", "ImprovementDecision", "ReviewPacket",
    "ImprovementController", "decide_improvement",
]
