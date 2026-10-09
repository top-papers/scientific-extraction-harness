from pathlib import Path

import pytest

from scientific_extraction_harness import EvidenceRecord, load_jsonl, write_jsonl


def test_round_trip_preserves_evidence(tmp_path: Path) -> None:
    record = EvidenceRecord(
        document_id="example-paper",
        page=3,
        modality="figure",
        locator="figure:2/series:control/x:10",
        field="temperature",
        value="273.15",
        unit="K",
        confidence=0.87,
    )
    output = tmp_path / "evidence.jsonl"

    write_jsonl([record], output)

    assert load_jsonl(output) == [record]


def test_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError, match="confidence"):
        EvidenceRecord(
            document_id="example-paper",
            page=1,
            modality="text",
            locator="paragraph:1",
            field="mass",
            value="1",
            unit="kg",
            confidence=1.1,
        )
