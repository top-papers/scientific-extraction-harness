"""Append-only JSONL storage for versioned extraction run contracts.

Writers coordinate through a sidecar lock file.  The ledger itself is never
rewritten, truncated, or repaired by this module.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .contracts import Candidate, Contract, Correction, Run, contract_to_json
from .evidence import EvidenceRecord


class LedgerLockError(RuntimeError):
    """Raised when the ledger lock cannot be acquired before its deadline."""


class LedgerCorruptionError(ValueError):
    """Raised when a ledger contains an invalid or incomplete entry."""


@contextmanager
def _ledger_lock(path: Path, timeout: float) -> Iterator[None]:
    """Hold an advisory, cross-process lock for *path* until the context exits."""
    if timeout < 0:
        raise ValueError("timeout must be non-negative")
    lock_path = Path(f"{path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # Create/open the sidecar in one operation.  A separate exists() check
        # followed by open("ab") is racy on Windows: concurrent creators can
        # receive PermissionError while the other append handle is open.
        # ``msvcrt.locking`` requires a byte to exist at the lock offset, so
        # whichever handle observes an empty file initializes that byte.  The
        # write is identical for all possible initializers and happens before
        # the advisory lock is acquired, just as lock-file creation did before.
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        handle = os.fdopen(fd, "r+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            handle.close()
            raise
    else:
        handle = lock_path.open("a+b")
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise LedgerLockError(f"timed out acquiring ledger lock: {lock_path}") from exc
                    time.sleep(min(0.01, max(0.001, deadline - time.monotonic())))
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise LedgerLockError(f"timed out acquiring ledger lock: {lock_path}") from exc
                    time.sleep(min(0.01, max(0.001, deadline - time.monotonic())))
        yield
    except LedgerLockError:
        raise
    except OSError as exc:
        raise LedgerLockError(f"unable to lock ledger: {lock_path}") from exc
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
        else:
            handle.close()


def append_contract(path: Path, contract: Contract, timeout: float = 5.0) -> None:
    """Append exactly one deterministic, newline-terminated contract atomically.

    The parent directory and a sidecar ``.lock`` file are created as needed.
    A lock timeout fails closed and leaves the ledger untouched.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _ledger_lock(path, timeout):
        with path.open("a", encoding="utf-8", newline="\n") as output:
            output.write(contract_to_json(contract))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())


def load_contracts(path: Path) -> Iterator[Contract]:
    """Read and validate ledger entries in append order."""
    with Path(path).open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            if not line.endswith("\n"):
                raise LedgerCorruptionError(
                    f"incomplete ledger entry at line {line_number} (missing newline)"
                )
            try:
                payload = json.loads(line)
                record_type = payload.pop("record_type")
                if record_type == "run":
                    yield Run(**payload)
                elif record_type == "candidate":
                    yield Candidate(evidence=EvidenceRecord(**payload.pop("evidence")), **payload)
                elif record_type == "correction":
                    yield Correction(evidence=EvidenceRecord(**payload.pop("evidence")), **payload)
                else:
                    raise ValueError(f"unknown record_type: {record_type}")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise LedgerCorruptionError(f"invalid ledger entry at line {line_number}") from exc
