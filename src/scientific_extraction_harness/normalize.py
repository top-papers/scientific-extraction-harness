"""Deterministic, reversible normalization of extracted values and units.

Normalization is deliberately fail-closed: only explicitly registered rules are
used.  A missing, unknown, or ambiguous unit produces an abstention rather than
an inferred conversion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

NORMALIZATION_SCHEMA_VERSION = "1"


class NormalizationError(ValueError):
    """Raised by strict normalization when a value cannot be normalized."""


@dataclass(frozen=True)
class NormalizationRule:
    """One versioned, explicit affine conversion rule.

    ``factor`` and ``offset`` are applied as ``value * factor + offset``.  Unit
    aliases are opt-in; no fuzzy unit matching is performed.
    """

    rule_id: str
    source_unit: str
    target_unit: str
    factor: Decimal | int | float | str = Decimal("1")
    offset: Decimal | int | float | str = Decimal("0")
    source_aliases: tuple[str, ...] = ()
    field: str | None = None
    version: str = NORMALIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name, value in (("rule_id", self.rule_id), ("source_unit", self.source_unit), ("target_unit", self.target_unit)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        if self.version != NORMALIZATION_SCHEMA_VERSION:
            raise ValueError(f"unsupported normalization version: {self.version}")
        if self.field is not None and not self.field.strip():
            raise ValueError("field must be non-empty when provided")
        object.__setattr__(self, "source_aliases", tuple(self.source_aliases))
        try:
            factor = Decimal(str(self.factor))
            offset = Decimal(str(self.offset))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("factor and offset must be numeric") from exc
        if not factor.is_finite() or not offset.is_finite():
            raise ValueError("factor and offset must be finite")
        if factor == 0:
            raise ValueError("factor must not be zero")
        object.__setattr__(self, "factor", factor)
        object.__setattr__(self, "offset", offset)

    @property
    def accepted_units(self) -> tuple[str, ...]:
        return (self.source_unit, *self.source_aliases)

    def matches(self, unit: str | None, field_name: str | None = None) -> bool:
        return (
            unit is not None
            and _unit_key(unit) in {_unit_key(item) for item in self.accepted_units}
            and (self.field is None or self.field == field_name)
        )


@dataclass(frozen=True)
class NormalizationTrace:
    """The complete reversible operation applied to one source value."""

    source_value: str
    source_unit: str | None
    factor: str
    offset: str
    target_unit: str

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizationResult:
    """Normalized output while retaining the exact source representation."""

    source_value: Any
    source_unit: str | None
    normalized_value: str | None
    normalized_unit: str | None
    rule_id: str | None
    trace: NormalizationTrace | None
    status: str = "normalized"
    schema_version: str = NORMALIZATION_SCHEMA_VERSION
    reason: str | None = None

    def __post_init__(self) -> None:
        # Infer the status for callers constructing a result directly while
        # keeping the explicit status used by normalize_value stable.
        if self.status == "normalized" and self.normalized_value is None:
            object.__setattr__(self, "status", "abstained")
        elif self.status == "abstained" and self.normalized_value is not None:
            object.__setattr__(self, "status", "normalized")
        if self.status not in {"normalized", "abstained"}:
            raise ValueError("status must be normalized or abstained")
        if self.schema_version != NORMALIZATION_SCHEMA_VERSION:
            raise ValueError(f"unsupported normalization version: {self.schema_version}")

    @property
    def abstained(self) -> bool:
        return self.status == "abstained"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.trace is not None:
            result["trace"] = self.trace.to_dict()
        return result

    def reverse(self) -> tuple[Any, str | None]:
        """Return the untouched source value and unit."""
        return self.source_value, self.source_unit


def _unit_key(unit: str) -> str:
    return " ".join(unit.strip().casefold().split())


def _format_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def normalize_value(
    value: Any,
    unit: str | None,
    rules: Iterable[NormalizationRule],
    *,
    field: str | None = None,
    strict: bool = False,
) -> NormalizationResult:
    """Normalize one value using exactly one matching rule.

    Unknown and ambiguous mappings abstain by default.  ``strict=True`` turns
    those cases (and malformed numeric values) into ``NormalizationError``.
    """
    rule_list = tuple(rules)
    matches = tuple(rule for rule in rule_list if rule.matches(unit, field))
    source_unit = unit
    if len(matches) != 1:
        reason = "unknown unit mapping" if not matches else "ambiguous unit mapping"
        if strict:
            raise NormalizationError(reason)
        return NormalizationResult(value, source_unit, None, None, None, None, "abstained", reason=reason)
    rule = matches[0]
    # Temperature-like offsets are defined relative to the source unit; a
    # single affine rule remains explicit and deterministic.
    try:
        source_number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        if strict:
            raise NormalizationError("value is not numeric") from exc
        return NormalizationResult(value, source_unit, None, None, None, None, "abstained", reason="value is not numeric")
    if not source_number.is_finite():
        if strict:
            raise NormalizationError("value is not finite")
        return NormalizationResult(value, source_unit, None, None, None, None, "abstained", reason="value is not finite")
    normalized = source_number * rule.factor + rule.offset
    trace = NormalizationTrace(str(value), source_unit, str(rule.factor), str(rule.offset), rule.target_unit)
    return NormalizationResult(value, source_unit, _format_decimal(normalized), rule.target_unit, rule.rule_id, trace)


def normalize_record(record: Any, rules: Iterable[NormalizationRule], *, strict: bool = False) -> NormalizationResult:
    """Normalize an EvidenceRecord-like object without mutating it."""
    return normalize_value(record.value, record.unit, rules, field=getattr(record, "field", None), strict=strict)


__all__ = [
    "NORMALIZATION_SCHEMA_VERSION",
    "NormalizationError",
    "NormalizationRule",
    "NormalizationTrace",
    "NormalizationResult",
    "normalize_value",
    "normalize_record",
]
