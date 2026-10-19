"""Deterministic, explainable confidence scoring for extraction candidates.

Confidence is an extractor signal only.  It does not change an evidence
record's review status and it can never approve a candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping


CONFIDENCE_POLICY_VERSION = "1"


def _score(value: float, name: str) -> float:
    """Validate and return a finite score in the inclusive unit interval."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number between 0 and 1")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


@dataclass(frozen=True)
class ConfidenceResult:
    """The score and its inputs, retained so a reviewer can explain it."""

    confidence: float
    locator_quality: float
    parser_agreement: float
    source_quality: float
    ocr_quality: float | None
    weak_locator: bool
    locator_penalty: float
    policy_version: str = CONFIDENCE_POLICY_VERSION
    explanations: tuple[str, ...] = field(default_factory=tuple)
    record_type: str = field(default="confidence_result", init=False)

    def __post_init__(self) -> None:
        _score(self.confidence, "confidence")
        _score(self.locator_quality, "locator_quality")
        _score(self.parser_agreement, "parser_agreement")
        _score(self.source_quality, "source_quality")
        if self.ocr_quality is not None:
            _score(self.ocr_quality, "ocr_quality")
        _score(self.locator_penalty, "locator_penalty")
        if not self.policy_version.strip():
            raise ValueError("policy_version is required")

    @property
    def components(self) -> dict[str, float]:
        """Return the component values in stable, JSON-friendly form."""
        result = {
            "locator_quality": self.locator_quality,
            "parser_agreement": self.parser_agreement,
            "source_quality": self.source_quality,
        }
        if self.ocr_quality is not None:
            result["ocr_quality"] = self.ocr_quality
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize without introducing review or approval state."""
        return {
            "record_type": self.record_type,
            "policy_version": self.policy_version,
            "confidence": self.confidence,
            "components": self.components,
            "weak_locator": self.weak_locator,
            "locator_penalty": self.locator_penalty,
            "explanations": list(self.explanations),
        }


@dataclass(frozen=True)
class ConfidencePolicy:
    """Versioned policy for composing extraction confidence.

    The base score is a weighted arithmetic mean.  A locator below
    ``weak_locator_threshold`` receives an additional multiplicative penalty;
    this makes a weak/ambiguous locator materially reduce confidence even when
    parser and source signals are strong.
    """

    version: str = CONFIDENCE_POLICY_VERSION
    locator_weight: float = 0.4
    parser_weight: float = 0.35
    source_weight: float = 0.25
    weak_locator_threshold: float = 0.5
    weak_locator_penalty: float = 0.75

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version is required")
        for name in ("locator_weight", "parser_weight", "source_weight"):
            _score(getattr(self, name), name)
        if sum((self.locator_weight, self.parser_weight, self.source_weight)) <= 0:
            raise ValueError("at least one component weight is required")
        _score(self.weak_locator_threshold, "weak_locator_threshold")
        _score(self.weak_locator_penalty, "weak_locator_penalty")

    def score(
        self,
        *,
        locator_quality: float,
        parser_agreement: float,
        source_quality: float,
        ocr_quality: float | None = None,
    ) -> ConfidenceResult:
        """Compose component signals into a bounded, explainable result.

        ``ocr_quality`` is optional.  When supplied it is averaged with source
        quality before the configured source weight is applied, which avoids
        silently treating OCR quality as parser agreement or locator quality.
        """
        locator = _score(locator_quality, "locator_quality")
        parser = _score(parser_agreement, "parser_agreement")
        source = _score(source_quality, "source_quality")
        ocr = None if ocr_quality is None else _score(ocr_quality, "ocr_quality")
        effective_source = source if ocr is None else (source + ocr) / 2.0

        total_weight = self.locator_weight + self.parser_weight + self.source_weight
        base = (
            self.locator_weight * locator
            + self.parser_weight * parser
            + self.source_weight * effective_source
        ) / total_weight
        weak = locator < self.weak_locator_threshold
        penalty = self.weak_locator_penalty if weak else 1.0
        confidence = round(max(0.0, min(1.0, base * penalty)), 12)

        explanations = [
            f"weighted mean of locator_quality, parser_agreement, and source_quality: {base:.12g}",
        ]
        if ocr is not None:
            explanations.append("source_quality and ocr_quality were averaged")
        if weak:
            explanations.append(
                f"locator_quality below {self.weak_locator_threshold:g}; "
                f"applied penalty {self.weak_locator_penalty:g}"
            )
        else:
            explanations.append("locator_quality met the weak-locator threshold; no penalty applied")

        return ConfidenceResult(
            confidence=confidence,
            locator_quality=locator,
            parser_agreement=parser,
            source_quality=source,
            ocr_quality=ocr,
            weak_locator=weak,
            locator_penalty=penalty,
            policy_version=self.version,
            explanations=tuple(explanations),
        )

    # These names make the policy convenient at call sites while retaining one
    # implementation and therefore one deterministic composition rule.
    evaluate = score
    calculate = score

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.version,
            "locator_weight": self.locator_weight,
            "parser_weight": self.parser_weight,
            "source_weight": self.source_weight,
            "weak_locator_threshold": self.weak_locator_threshold,
            "weak_locator_penalty": self.weak_locator_penalty,
        }


def compose_confidence(
    *,
    locator_quality: float,
    parser_agreement: float,
    source_quality: float,
    ocr_quality: float | None = None,
    policy: ConfidencePolicy | None = None,
) -> ConfidenceResult:
    """Convenience wrapper using the default versioned policy."""
    return (policy or ConfidencePolicy()).score(
        locator_quality=locator_quality,
        parser_agreement=parser_agreement,
        source_quality=source_quality,
        ocr_quality=ocr_quality,
    )
