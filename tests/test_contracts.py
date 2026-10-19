from pathlib import Path

import pytest

from scientific_extraction_harness import (
    Candidate,
    Correction,
    EvidenceRecord,
    ExtractorApprovalError,
    Run,
    append_contract,
    contract_to_json,
    load_contracts,
    make_candidate_evidence,
)


def evidence(status: str = "candidate") -> EvidenceRecord:
    return EvidenceRecord("doc", 1, "text", "paragraph:1", "mass", "2", "kg", 0.8, status)


def test_extractor_guard_rejects_approved() -> None:
    with pytest.raises(ExtractorApprovalError, match="may not create approved"):
        make_candidate_evidence(
            document_id="doc", page=1, modality="text", locator="paragraph:1",
            field="mass", value="2", unit="kg", confidence=0.8, status="approved",
        )


def test_candidate_and_correction_are_versioned() -> None:
    candidate = Candidate("c1", "r1", evidence())
    correction = Correction("x1", "r1", "c1", evidence("approved"), "reviewed source")
    assert candidate.to_dict()["schema_version"] == "1"
    assert correction.to_dict()["record_type"] == "correction"


def test_ledger_is_deterministic_append_only_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "runs.jsonl"
    run = Run("r1", "extractor-v1", ("doc",), metadata={"z": 1, "a": 2})
    candidate = Candidate("c1", "r1", evidence())
    append_contract(path, run)
    first = path.read_text(encoding="utf-8")
    append_contract(path, candidate)
    assert path.read_text(encoding="utf-8").startswith(first)
    assert list(load_contracts(path)) == [run, candidate]
    assert contract_to_json(run) == contract_to_json(run)
    assert '"a":2,"z":1' in first
