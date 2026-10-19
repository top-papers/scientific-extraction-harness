"""Provider-neutral, opt-in LLM adapter boundary.

This module intentionally contains no SDK or network code.  A caller supplies a
transport callable; the adapter only builds a deterministic request and turns a
strict JSON response into *candidate* evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import re
from typing import Any, Callable, Mapping

from ..contracts import make_candidate_evidence
from ..evidence import EvidenceRecord
from .base import AdapterDiagnostic, AdapterResult

Transport = Callable[[Mapping[str, object]], object]
_SECRET = re.compile(
    r"(?i)\b(api[_ -]?key|token|password|secret|credential)\b\s*(?:[:=]|is)\s*([^\s,;]+)"
)
_AUTHORIZATION = re.compile(r"(?i)\b(authorization)\s*:\s*(?:bearer\s+)?[^\s,;]+")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_SENSITIVE_KEYS = {"credential", "api_key", "apikey", "token", "password", "secret", "authorization"}


def _safe(value: object) -> str:
    """Return diagnostic-safe text while preserving non-sensitive prompt prose."""
    text = str(value)
    text = _AUTHORIZATION.sub(lambda m: m.group(1) + ": [REDACTED]", text)
    text = _SECRET.sub(lambda m: m.group(1) + "=[REDACTED]", text)
    return _EMAIL.sub("[REDACTED_EMAIL]", text)


def _redact(value: object) -> object:
    """Recursively redact values and sensitive-key fields before transport."""
    if isinstance(value, str):
        return _safe(value)
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            name = str(key)
            result[name] = "[REDACTED]" if name.lower().replace("-", "_") in _SENSITIVE_KEYS else _redact(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _document_id(document: object) -> str:
    return str(getattr(document, "document_id", ""))


@dataclass(frozen=True)
class LLMAdapter:
    """An explicit, fail-closed LLM extraction boundary.

    ``transport`` is deliberately injected and receives only the request
    envelope. Authentication is owned by the transport closure, so credentials
    never enter requests, diagnostics, or persisted adapter results.
    """

    transport: Transport | None = None
    adapter_id: str = "llm"
    adapter_version: str = "1"

    def extract(self, document: object, *, config: Mapping[str, object] | None = None) -> AdapterResult:
        config = dict(config or {})
        if config.get("external_calls") is not True:
            return self._abstain("external-calls-disabled", "external calls are disabled")
        if config.get("explicit_opt_in") is not True and config.get("opt_in") is not True:
            return self._abstain("explicit-opt-in-required", "explicit LLM opt-in is required")
        if self.transport is None or not callable(self.transport):
            return self._abstain("transport-missing", "no transport was configured")

        credential = self._credential(config)
        if not credential:
            return self._abstain("credentials-missing", "explicit credentials are required")
        model = config.get("model")
        prompt = config.get("prompt")
        if not isinstance(model, str) or not model.strip() or not isinstance(prompt, str) or not prompt:
            return self._abstain("configuration-missing", "model and prompt are required")
        run_metadata = config.get("run_metadata", {})
        if not isinstance(run_metadata, Mapping):
            return self._abstain("invalid-run-metadata", "run metadata must be an object")
        timeout = config.get("timeout_seconds", 30)
        budget = config.get("budget_tokens", 0)
        if not isinstance(timeout, (int, float)) or timeout <= 0 or not isinstance(budget, int) or budget < 0:
            return self._abstain("invalid-budget", "timeout and budget are invalid")

        # Transport receives only the redacted prompt. The hash deliberately
        # identifies the original prompt for reproducibility without storing it.
        redacted_prompt = _safe(prompt)
        envelope = {
            "schema": "llm-request-1",
            "model": model,
            "config": _redact(self._public_config(config)),
            "prompt": redacted_prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "prompt_hash_basis": "original",
            "run_metadata": _redact(run_metadata),
            "document": {"document_id": _document_id(document), "sha256": str(getattr(document, "sha256", ""))},
            "timeout_seconds": timeout,
            "budget_tokens": budget,
            "retry": False,
        }
        try:
            response = self.transport(envelope)
        except Exception as exc:
            return self._abstain("transport-error", "LLM transport failed", {"exception_type": type(exc).__name__})
        return self._parse(response, document)

    @staticmethod
    def _public_config(config: Mapping[str, object]) -> dict[str, object]:
        blocked = {"credential", "api_key", "token", "password", "secret", "authorization", "prompt"}
        return {str(k): v for k, v in sorted(config.items(), key=lambda x: str(x[0])) if str(k).lower() not in blocked and k != "run_metadata"}

    @staticmethod
    def _credential(config: Mapping[str, object]) -> str | None:
        value = config.get("credential")
        if isinstance(value, str) and value:
            return value
        env_name = config.get("credential_env")
        allow = config.get("credential_env_allowlist", ())
        if isinstance(env_name, str) and isinstance(allow, (list, tuple, set)) and env_name in allow:
            found = os.environ.get(env_name)
            return found if found else None
        return None

    def _parse(self, response: object, document: object) -> AdapterResult:
        try:
            payload = json.loads(response) if isinstance(response, str) else response
            rows = payload["candidates"] if isinstance(payload, Mapping) and set(payload) == {"candidates"} else payload
            if not isinstance(rows, list) or not rows:
                raise ValueError("response must contain a non-empty candidates list")
            records: list[EvidenceRecord] = []
            for row in rows:
                if not isinstance(row, Mapping) or row.get("status", "candidate") != "candidate":
                    raise ValueError("unsupported candidate shape")
                required = ("page", "modality", "locator", "field", "value", "confidence")
                if any(key not in row for key in required) or row["modality"] not in {"text", "table", "figure", "scan"}:
                    raise ValueError("incomplete provenance")
                records.append(make_candidate_evidence(document_id=_document_id(document), page=int(row["page"]), modality=row["modality"], locator=str(row["locator"]), field=str(row["field"]), value=str(row["value"]), unit=row.get("unit"), confidence=float(row["confidence"])))
            return AdapterResult(tuple(records))
        except (TypeError, ValueError, KeyError, json.JSONDecodeError, OverflowError):
            return self._abstain("malformed-response", "LLM response was malformed or unsupported")

    @staticmethod
    def _abstain(code: str, message: str, details: Mapping[str, object] | None = None) -> AdapterResult:
        return AdapterResult(diagnostics=(AdapterDiagnostic("abstention", code, _safe(message), details or {}),), abstained=True)


__all__ = ["LLMAdapter", "Transport"]
