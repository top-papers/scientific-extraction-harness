"""Dependency-free deterministic adapter for synthetic table inputs."""

from __future__ import annotations

import json
from typing import Any, Mapping

from ..contracts import make_candidate_evidence
from ..evidence import EvidenceRecord
from .base import AdapterDiagnostic, AdapterResult


class TableAdapter:
    """Map a JSON-like table fixture to candidate evidence records.

    Input is a mapping with ``tables`` (or one table mapping), where each table
    has ``headers``, ``rows``, and optional ``units``. Rows may be mappings or
    sequences. Missing or ambiguous evidence causes an explicit atomic
    abstention: no partial candidates are returned.
    """

    adapter_id = "table"
    adapter_version = "1"

    def extract(
        self,
        document: Any,
        *,
        config: Mapping[str, object] | None = None,
    ) -> AdapterResult:
        config = config or {}
        document_id = str(config.get("document_id") or getattr(document, "document_id", ""))
        try:
            page = int(config.get("page", 1))
        except (TypeError, ValueError):
            return self._abstention("invalid-page", "table page must be an integer")

        payload, input_error = self._payload(document)
        if input_error:
            return self._abstention(input_error[0], input_error[1])
        tables = payload.get("tables")
        if tables is None:
            tables = [payload]
        if not isinstance(tables, list):
            return self._abstention("invalid-tables", "table input must contain a tables list")

        records: list[EvidenceRecord] = []
        diagnostics: list[AdapterDiagnostic] = []
        for table_index, table in enumerate(tables, 1):
            if not isinstance(table, Mapping):
                diagnostics.append(self._diagnostic("invalid-table", "table must be an object", table_index))
                continue
            headers = table.get("headers")
            rows = table.get("rows")
            units = table.get("units", {})
            if not isinstance(headers, list) or not isinstance(rows, list):
                diagnostics.append(self._diagnostic(
                    "missing-table-fields", "table requires headers and rows", table_index
                ))
                continue
            names = [str(header).strip() for header in headers]
            for row_index, row in enumerate(rows, 1):
                for column_index, field in enumerate(names):
                    if not field:
                        diagnostics.append(self._diagnostic(
                            "ambiguous-header", "header is empty", table_index, row_index
                        ))
                        continue
                    if names.count(field) > 1:
                        diagnostics.append(self._diagnostic(
                            "ambiguous-header", f"duplicate header: {field}", table_index, row_index, field
                        ))
                        continue
                    value, present = self._cell(row, field, column_index)
                    if not present or value is None or (isinstance(value, str) and not value.strip()):
                        diagnostics.append(self._diagnostic(
                            "missing-cell", "cell is missing or empty", table_index, row_index, field
                        ))
                        continue
                    if isinstance(value, (Mapping, list, tuple, set)):
                        diagnostics.append(self._diagnostic(
                            "ambiguous-cell", "cell contains multiple or structured values", table_index, row_index, field
                        ))
                        continue
                    records.append(make_candidate_evidence(
                        document_id=document_id,
                        page=page,
                        modality="table",
                        locator=f"table:{table_index}/row:{row_index}/column:{field}",
                        field=field,
                        value=str(value),
                        unit=self._unit(units, field, column_index),
                        confidence=1.0,
                        status="candidate",
                    ))

        if diagnostics:
            return AdapterResult(diagnostics=tuple(diagnostics), abstained=True)
        return AdapterResult(candidates=tuple(records))

    @staticmethod
    def _payload(document: Any) -> tuple[Mapping[str, object], tuple[str, str] | None]:
        if isinstance(document, Mapping):
            return document, None
        content = getattr(document, "content", b"")
        if not isinstance(content, bytes):
            return {}, ("invalid-input", "table adapter requires a mapping or UTF-8 JSON bytes")
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}, ("invalid-input", "table input must be valid UTF-8 JSON")
        if not isinstance(payload, Mapping):
            return {}, ("invalid-input", "table JSON must be an object")
        return payload, None

    @staticmethod
    def _cell(row: object, field: str, index: int) -> tuple[object, bool]:
        if isinstance(row, Mapping):
            return row.get(field), field in row
        if isinstance(row, (list, tuple)):
            return (row[index], True) if index < len(row) else (None, False)
        return None, False

    @staticmethod
    def _unit(units: object, field: str, index: int) -> str | None:
        if isinstance(units, Mapping):
            value = units.get(field)
        elif isinstance(units, list):
            value = units[index] if index < len(units) else None
        else:
            value = None
        return None if value is None or str(value).strip() == "" else str(value)

    @staticmethod
    def _diagnostic(
        code: str, message: str, table: int, row: int | None = None, column: str | None = None
    ) -> AdapterDiagnostic:
        details: dict[str, object] = {"table": table}
        if row is not None:
            details["row"] = row
        if column is not None:
            details["column"] = column
        return AdapterDiagnostic("abstention", code, message, details)

    @classmethod
    def _abstention(cls, code: str, message: str) -> AdapterResult:
        return AdapterResult(diagnostics=(cls._diagnostic(code, message, 0),), abstained=True)
