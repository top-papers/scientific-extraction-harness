from pathlib import Path

from scientific_extraction_harness import EvidenceRecord
from scientific_extraction_harness.adapters.text import TextAdapter, TextFieldRule
from scientific_extraction_harness.ingest import IngestedDocument
from scientific_extraction_harness.pipeline import PipelineBudget, run_extract


def document(content=b"mass: 3 kg\n"):
    return IngestedDocument("paper-1", Path("paper.txt"), content, "hash")


def adapter():
    return TextAdapter([TextFieldRule("mass", r"mass:\s*(\d+)", unit="kg")])


def test_run_extract_is_deterministic_and_hashes_candidates():
    first = run_extract(document(), adapter(), run_id="run-1", seed=7)
    second = run_extract(document(), adapter(), run_id="run-1", seed=7)
    assert first.ok
    assert first.candidates[0].candidate_id == second.candidates[0].candidate_id
    assert first.candidates[0].evidence == second.candidates[0].evidence


def test_validation_failure_is_fail_closed():
    result = run_extract(document(b"mass: 3 kg\nmass: 4 kg\n"), adapter(), run_id="run-1")
    assert not result.ok
    assert result.candidates == ()
    assert any(issue.code == "ambiguous-evidence" for issue in result.issues)


def test_candidate_budget_and_input_budget_fail_closed():
    result = run_extract(document(), adapter(), run_id="run-1", budget=PipelineBudget(max_candidates=0))
    assert not result.ok and result.budget_exceeded and result.candidates == ()
    result = run_extract(document(), adapter(), run_id="run-1", budget=PipelineBudget(max_input_bytes=1))
    assert not result.ok and result.budget_exceeded and result.candidates == ()


def test_external_calls_are_denied_by_default():
    result = run_extract(document(), adapter(), run_id="run-1", config={"external_calls": True})
    assert not result.ok
    assert "external calls are disabled" in result.errors
