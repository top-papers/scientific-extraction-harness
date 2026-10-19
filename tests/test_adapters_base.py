from pathlib import Path
from typing import Mapping

import pytest

from scientific_extraction_harness.adapters.base import (
    AdapterDiagnostic,
    AdapterResult,
    ExtractionAdapter,
    abstain,
    candidate,
    run_adapter,
)
from scientific_extraction_harness.evidence import EvidenceRecord
from scientific_extraction_harness.ingest import IngestedDocument


def _document() -> IngestedDocument:
    return IngestedDocument("doc-1", Path("paper.pdf"), b"data", "hash")


def _record(status: str = "candidate") -> EvidenceRecord:
    return EvidenceRecord(
        document_id="doc-1",
        page=1,
        modality="text",
        locator="paragraph:1",
        field="mass",
        value="1",
        unit="kg",
        confidence=0.8,
        status=status,
    )


def test_protocol_accepts_adapter_with_structured_result() -> None:
    class FixtureAdapter:
        adapter_id = "fixture"
        adapter_version = "1"

        def extract(self, document: IngestedDocument, *, config: Mapping[str, object]) -> AdapterResult:
            return AdapterResult(candidates=(candidate(_record()),))

    adapter: ExtractionAdapter = FixtureAdapter()
    result = run_adapter(adapter, _document())

    assert result.records == (_record(),)
    assert not result.errors


def test_abstention_is_structured_and_not_silent() -> None:
    result = abstain("no-evidence", "No supported page region was found")

    assert result.abstained
    assert result.candidates == ()
    assert result.diagnostics == (
        AdapterDiagnostic("abstention", "no-evidence", "No supported page region was found"),
    )


def test_abstained_result_requires_abstention_diagnostic() -> None:
    with pytest.raises(ValueError, match="abstention diagnostic"):
        AdapterResult(abstained=True)


def test_approved_candidate_is_rejected_at_boundary() -> None:
    with pytest.raises(ValueError, match="approved"):
        candidate(_record("approved"))

    with pytest.raises(ValueError, match="approved"):
        AdapterResult(candidates=(_record("approved"),))


def test_run_adapter_reports_approval_attempt_as_error() -> None:
    class BadAdapter:
        adapter_id = "bad"
        adapter_version = "1"

        def extract(self, document: IngestedDocument, *, config: Mapping[str, object]) -> AdapterResult:
            return AdapterResult(candidates=(_record("approved"),))

    result = run_adapter(BadAdapter(), _document())

    assert result.candidates == ()
    assert len(result.errors) == 1
    assert result.errors[0].code == "boundary-approved"


def test_run_adapter_reports_unexpected_adapter_errors() -> None:
    class BrokenAdapter:
        adapter_id = "broken"
        adapter_version = "1"

        def extract(self, document: IngestedDocument, *, config: Mapping[str, object]) -> AdapterResult:
            raise RuntimeError("fixture broke")

    result = run_adapter(BrokenAdapter(), _document())

    assert result.errors[0].code == "adapter-error"
    assert result.errors[0].details == {"exception_type": "RuntimeError"}
