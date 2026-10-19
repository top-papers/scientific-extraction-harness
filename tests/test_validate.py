from scientific_extraction_harness import EvidenceRecord, Validator
from scientific_extraction_harness.adapters.base import AdapterDiagnostic, AdapterResult


def record(**overrides):
    values = dict(
        document_id="paper-1", page=2, modality="text", locator="page:2/paragraph:1",
        field="mass", value="3", unit="kg", confidence=0.8,
    )
    values.update(overrides)
    return EvidenceRecord(**values)


def test_valid_record_passes_and_preserves_record():
    evidence = record()
    result = Validator().validate(evidence)
    assert result.valid and result.ok
    assert result.issues == ()
    assert result.records == (evidence,)


def test_provenance_fields_fail_closed():
    evidence = record()
    for name, value in (("document_id", ""), ("locator", ""), ("field", ""), ("value", "")):
        object.__setattr__(evidence, name, value)
    result = Validator().validate(evidence)
    assert not result.valid
    assert {issue.code for issue in result.issues} == {
        "missing-document_id", "missing-locator", "missing-field", "missing-value"
    }


def test_modality_status_and_confidence_are_structured():
    evidence = object.__new__(EvidenceRecord)
    object.__setattr__(evidence, "document_id", "paper")
    object.__setattr__(evidence, "page", 0)
    object.__setattr__(evidence, "modality", "audio")
    object.__setattr__(evidence, "locator", "loc")
    object.__setattr__(evidence, "field", "x")
    object.__setattr__(evidence, "value", "1")
    object.__setattr__(evidence, "unit", None)
    object.__setattr__(evidence, "confidence", 2)
    object.__setattr__(evidence, "status", "approved")
    object.__setattr__(evidence, "reviewer_note", None)
    result = Validator().validate(evidence)
    assert {issue.code for issue in result.issues} == {
        "invalid-page", "unsupported-modality", "invalid-confidence", "status-boundary"
    }
    assert all(issue.path for issue in result.issues)


def test_adapter_missing_and_ambiguous_diagnostics_fail_closed():
    result = AdapterResult(
        diagnostics=(
            AdapterDiagnostic("abstention", "no-match", "mass was not found"),
            AdapterDiagnostic("abstention", "ambiguous-match", "two masses found"),
        ),
        abstained=True,
    )
    validation = Validator().validate(result)
    assert not validation.valid
    assert [issue.code for issue in validation.issues] == ["missing-evidence", "ambiguous-evidence"]


def test_adapter_error_and_invalid_candidates_are_structured():
    result = AdapterResult(
        candidates=(record(),),
        diagnostics=(AdapterDiagnostic("error", "adapter-error", "failed"),),
    )
    validation = Validator().validate(result)
    assert not validation.valid
    assert validation.issues[0].code == "adapter-error"
    assert validation.records == ()
