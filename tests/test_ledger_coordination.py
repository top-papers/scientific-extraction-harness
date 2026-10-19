from __future__ import annotations

import multiprocessing
import threading
from pathlib import Path

import pytest

from scientific_extraction_harness.contracts import Run
from scientific_extraction_harness.ledger import (
    LedgerCorruptionError,
    append_contract,
    load_contracts,
)


def _run(path: str, run_id: str) -> None:
    append_contract(Path(path), Run(run_id=run_id, extractor="test"))


def test_sequential_append_creates_parent_and_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "ledger.jsonl"
    contract = Run(run_id="one", extractor="test")
    append_contract(path, contract)
    append_contract(path, contract)
    assert path.read_text(encoding="utf-8") == (
        '{"extractor":"test","input_documents":[],"metadata":{},'
        '"record_type":"run","run_id":"one","schema_version":"1"}\n'
    ) * 2
    assert list(load_contracts(path)) == [contract, contract]


def test_truncated_or_malformed_entry_is_corruption(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text('{"record_type":"run"}', encoding="utf-8")
    with pytest.raises(LedgerCorruptionError):
        list(load_contracts(path))


def test_concurrent_process_appends_are_complete(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ctx = multiprocessing.get_context("spawn")
    processes = [ctx.Process(target=_run, args=(str(path), str(i))) for i in range(8)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    records = list(load_contracts(path))
    assert sorted(record.run_id for record in records) == [str(i) for i in range(8)]


def test_concurrent_thread_appends_are_complete(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    threads = [threading.Thread(target=_run, args=(str(path), str(i))) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(record.run_id for record in load_contracts(path)) == [str(i) for i in range(8)]
