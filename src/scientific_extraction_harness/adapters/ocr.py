"""Dependency-free boundary for explicit OCR results.

This adapter does not perform OCR.  It accepts already-produced, structured OCR
regions and turns only unambiguous, sufficiently confident readings into scan
candidates.  The input is deliberately explicit so an OCR engine cannot hide
missing provenance or uncertainty behind this boundary.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..contracts import make_candidate_evidence
from ..evidence import EvidenceRecord
from .base import AdapterDiagnostic, AdapterResult


class OCRAdapter:
    """Convert explicit OCR region metadata into candidate evidence.

    Input may be a mapping, or UTF-8 JSON bytes on a document-like object.  It
    must contain ``regions`` and an explicit ``document_id`` (in the payload or
    config).  Every region must explicitly provide text, page, locator, field,
    and confidence.  The locator is checked against
    ``ocr:page:<page>/region:<id>``; this adapter never invents OCR text.
    """

    adapter_id = "ocr"
    adapter_version = "1"
    default_min_confidence = 0.8
    default_max_uncertainty = 0.2

    def extract(
        self,
        document: Any,
        *,
        config: Mapping[str, object] | None = None,
    ) -> AdapterResult:
        config = config or {}
        payload, error = self._payload(document)
        if error:
            return self._abstention(*error)

        document_id = config.get("document_id", payload.get("document_id"))
        if not self._explicit_text(document_id):
            return self._abstention("missing-document-id", "OCR document_id must be explicit")
        regions = payload.get("regions")
        if not isinstance(regions, list) or not regions:
            return self._abstention("missing-regions", "OCR input requires explicit regions")

        try:
            minimum = float(config.get("min_confidence", self.default_min_confidence))
        except (TypeError, ValueError):
            return self._abstention("invalid-threshold", "OCR min_confidence must be numeric")
        if not 0 <= minimum <= 1:
            return self._abstention("invalid-threshold", "OCR min_confidence must be between 0 and 1")

        records: list[EvidenceRecord] = []
        diagnostics: list[AdapterDiagnostic] = []
        fields: dict[str, str] = {}
        for index, region in enumerate(regions, 1):
            if not isinstance(region, Mapping):
                diagnostics.append(self._diag("invalid-region", index, "region must be an object"))
                continue
            self._validate_region(region, index, str(document_id), minimum, fields, records, diagnostics)

        if diagnostics:
            return AdapterResult(diagnostics=tuple(diagnostics), abstained=True)
        return AdapterResult(candidates=tuple(records))

    def _validate_region(
        self,
        region: Mapping[str, object],
        index: int,
        document_id: str,
        minimum: float,
        fields: dict[str, str],
        records: list[EvidenceRecord],
        diagnostics: list[AdapterDiagnostic],
    ) -> None:
        required = ("text", "page", "locator", "field", "confidence")
        missing = [name for name in required if name not in region or region[name] is None]
        if missing:
            diagnostics.append(self._diag("missing-metadata", index, "OCR region metadata is incomplete", missing=missing))
            return

        text = region["text"]
        field = region["field"]
        locator = region["locator"]
        if not isinstance(text, str) or not text.strip():
            diagnostics.append(self._diag("empty-text", index, "OCR text is missing or empty"))
            return
        if not isinstance(field, str) or not field.strip():
            diagnostics.append(self._diag("invalid-field", index, "OCR field must be non-empty"))
            return
        if not isinstance(locator, str) or not locator.strip():
            diagnostics.append(self._diag("invalid-locator", index, "OCR locator must be explicit"))
            return
        try:
            page = int(region["page"])
            confidence = float(region["confidence"])
        except (TypeError, ValueError):
            diagnostics.append(self._diag("invalid-metadata", index, "OCR page and confidence must be numeric"))
            return
        expected_prefix = f"ocr:page:{page}/region:"
        if page < 1 or not locator.startswith(expected_prefix) or not locator[len(expected_prefix):].strip():
            diagnostics.append(self._diag("invalid-locator", index, "OCR locator has an invalid format"))
            return
        if not 0 <= confidence <= 1:
            diagnostics.append(self._diag("invalid-confidence", index, "OCR confidence must be between 0 and 1"))
            return

        quality = region.get("quality")
        uncertainty = region.get("uncertainty")
        quality_value = self._number(quality)
        uncertainty_value = self._number(uncertainty)
        if quality is not None and (quality_value is None or not 0 <= quality_value <= 1):
            diagnostics.append(self._diag("invalid-quality", index, "OCR quality must be between 0 and 1"))
            return
        if uncertainty is not None and (uncertainty_value is None or not 0 <= uncertainty_value <= 1):
            diagnostics.append(self._diag("invalid-uncertainty", index, "OCR uncertainty must be between 0 and 1"))
            return
        if confidence < minimum or (quality_value is not None and quality_value < minimum) or (
            uncertainty_value is not None and uncertainty_value > self.default_max_uncertainty
        ):
            diagnostics.append(self._diag("low-quality", index, "OCR reading does not meet quality thresholds", confidence=confidence, quality=quality_value, uncertainty=uncertainty_value))
            return
        if region.get("ambiguous") is True or region.get("conflicting") is True or region.get("approved") is True or region.get("status") in ("approved", "rejected"):
            diagnostics.append(self._diag("unacceptable-reading", index, "OCR reading is ambiguous or outside candidate status", status=region.get("status")))
            return
        alternatives = region.get("alternatives")
        if isinstance(alternatives, (list, tuple, set)) and len(alternatives) > 0:
            diagnostics.append(self._diag("ambiguous-reading", index, "OCR region contains alternate readings", alternatives_count=len(alternatives)))
            return
        if field in fields:
            diagnostics.append(self._diag("conflicting-reading", index, "multiple OCR readings for one field", field=field))
            return
        fields[field] = text
        records.append(make_candidate_evidence(document_id=document_id, page=page, modality="scan", locator=locator, field=field, value=text.strip(), unit=self._unit(region.get("unit")), confidence=confidence, status="candidate"))

    @staticmethod
    def _payload(document: Any) -> tuple[Mapping[str, object], tuple[str, str] | None]:
        if isinstance(document, Mapping):
            return document, None
        content = getattr(document, "content", document if isinstance(document, bytes) else b"")
        if not isinstance(content, bytes):
            return {}, ("invalid-input", "OCR input must be a mapping or UTF-8 JSON bytes")
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}, ("invalid-input", "OCR input must be valid UTF-8 JSON")
        return (payload, None) if isinstance(payload, Mapping) else ({}, ("invalid-input", "OCR JSON must be an object"))

    @staticmethod
    def _explicit_text(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _number(value: object) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _unit(value: object) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _diag(code: str, region: int, message: str, **details: object) -> AdapterDiagnostic:
        details = {"region": region, **details}
        return AdapterDiagnostic("abstention", code, message, details)

    @classmethod
    def _abstention(cls, code: str, message: str) -> AdapterResult:
        return AdapterResult(diagnostics=(AdapterDiagnostic("abstention", code, message),), abstained=True)


__all__ = ["OCRAdapter"]
