import pytest

from scientific_extraction_harness.adapters.text import TextAdapter, TextFieldRule


def test_extracts_unique_candidate_with_page_paragraph_and_chars_locator() -> None:
    adapter = TextAdapter([TextFieldRule("temperature", r"Temperature\s*=\s*(\d+\.\d+)", "K")])

    result = adapter.extract("synthetic-1", b"Intro\nTemperature = 273.15\n\fOther page")

    assert len(result.records) == 1
    record = result.records[0]
    assert record.value == "273.15"
    assert record.page == 1
    assert record.modality == "text"
    assert record.locator == "page:1/paragraph:2/chars:20-26"
    assert record.status == "candidate"
    assert result.diagnostics == ()


def test_abstains_when_rule_is_missing_or_ambiguous() -> None:
    adapter = TextAdapter([
        TextFieldRule("mass", r"Mass:\s*(\d+)\s*g"),
        TextFieldRule("temperature", r"Temperature:\s*(\d+)\s*K"),
    ])

    result = adapter.extract(
        "synthetic-2",
        b"Mass: 2 g\nMass: 3 g\nTemperature: 20 K",
    )

    assert len(result.records) == 0
    assert result.abstained
    assert [(item.code, item.details["field"], item.details["matches"]) for item in result.diagnostics] == [
        ("ambiguous-match", "mass", 2),
    ]


def test_rejects_rules_without_value_capture_and_invalid_utf8_abstains() -> None:
    with pytest.raises(ValueError, match="capture group"):
        TextFieldRule("mass", r"Mass: \d+")

    result = TextAdapter([TextFieldRule("mass", r"Mass:\s*(\d+)")]).extract("doc", b"\xff")
    assert result.records == ()
    assert result.diagnostics[0].code == "invalid-utf8"
