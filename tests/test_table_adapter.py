import json

from scientific_extraction_harness.adapters.table import TableAdapter


def test_extracts_synthetic_json_table_with_source_values_and_units() -> None:
    result = TableAdapter().extract(
        {
            "tables": [{
                "headers": ["temperature", "yield"],
                "units": {"temperature": "°C", "yield": "%"},
                "rows": [["37.0", "82"]],
            }]
        },
        config={"document_id": "synthetic-paper", "page": 2},
    )

    assert [(record.field, record.value, record.unit) for record in result.candidates] == [
        ("temperature", "37.0", "°C"),
        ("yield", "82", "%"),
    ]
    assert result.candidates[0].locator == "table:1/row:1/column:temperature"
    assert all(record.status == "candidate" for record in result.candidates)
    assert result.diagnostics == ()
    assert not result.abstained


def test_extracts_json_bytes_from_ingested_like_document() -> None:
    class Document:
        document_id = "bytes-paper"
        content = json.dumps({
            "headers": ["mass"], "units": ["mg"], "rows": [["4.2"]]
        }).encode()

    result = TableAdapter().extract(Document(), config={"page": 1})
    assert result.candidates[0].document_id == "bytes-paper"
    assert result.candidates[0].value == "4.2"
    assert result.candidates[0].unit == "mg"


def test_abstains_for_missing_and_ambiguous_cells() -> None:
    result = TableAdapter().extract({
        "headers": ["value", "value", "missing"],
        "rows": [["1", "2"]],
    }, config={"document_id": "ambiguous-paper"})

    assert result.candidates == ()
    assert result.abstained
    assert [(diagnostic.code, diagnostic.details.get("column")) for diagnostic in result.diagnostics] == [
        ("ambiguous-header", "value"),
        ("ambiguous-header", "value"),
        ("missing-cell", "missing"),
    ]


def test_abstains_for_ambiguous_cell_value_and_never_approves() -> None:
    result = TableAdapter().extract({
        "headers": ["result"],
        "rows": [{"result": ["1", "2"]}],
    }, config={"document_id": "ambiguous-value"})

    assert result.candidates == ()
    assert result.abstained
    assert result.diagnostics[0].code == "ambiguous-cell"
    assert all(diagnostic.kind == "abstention" for diagnostic in result.diagnostics)
