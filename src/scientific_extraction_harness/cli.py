"""Local command line interface for extraction, review, and evaluation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from .adapters.table import TableAdapter
from .adapters.text import TextAdapter, TextFieldRule
from .evaluate import CaseManifest, evaluate
from .evidence import EvidenceRecord
from .manifest import ManifestLoader
from .pipeline import run_extract
from .review import ReviewStore, ReviewEvent


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_json(value: object, path: str | None) -> None:
    text = _json_dump(value) + "\n"
    if path:
        Path(path).write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text, end="")


def _read_json(value: str) -> Any:
    path = Path(value)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(value)


def _text_adapter_rules(args: argparse.Namespace, config: Mapping[str, Any]) -> list[TextFieldRule]:
    raw = args.rules
    if raw is None:
        raw = config.get("rules", config.get("text_rules", []))
    elif isinstance(raw, str):
        raw = _read_json(raw)
    if not isinstance(raw, list):
        raise ValueError("text adapter requires --rules as a JSON list or a rules file")
    rules = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("each text rule must be an object")
        rules.append(TextFieldRule(
            field=str(item.get("field", "")), pattern=str(item.get("pattern", "")),
            unit=item.get("unit"), confidence=float(item.get("confidence", 0.9)),
            flags=int(item.get("flags", 0)),
        ))
    return rules


def _extract(args: argparse.Namespace) -> int:
    config: dict[str, Any] = {"external_calls": False}
    if args.config:
        loaded = _read_json(args.config)
        if not isinstance(loaded, Mapping):
            raise ValueError("--config must contain a JSON object")
        config.update(loaded)
    config["external_calls"] = False
    loader = ManifestLoader(Path(args.input_root))
    manifest = loader.load(args.manifest)
    document = loader.load_document(args.manifest)
    if args.adapter == "text":
        adapter = TextAdapter(_text_adapter_rules(args, config))
    else:
        adapter = TableAdapter()
    result = run_extract(document, adapter, run_id=args.run_id or manifest.document_id,
                         seed=args.seed, config=config, normalize=False)
    report = result.to_dict()
    report["document_id"] = manifest.document_id
    report["adapter"] = args.adapter
    if args.candidates:
        _write_json([candidate.to_dict() for candidate in result.candidates], args.candidates)
    _write_json(report, args.output)
    return 0 if result.ok else 1


def _review(args: argparse.Namespace) -> int:
    replacement = None
    if args.replacement is not None:
        payload = _read_json(args.replacement)
        if not isinstance(payload, Mapping):
            raise ValueError("replacement must be a JSON object")
        replacement = EvidenceRecord(**dict(payload))
    event = ReviewEvent.create(args.run_id, args.candidate_id, args.action, args.reviewer_id,
                               note=args.note, replacement=replacement)
    ReviewStore(Path(args.review_jsonl)).append(event)
    _write_json(event.to_dict(), args.output)
    return 0


def _load_predictions(path: str) -> dict[str, list[EvidenceRecord]]:
    source = Path(path)
    if source.suffix.lower() != ".jsonl":
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("predictions must be a JSON object mapping case IDs to records")
        raw_map = payload
    else:
        raw_map: dict[str, list[Any]] = {}
        for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, Mapping) or not isinstance(item.get("case_id"), str):
                raise ValueError(f"prediction line {line_number} requires case_id")
            record = item.get("record", item.get("prediction", item.get("evidence")))
            if record is None and "document_id" in item:
                record = item
            if isinstance(record, list):
                raw_map.setdefault(item["case_id"], []).extend(record)
            elif isinstance(record, Mapping):
                raw_map.setdefault(item["case_id"], []).append(record)
            else:
                raise ValueError(f"prediction line {line_number} requires a record")
    result: dict[str, list[EvidenceRecord]] = {}
    for case_id, records in raw_map.items():
        if not isinstance(case_id, str) or not isinstance(records, list):
            raise ValueError("prediction mapping values must be lists of records")
        result[case_id] = [EvidenceRecord(**dict(record)) for record in records]
    return result


def _evaluate(args: argparse.Namespace) -> int:
    manifest = CaseManifest.load(Path(args.manifest))
    predictions = _load_predictions(args.predictions)
    report = evaluate(manifest, predictions)
    payload = {"schema_version": report.schema_version,
               "splits": {name: vars(metrics) for name, metrics in sorted(report.splits.items())}}
    _write_json(payload, args.output)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scientific-extraction-harness")
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract", help="extract candidates from a local document")
    extract.add_argument("manifest", type=Path)
    extract.add_argument("input_root", type=Path)
    extract.add_argument("--adapter", choices=("text", "table"), required=True)
    extract.add_argument("--rules", help="JSON list or path to text adapter rules")
    extract.add_argument("--config", help="optional JSON pipeline configuration")
    extract.add_argument("--run-id")
    extract.add_argument("--seed", type=int, default=0)
    extract.add_argument("--output")
    extract.add_argument("--candidates")
    extract.set_defaults(handler=_extract)

    review = sub.add_parser("review", help="append one explicit human review event")
    review.add_argument("review_jsonl", type=Path)
    review.add_argument("--run-id", required=True)
    review.add_argument("--candidate-id", required=True)
    review.add_argument("--action", choices=("approve", "reject", "correct"), required=True)
    review.add_argument("--reviewer-id", required=True)
    review.add_argument("--note")
    review.add_argument("--replacement", help="JSON object or path for correct")
    review.add_argument("--output")
    review.set_defaults(handler=_review)

    evaluation = sub.add_parser("evaluate", help="evaluate predictions against a case manifest")
    evaluation.add_argument("manifest", type=Path)
    evaluation.add_argument("predictions", type=Path)
    evaluation.add_argument("--output")
    evaluation.set_defaults(handler=_evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        return int(args.handler(args))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(_json_dump({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
