"""Deterministic, dependency-free page triage and adapter routing."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping


@dataclass(frozen=True)
class PageFeatures:
    page: int
    text_chars: int = 0
    embedded_images: int = 0
    vector_ratio: float = 0.0
    has_table: bool = False
    has_figure: bool = False
    has_chart: bool = False
    formula_heavy: bool = False
    parser_complete: bool = True
    ocr_confidence: float | None = None
    reading_order_broken: bool = False
    language: str | None = None
    cost: int = 1

    def __post_init__(self) -> None:
        if self.page < 1: raise ValueError("page must be at least 1")
        if self.text_chars < 0 or self.embedded_images < 0 or self.cost < 0: raise ValueError("counts and cost must be non-negative")
        if not 0 <= self.vector_ratio <= 1: raise ValueError("vector_ratio must be between 0 and 1")
        if self.ocr_confidence is not None and not 0 <= self.ocr_confidence <= 1: raise ValueError("ocr_confidence must be between 0 and 1")

    @property
    def text_density(self) -> str:
        if self.text_chars == 0 or not self.parser_complete: return "missing"
        if self.text_chars < 200: return "low"
        return "normal"


@dataclass(frozen=True)
class AdapterPolicy:
    allowed_modalities: frozenset[str] = frozenset({"text", "table", "figure", "ocr", "chart", "vlm"})
    budgets: Mapping[str, int] = field(default_factory=dict)
    external_calls: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_modalities", frozenset(self.allowed_modalities))
        object.__setattr__(self, "budgets", dict(self.budgets))
        if any(v < 0 for v in self.budgets.values()): raise ValueError("budgets must be non-negative")


@dataclass(frozen=True)
class RouteDecision:
    page: int
    classification: str
    adapters: tuple[str, ...]
    reasons: tuple[str, ...]
    abstained: bool = False
    abstention_reasons: tuple[str, ...] = ()


def classify_page(features: PageFeatures) -> str:
    """Classify using only supplied features; ordering is intentional and stable."""
    if features.text_chars == 0 or not features.parser_complete: return "scan"
    if features.ocr_confidence is not None and features.ocr_confidence < 0.70: return "low_quality_text"
    if features.reading_order_broken or features.formula_heavy: return "complex_layout"
    if features.has_chart: return "chart"
    if features.has_table: return "table"
    if features.has_figure or features.embedded_images: return "figure"
    return "born_digital"


def route_page(features: PageFeatures, policy: AdapterPolicy | None = None) -> RouteDecision:
    policy = policy or AdapterPolicy()
    kind = classify_page(features)
    selected: list[str] = []
    reasons: list[str] = [f"classification:{kind}"]
    abstentions: list[str] = []

    def add(adapter: str, modality: str, why: str, *, external: bool = False) -> None:
        if modality not in policy.allowed_modalities:
            abstentions.append(f"modality-not-allowed:{modality}"); return
        if external and not policy.external_calls:
            abstentions.append(f"external-calls-disabled:{adapter}"); return
        if policy.budgets.get(adapter, 1) <= 0:
            abstentions.append(f"budget-exhausted:{adapter}"); return
        selected.append(adapter); reasons.append(why)

    if kind == "born_digital":
        add("docling", "text", "parser text is complete")
        add("grobid", "text", "scholarly structure companion")
    elif kind == "scan" or kind == "low_quality_text":
        add("paddleocr", "ocr", "text is missing or below confidence threshold")
        add("tesseract", "ocr", "deterministic OCR fallback")
    elif kind == "complex_layout":
        add("docling", "text", "retain parser output")
        add("marker", "text", "compare broken order or formula-heavy layout")
        add("mineru", "table", "compare dense layout/table extraction")
    elif kind == "table":
        add("docling", "table", "table detected")
    elif kind == "figure":
        add("docling", "figure", "figure/image detected")
    elif kind == "chart":
        add("source_table", "table", "source-table lookup precedes digitization")
        add("chart", "chart", "chart requires calibrated digitization")

    if features.has_chart and "chart" not in selected and "modality-not-allowed:chart" in abstentions:
        reasons.append("chart-digitization-abstained")
    if not selected:
        abstentions.append("no-eligible-adapter")
    return RouteDecision(features.page, kind, tuple(selected), tuple(reasons), bool(abstentions and not selected), tuple(abstentions))


def triage_page(features: PageFeatures, policy: AdapterPolicy | None = None) -> RouteDecision:
    return route_page(features, policy)


def route_pages(features: Iterable[PageFeatures], policy: AdapterPolicy | None = None) -> tuple[RouteDecision, ...]:
    """Route pages in page order, consuming adapter invocation budgets."""
    base = policy or AdapterPolicy()
    remaining = dict(base.budgets)
    decisions = []
    for page in sorted(features, key=lambda item: item.page):
        decision = route_page(page, AdapterPolicy(base.allowed_modalities, remaining, base.external_calls))
        decisions.append(decision)
        for adapter in decision.adapters:
            if adapter in remaining:
                remaining[adapter] -= 1
    return tuple(decisions)


TriageFeatures = PageFeatures
RoutingPolicy = AdapterPolicy
__all__ = ["PageFeatures", "TriageFeatures", "AdapterPolicy", "RoutingPolicy", "RouteDecision", "classify_page", "route_page", "route_pages", "triage_page"]
