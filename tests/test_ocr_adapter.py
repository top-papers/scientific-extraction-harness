from scientific_extraction_harness.adapters import OCRAdapter


def region(**overrides):
    value = {"text": "273.15", "page": 2, "locator": "ocr:page:2/region:r1", "field": "temperature", "confidence": 0.94, "quality": 0.91, "uncertainty": 0.04}
    value.update(overrides)
    return value


def test_emits_explicit_scan_candidate():
    result = OCRAdapter().extract({"document_id": "paper-1", "regions": [region()]})
    assert len(result.candidates) == 1
    record = result.candidates[0]
    assert (record.value, record.modality, record.locator, record.status) == ("273.15", "scan", "ocr:page:2/region:r1", "candidate")
    assert not result.abstained


def test_abstains_without_explicit_metadata_and_does_not_leak_text():
    result = OCRAdapter().extract({"document_id": "paper-1", "regions": [region(text="SECRET OCR TEXT", confidence=None)]})
    assert result.abstained and not result.candidates
    assert result.diagnostics[0].code == "missing-metadata"
    assert "SECRET OCR TEXT" not in repr(result.diagnostics)


def test_rejects_low_quality_ambiguous_conflicting_and_approved_readings():
    result = OCRAdapter().extract({"document_id": "paper-1", "regions": [
        region(field="a", confidence=0.4),
        region(field="b", alternatives=["273.1"]),
        region(field="c", approved=True),
        region(field="d", confidence=0.95),
        region(field="d", confidence=0.95, locator="ocr:page:2/region:r2"),
    ]})
    assert result.abstained and result.candidates == ()
    assert {item.code for item in result.diagnostics} == {"low-quality", "ambiguous-reading", "unacceptable-reading", "conflicting-reading"}


def test_rejects_invalid_locator_and_never_approves():
    result = OCRAdapter().extract({"document_id": "paper-1", "regions": [region(locator="page:2/region:r1")]})
    assert result.abstained
    assert result.diagnostics[0].code == "invalid-locator"
    assert all(item.status == "candidate" for item in result.candidates)
