"""Small stdlib-only content-addressed cache for local stage artifacts."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .render import canonical_json, sha256_bytes


class CacheError(Exception):
    """Base cache failure."""


class CacheMiss(CacheError):
    pass


class CacheCorruption(CacheError):
    pass


def cache_key(*, source_hash: str, stage: str, adapter: str, version: str, config: Any = None, config_hash: str | None = None, asset_hashes: list[str] | tuple[str, ...] = ()) -> str:
    """Create a stable key from all processing identity inputs."""
    if config_hash is None:
        config_hash = sha256_bytes(canonical_json(config if config is not None else {}))
    payload = {"source_hash": source_hash, "stage": stage, "adapter": adapter, "version": version, "config_hash": config_hash, "asset_hashes": sorted(asset_hashes)}
    return sha256_bytes(canonical_json(payload))


@dataclass(frozen=True)
class CacheReceipt:
    key: str
    payload_sha256: str
    byte_length: int


class StageCache:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _paths(self, key: str) -> tuple[Path, Path]:
        if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("key must be a SHA-256 hex digest")
        directory = self.root / key[:2]
        return directory / f"{key}.bin", directory / f"{key}.json"

    def put(self, key: str, payload: bytes, *, metadata: Mapping[str, Any] | None = None) -> CacheReceipt:
        if not isinstance(payload, bytes): raise TypeError("payload must be bytes")
        data_path, meta_path = self._paths(key)
        data_path.parent.mkdir(parents=True, exist_ok=True)
        digest = sha256_bytes(payload)
        meta = {"schema_version": 1, "key": key, "payload_sha256": digest, "byte_length": len(payload), "metadata": dict(metadata or {})}
        # Named temporary files in the target directory make os.replace atomic.
        fd, temporary = tempfile.mkstemp(prefix=f".{key}.", dir=data_path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, data_path)
            fd2, temporary_meta = tempfile.mkstemp(prefix=f".{key}.", dir=meta_path.parent)
            try:
                with os.fdopen(fd2, "wb") as handle:
                    handle.write(canonical_json(meta)); handle.flush(); os.fsync(handle.fileno())
                os.replace(temporary_meta, meta_path)
            finally:
                if os.path.exists(temporary_meta): os.unlink(temporary_meta)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        return CacheReceipt(key, digest, len(payload))

    def get(self, key: str) -> bytes:
        data_path, meta_path = self._paths(key)
        if not data_path.exists() or not meta_path.exists(): raise CacheMiss(key)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            payload = data_path.read_bytes()
        except (OSError, ValueError, UnicodeError) as exc:
            raise CacheCorruption("cache entry unreadable") from exc
        if meta.get("key") != key or meta.get("byte_length") != len(payload) or meta.get("payload_sha256") != sha256_bytes(payload):
            raise CacheCorruption("cache entry integrity check failed")
        return payload

    def receipt(self, key: str) -> CacheReceipt:
        self.get(key)
        _, meta_path = self._paths(key)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return CacheReceipt(key, meta["payload_sha256"], meta["byte_length"])
