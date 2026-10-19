"""Dependency-free deterministic extraction from synthetic text bytes.

This adapter intentionally does not parse PDFs. Input is de-identified UTF-8 text
with optional form-feed page separators and explicit regex field rules.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Pattern, Any, Mapping

from ..contracts import make_candidate_evidence
from .base import AdapterDiagnostic, AdapterResult


@dataclass(frozen=True)
class TextFieldRule:
    """A named regex rule whose first capture group is the source value."""

    field: str
    pattern: str
    unit: str | None = None
    confidence: float = 0.9
    flags: int = 0

    def __post_init__(self) -> None:
        if not self.field.strip():
            raise ValueError("field is required")
        if not self.pattern:
            raise ValueError("pattern is required")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if re.compile(self.pattern, self.flags).groups < 1:
            raise ValueError("pattern must contain a capture group for value")


class TextAdapter:
    """Extract unique regex matches while preserving page/paragraph/char location."""

    adapter_id = "text"
    adapter_version = "1"

    def __init__(self, rules: list[TextFieldRule] | tuple[TextFieldRule, ...]):
        self._rules = tuple(rules)
        self._compiled: tuple[Pattern[str], ...] = tuple(
            re.compile(rule.pattern, rule.flags) for rule in self._rules
        )

    def extract(
        self,
        document: Any,
        content: bytes | None = None,
        *,
        config: Mapping[str, object] | None = None,
    ) -> AdapterResult:
        """Extract from an ``IngestedDocument`` or explicit ``(id, bytes)`` pair."""
        config = config or {}
        if content is not None:
            document_id = str(config.get("document_id") or document)
        else:
            document_id = str(config.get("document_id") or getattr(document, "document_id", ""))
        content = content if content is not None else (document if isinstance(document, bytes) else getattr(document, "content", b""))
        if not isinstance(content, bytes):
            return self._abstention("invalid-input", "text adapter requires bytes")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return self._abstention("invalid-utf8", "text bytes are not valid UTF-8")
        locations = self._paragraphs(text.split("\f"))
        records = []
        diagnostics = []
        for rule, pattern in zip(self._rules, self._compiled):
            matches = [
                (page, paragraph, start, match)
                for page, paragraph, start, _end, paragraph_text in locations
                for match in pattern.finditer(paragraph_text)
            ]
            if not matches:
                diagnostics.append(self._diagnostic("no-match", rule.field, "no unique match", 0))
                continue
            if len(matches) != 1:
                diagnostics.append(self._diagnostic("ambiguous-match", rule.field, "multiple matches", len(matches)))
                continue
            page, paragraph, start, match = matches[0]
            value = match.group(1).strip()
            if not value:
                diagnostics.append(self._diagnostic("empty-value", rule.field, "matched value is empty", 1))
                continue
            value_start = start + match.start(1)
            value_end = start + match.end(1)
            records.append(make_candidate_evidence(
                document_id=document_id,
                page=page,
                modality="text",
                locator=f"page:{page}/paragraph:{paragraph}/chars:{value_start}-{value_end}",
                field=rule.field,
                value=value,
                unit=rule.unit,
                confidence=rule.confidence,
            ))
        # A rule set is emitted atomically: a missing or ambiguous requested
        # field makes the complete extraction abstain rather than mixing partial
        # evidence with an unresolved request.
        return AdapterResult(tuple(records) if not diagnostics else (), tuple(diagnostics), abstained=bool(diagnostics))

    @staticmethod
    def _paragraphs(pages: list[str]):
        locations = []
        offset = 0
        for page_number, page_text in enumerate(pages, 1):
            paragraph_number = 0
            for match in re.finditer(r"[^\r\n]+", page_text):
                paragraph_number += 1
                locations.append((page_number, paragraph_number, offset + match.start(), offset + match.end(), match.group(0)))
            offset += len(page_text) + 1
        return locations

    @staticmethod
    def _diagnostic(code: str, field: str, message: str, matches: int) -> AdapterDiagnostic:
        return AdapterDiagnostic("abstention", code, f"{field}: {message}", {"field": field, "matches": matches})

    @staticmethod
    def _abstention(code: str, message: str) -> AdapterResult:
        return AdapterResult(diagnostics=(AdapterDiagnostic("abstention", code, message),), abstained=True)
