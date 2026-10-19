"""Local-first privacy and external-call policy boundaries.

This module is intentionally dependency-free.  It validates inputs before they
reach an adapter, keeps external calls fail-closed, and produces metadata-only
receipts.  It does not alter adapter or LLM semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping


_REDACTED = "[REDACTED]"
_EMAIL = re.compile(r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:api[_-]?key|token|secret|password|passwd|credential|authorization)\b\s*[:=]\s*)([^\s,;]+)"
)
_SENSITIVE_KEYS = re.compile(
    r"(?i)(?:secret|token|password|passwd|credential|authorization|api[_-]?key|private[_-]?key|raw[_-]?source|source[_-]?text|prompt|transcript|ocr[_-]?text|email|contact)"
)


class PrivacyError(ValueError):
    """Base error for a rejected privacy-policy operation."""


class UnauthorizedInputError(PrivacyError):
    pass


class PathPolicyError(PrivacyError):
    pass


class ExternalCallDenied(PrivacyError):
    pass


class TermsReceiptError(PrivacyError):
    pass


@dataclass(frozen=True)
class PrivacyPolicy:
    """Explicit policy for one run; safe defaults prohibit network access."""

    allowed_roots: tuple[Path, ...] = ()
    max_input_bytes: int = 10 * 1024 * 1024
    allowed_extensions: frozenset[str] = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".txt", ".json"})
    external_calls: bool = False
    external_adapters: frozenset[str] = frozenset()
    require_redaction: bool = True

    def __post_init__(self) -> None:
        if self.max_input_bytes <= 0:
            raise ValueError("max_input_bytes must be positive")
        object.__setattr__(self, "allowed_roots", tuple(Path(p).resolve() for p in self.allowed_roots))
        object.__setattr__(self, "allowed_extensions", frozenset(e.lower() for e in self.allowed_extensions))
        object.__setattr__(self, "external_adapters", frozenset(self.external_adapters))


@dataclass(frozen=True)
class LicenseTermsReceipt:
    """Evidence that an optional adapter's code/model terms were reviewed."""

    adapter: str
    version: str
    license: str
    model_terms: str
    source: str = ""

    def __post_init__(self) -> None:
        if not all(isinstance(v, str) and v.strip() for v in (self.adapter, self.version, self.license, self.model_terms)):
            raise TermsReceiptError("adapter, version, license, and model_terms are required")

    def as_metadata(self) -> dict[str, str]:
        return {"adapter": self.adapter, "version": self.version, "license": self.license, "model_terms": self.model_terms, "source": self.source}


@dataclass(frozen=True)
class AuditReceipt:
    """Metadata-only record; never contains source, prompt, credentials, or payload."""

    action: str
    adapter: str
    allowed: bool
    external: bool
    redacted: bool
    input_sha256: str | None = None
    terms_receipt: Mapping[str, str] | None = None
    reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        result = {"action": self.action, "adapter": self.adapter, "allowed": self.allowed, "external": self.external, "redacted": self.redacted}
        if self.input_sha256:
            result["input_sha256"] = self.input_sha256
        if self.terms_receipt:
            result["terms_receipt"] = dict(self.terms_receipt)
        if self.reason:
            result["reason"] = self.reason
        result["metadata"] = redact_sensitive(dict(self.metadata))
        return result


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_local_input(path: str | Path, *, authorized: bool, policy: PrivacyPolicy | None = None) -> Path:
    """Validate an authorized, regular local file and return its resolved path."""
    if not authorized:
        raise UnauthorizedInputError("input is not authorized for processing")
    policy = policy or PrivacyPolicy()
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_file():
        raise PathPolicyError("input must be an existing regular file")
    if policy.allowed_roots and not any(_inside(candidate, root) for root in policy.allowed_roots):
        raise PathPolicyError("input is outside the configured allowed roots")
    if candidate.stat().st_size > policy.max_input_bytes:
        raise PathPolicyError("input exceeds the configured size limit")
    if policy.allowed_extensions and candidate.suffix.lower() not in policy.allowed_extensions:
        raise PathPolicyError("input type is not permitted")
    return candidate


def redact_sensitive(value: Any) -> Any:
    """Return a recursively redacted copy suitable for diagnostics or payloads."""
    if isinstance(value, Mapping):
        return {str(k): (_REDACTED if _SENSITIVE_KEYS.search(str(k)) else redact_sensitive(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        converted = [redact_sensitive(v) for v in value]
        return type(value)(converted) if not isinstance(value, set) else set(converted)
    if isinstance(value, str):
        value = _BEARER.sub(_REDACTED, value)
        value = _SECRET_ASSIGNMENT.sub(lambda m: m.group(1) + _REDACTED, value)
        return _EMAIL.sub(_REDACTED, value)
    return value


def redacted_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Alias emphasizing that a copy, not the caller's payload, is returned."""
    return redact_sensitive(payload)


def _terms(receipt: LicenseTermsReceipt | Mapping[str, Any] | None, adapter: str) -> dict[str, str]:
    if isinstance(receipt, LicenseTermsReceipt):
        result = receipt.as_metadata()
    elif isinstance(receipt, Mapping):
        result = {str(k): str(v) for k, v in receipt.items()}
    else:
        raise TermsReceiptError(f"license/model terms receipt required for adapter {adapter}")
    required = ("adapter", "version", "license", "model_terms")
    if any(not result.get(key, "").strip() or result.get(key, "").strip().lower() in {"unknown", "unspecified", "n/a"} for key in required):
        raise TermsReceiptError("license/model terms receipt is incomplete or unknown")
    return result


def gate_external_call(*, adapter: str, policy: PrivacyPolicy | None = None, cli_acknowledged: bool = False, terms_receipt: LicenseTermsReceipt | Mapping[str, Any] | None = None, payload: Mapping[str, Any] | None = None, input_sha256: str | None = None) -> tuple[dict[str, Any], AuditReceipt]:
    """Authorize an external adapter only with config and CLI dual opt-in."""
    policy = policy or PrivacyPolicy()
    if not policy.external_calls:
        raise ExternalCallDenied("external calls are disabled by policy")
    if not cli_acknowledged:
        raise ExternalCallDenied("external calls require explicit CLI acknowledgement")
    if policy.external_adapters and adapter not in policy.external_adapters:
        raise ExternalCallDenied(f"adapter is not in the external allowlist: {adapter}")
    receipt = _terms(terms_receipt, adapter)
    safe_payload = redact_sensitive(dict(payload or {}))
    audit = AuditReceipt("external-call", adapter, True, True, True, input_sha256, receipt)
    return safe_payload, audit


def make_audit_receipt(*, action: str, adapter: str, allowed: bool, external: bool = False, input_value: bytes | str | None = None, metadata: Mapping[str, Any] | None = None, reason: str | None = None) -> AuditReceipt:
    """Create a safe receipt containing only metadata and a pseudonymous hash."""
    digest = None
    if input_value is not None:
        raw = input_value.encode("utf-8") if isinstance(input_value, str) else input_value
        digest = sha256(raw).hexdigest()
    return AuditReceipt(action, adapter, allowed, external, True, digest, None, reason, redact_sensitive(dict(metadata or {})))


__all__ = ["PrivacyPolicy", "PrivacyError", "UnauthorizedInputError", "PathPolicyError", "ExternalCallDenied", "TermsReceiptError", "LicenseTermsReceipt", "AuditReceipt", "validate_local_input", "redact_sensitive", "redacted_payload", "gate_external_call", "make_audit_receipt"]
