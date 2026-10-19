"""Deterministic, constrained YAML export for reviewed datasets (stdlib only)."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from .expert_review import ExpertReviewRecord, ValidationEvent

_SCHEMA_VERSION = "reviewed-dataset.v1"
_SECRET = re.compile(r"(?i)(password|passwd|secret|api[_ -]?key|access[_ -]?token|private[_ -]?key|bearer)")
_PDF_BYTES = re.compile(r"%PDF-|JVBERi0")


class YAMLExportError(ValueError):
    """Raised when a dataset package cannot be safely exported."""


def _safe(value: Any, path: str = "") -> None:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise YAMLExportError("raw bytes are not allowed in dataset export")
    if isinstance(value, str):
        if _PDF_BYTES.search(value):
            raise YAMLExportError("source PDF bytes are not allowed in dataset export")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _SECRET.search(str(key)):
                raise YAMLExportError(f"secret-like field is not allowed: {key}")
            _safe(child, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        for child in value:
            _safe(child, path)
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise YAMLExportError(f"unsupported YAML value at {path or 'root'}")


def _quote(value: str) -> str:
    # JSON double quoting is valid YAML and deterministic, including control chars.
    import json
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise YAMLExportError("non-finite floats are not allowed")
        return repr(value)
    if isinstance(value, str):
        return _quote(value)
    raise YAMLExportError("unsupported scalar")


def _render(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, Mapping):
        if not value:
            return [prefix + "{}"]
        lines: list[str] = []
        for key in sorted(value, key=lambda k: str(k)):
            if not isinstance(key, str):
                raise YAMLExportError("mapping keys must be strings")
            rendered_key = _quote(key)
            child = value[key]
            if isinstance(child, Mapping) and child:
                lines.append(f"{prefix}{rendered_key}:")
                lines.extend(_render(child, indent + 2))
            elif isinstance(child, Sequence) and not isinstance(child, (str, bytes, bytearray, memoryview)) and child:
                lines.append(f"{prefix}{rendered_key}:")
                lines.extend(_render(child, indent + 2))
            else:
                lines.append(f"{prefix}{rendered_key}: {_scalar(child)}")
        return lines
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        if not value:
            return [prefix + "[]"]
        lines = []
        for child in value:
            if isinstance(child, (Mapping, Sequence)) and child:
                lines.append(prefix + "-")
                lines.extend(_render(child, indent + 2))
            else:
                lines.append(f"{prefix}- {_scalar(child)}")
        return lines
    return [prefix + _scalar(value)]


def export_reviewed_dataset(*, article_hash: str, extraction_candidates: Sequence[Mapping[str, Any]],
                            provenance: Mapping[str, Any], review: ExpertReviewRecord,
                            validation_event: ValidationEvent, schema_version: str = _SCHEMA_VERSION) -> str:
    """Return deterministic YAML, requiring a matching explicit validation event."""
    if not isinstance(review, ExpertReviewRecord) or not isinstance(validation_event, ValidationEvent):
        raise YAMLExportError("review and explicit validation_event are required")
    if review.validation_event_id != validation_event.validation_event_id:
        raise YAMLExportError("review is not bound to the supplied validation event")
    if review.extraction_artifact_hash != validation_event.extraction_artifact_hash:
        raise YAMLExportError("validation event does not match reviewed artifact")
    if not isinstance(article_hash, str) or not article_hash.strip():
        raise YAMLExportError("article_hash is required")
    package = {
        "article_hash": article_hash,
        "extraction_candidates": list(extraction_candidates),
        "expert_review": {"comment": review.comment, "reviewer_pseudonym": review.reviewer_pseudonym, "score": review.score},
        "provenance": dict(provenance),
        "schema_version": schema_version,
        "validation_event": validation_event.to_dict(),
    }
    _safe(package)
    return "\n".join(_render(package)) + "\n"


# Short alias for consumers that prefer a noun-like API.
export_dataset = export_reviewed_dataset
