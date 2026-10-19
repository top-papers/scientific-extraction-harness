import json
from pathlib import Path

from scientific_extraction_harness.cli import main


def _manifest(root: Path, document: str = "doc.txt") -> Path:
    (root / document).write_text("mass: 12 g\n", encoding="utf-8")
    path = root / "manifest.json"
    path.write_text(json.dumps({
        "manifest_version": "1", "document_id": "doc-1", "path": document,
        "permission": "local-test",
    }), encoding="utf-8")
    return path


def test_help_and_extract_success(tmp_path, capsys):
    manifest = _manifest(tmp_path)
    output = tmp_path / "report.json"
    candidates = tmp_path / "candidates.json"
    assert main(["extract", str(manifest), str(tmp_path), "--adapter", "text",
                 "--rules", '[{"field":"mass","pattern":"mass: ([0-9]+)","unit":"g"}]',
                 "--output", str(output), "--candidates", str(candidates)]) == 0
    report = json.loads(output.read_text())
    assert report["ok"] is True
    assert len(json.loads(candidates.read_text())) == 1
    assert "mass: 12" not in json.dumps(report)


def test_extract_failure_is_nonzero_and_fail_closed(tmp_path):
    manifest = _manifest(tmp_path)
    output = tmp_path / "report.json"
    assert main(["extract", str(manifest), str(tmp_path), "--adapter", "text",
                 "--rules", '[{"field":"missing","pattern":"missing: ([0-9]+)"}]',
                 "--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert report["ok"] is False
    assert report["candidates"] == []


def test_review_requires_explicit_action_and_appends(tmp_path):
    path = tmp_path / "reviews.jsonl"
    assert main(["review", str(path), "--run-id", "run", "--candidate-id", "candidate",
                 "--action", "approve", "--reviewer-id", "reviewer", "--note", "checked"]) == 0
    event = json.loads(path.read_text().splitlines()[0])
    assert event["action"] == "approve"
    assert event["candidate_id"] == "candidate"


def test_evaluate_success_and_invalid_predictions(tmp_path):
    manifest = tmp_path / "cases.json"
    manifest.write_text(json.dumps({"manifest_version": "1", "cases": [
        {"case_id": "holdout-1", "split": "holdout"},
    ]}), encoding="utf-8")
    predictions = tmp_path / "predictions.json"
    predictions.write_text("{}", encoding="utf-8")
    output = tmp_path / "evaluation.json"
    assert main(["evaluate", str(manifest), str(predictions), "--output", str(output)]) == 0
    assert json.loads(output.read_text())["schema_version"] == "1"
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert main(["evaluate", str(manifest), str(bad)]) == 2
