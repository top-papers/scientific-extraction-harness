"""Dependency-free adapter for explicitly annotated figure regions.

This boundary deliberately does not inspect image or PDF bytes.  A figure result
is emitted only when a caller supplies an unambiguous figure number, region
identifier, and complete evidence metadata.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..contracts import make_candidate_evidence
from ..evidence import EvidenceRecord
from .base import AdapterDiagnostic, AdapterResult


class FigureAdapter:
    """Convert explicit figure/region metadata into candidate evidence.

    Supported mapping forms are either ``{"figures": [{"number": ...,
    "regions": [...]}, ...]}`` or a single figure mapping with ``number`` and
    ``regions``.  Each region must explicitly contain ``document_id``, ``page``,
    ``field``, ``value``, ``unit`` and ``confidence``.  ``unit`` may explicitly
    be ``None``.  No image, PDF, axis, or value inference is performed.
    """

    adapter_id = "figure"
    adapter_version = "1"

    def extract(
        self,
        document: Any,
        *,
        config: Mapping[str, object] | None = None,
    ) -> AdapterResult:
        del config  # Figure provenance must be present in the explicit mapping.
        payload = self._payload(document)
        if payload is None:
            return self._abstain(
                "unsupported-input",
                "figure adapter requires an explicit metadata/region mapping; bytes are not parsed",
            )

        figures = payload.get("figures")
        if figures is None and "number" in payload and "regions" in payload:
            figures = [payload]
        if not isinstance(figures, list) or not figures:
            return self._abstain("missing-figure-metadata", "figure mapping requires a non-empty figures list")

        records: list[EvidenceRecord] = []
        diagnostics: list[AdapterDiagnostic] = []
        locators: set[str] = set()
        for figure_index, figure in enumerate(figures, 1):
            if not isinstance(figure, Mapping):
                diagnostics.append(self._diag("invalid-figure", figure_index, "figure must be a mapping"))
                continue
            number = figure.get("number", figure.get("figure"))
            if not self._positive_integer(number):
                diagnostics.append(self._diag("invalid-figure-number", figure_index, "figure number must be a positive integer"))
                continue
            regions = figure.get("regions")
            if isinstance(regions, Mapping):
                regions = [dict(region, id=region_id) if isinstance(region, Mapping) else region
                           for region_id, region in regions.items()]
            if not isinstance(regions, list) or not regions:
                diagnostics.append(self._diag("missing-regions", figure_index, "figure requires a non-empty regions list or mapping"))
                continue
            for region_index, region in enumerate(regions, 1):
                if not isinstance(region, Mapping):
                    diagnostics.append(self._diag("invalid-region", figure_index, "region must be a mapping", region_index))
                    continue
                region_id = region.get("id", region.get("region"))
                if not isinstance(region_id, str) or not region_id.strip():
                    diagnostics.append(self._diag("missing-region-id", figure_index, "region id must be explicit", region_index))
                    continue
                locator = f"figure:{number}/region:{region_id.strip()}"
                if locator in locators:
                    diagnostics.append(self._diag("ambiguous-region", figure_index, "duplicate figure region locator", region_index))
                    continue
                locators.add(locator)
                missing = [name for name in ("document_id", "page", "field", "value", "confidence") if name not in region]
                if missing:
                    diagnostics.append(self._diag("missing-provenance", figure_index, "region metadata is incomplete", region_index, {"fields": tuple(missing)}))
                    continue
                if "unit" not in region:
                    diagnostics.append(self._diag("missing-provenance", figure_index, "unit must be explicit, including null", region_index, {"fields": ("unit",)}))
                    continue
                if not self._scalar_text(region["document_id"]) or not self._scalar_text(region["field"]):
                    diagnostics.append(self._diag("ambiguous-provenance", figure_index, "document_id and field must be non-empty scalar text", region_index))
                    continue
                if not self._scalar_text(region["value"]):
                    diagnostics.append(self._diag("ambiguous-value", figure_index, "figure value must be one explicit scalar", region_index))
                    continue
                try:
                    page = int(region["page"])
                    confidence = float(region["confidence"])
                except (TypeError, ValueError):
                    diagnostics.append(self._diag("invalid-provenance", figure_index, "page and confidence must be numeric", region_index))
                    continue
                if page < 1 or not 0 <= confidence <= 1:
                    diagnostics.append(self._diag("invalid-provenance", figure_index, "page or confidence is out of range", region_index))
                    continue
                unit = region["unit"]
                if unit is not None and not self._scalar_text(unit):
                    diagnostics.append(self._diag("ambiguous-unit", figure_index, "unit must be scalar text or null", region_index))
                    continue
                records.append(make_candidate_evidence(
                    document_id=str(region["document_id"]).strip(), page=page,
                    modality="figure", locator=locator, field=str(region["field"]).strip(),
                    value=str(region["value"]).strip(), unit=None if unit is None else str(unit).strip(),
                    confidence=confidence, status="candidate",
                ))

        if diagnostics:
            return AdapterResult(diagnostics=tuple(diagnostics), abstained=True)
        return AdapterResult(candidates=tuple(records))

    @staticmethod
    def _payload(document: Any) -> Mapping[str, object] | None:
        return document if isinstance(document, Mapping) else None

    @staticmethod
    def _positive_integer(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    @staticmethod
    def _scalar_text(value: object) -> bool:
        return isinstance(value, (str, int, float)) and not isinstance(value, bool) and bool(str(value).strip())

    @staticmethod
    def _diag(code: str, figure: int, message: str, region: int | None = None, extra: Mapping[str, object] | None = None) -> AdapterDiagnostic:
        details: dict[str, object] = {"figure_index": figure}
        if region is not None:
            details["region_index"] = region
        if extra:
            details.update(extra)
        return AdapterDiagnostic("abstention", code, message, details)

    @classmethod
    def _abstain(cls, code: str, message: str) -> AdapterResult:
        return AdapterResult(diagnostics=(AdapterDiagnostic("abstention", code, message),), abstained=True)


__all__ = ["FigureAdapter"]
