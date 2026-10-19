from scientific_extraction_harness.adapters.figure import FigureAdapter


def test_extracts_only_explicit_figure_region_metadata() -> None:
    result = FigureAdapter().extract({
        "figures": [{"number": 2, "regions": [{
            "id": "panel-a",
            "document_id": "paper-1",
            "page": 4,
            "field": "yield",
            "value": "82",
            "unit": "%",
            "confidence": 0.8,
        }]}]
    })
    assert len(result.candidates) == 1
    record = result.candidates[0]
    assert record.locator == "figure:2/region:panel-a"
    assert record.modality == "figure"
    assert record.status == "candidate"
    assert not result.abstained


def test_abstains_for_bytes_and_missing_provenance_without_source_diagnostics() -> None:
    result = FigureAdapter().extract(b"image bytes")
    assert result.candidates == ()
    assert result.abstained
    assert result.diagnostics[0].code == "unsupported-input"
    assert all("image bytes" not in diagnostic.message for diagnostic in result.diagnostics)

    incomplete = FigureAdapter().extract({
        "number": 1,
        "regions": [{"id": "x", "document_id": "paper", "page": 1, "field": "x", "value": "3"}],
    })
    assert incomplete.abstained
    assert incomplete.candidates == ()
    assert incomplete.diagnostics[0].code == "missing-provenance"


def test_rejects_ambiguous_regions_and_never_approves() -> None:
    result = FigureAdapter().extract({
        "number": 1,
        "regions": [
            {"id": "x", "document_id": "paper", "page": 1, "field": "x", "value": "3", "unit": None, "confidence": 1.0},
            {"id": "x", "document_id": "paper", "page": 1, "field": "x", "value": "4", "unit": None, "confidence": 1.0},
        ],
    })
    assert result.abstained
    assert result.candidates == ()
    assert any(d.code == "ambiguous-region" for d in result.diagnostics)
