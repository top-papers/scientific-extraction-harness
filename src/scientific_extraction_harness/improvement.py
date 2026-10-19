"""Versioned, content-addressed manifests for safe improvement candidates.

This module only records candidate metadata.  It deliberately does not execute
candidate code, call models or services, evaluate candidates, or merge changes.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


MANIFEST_VERSION = "1"
MUTATION_KINDS = frozenset(
    {"prompt", "config", "normalization", "retrieval", "threshold", "code"}
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CandidateManifestError(ValueError):
    """Raised when a candidate manifest is invalid or its hash is incorrect."""


class CandidateRegistryError(ValueError):
    """Raised when a candidate registry is invalid or cannot accept a record."""


def _canonical_json(value: Any) -> str:
    """Serialize JSON-compatible data in one stable, hashable representation."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CandidateManifestError("manifest fields must be JSON-compatible") from exc


def _validate_hash(value: str, field: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise CandidateManifestError(f"{field} must be 64 lowercase hexadecimal characters")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _freeze_json(child) for key, child in value.items()}
    if isinstance(value, list):
        return tuple(_freeze_json(child) for child in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise CandidateManifestError("budget must contain only JSON-compatible values")


@dataclass(frozen=True)
class CandidateManifest:
    """A reproducible description of one proposed improvement.

    ``candidate_id`` is SHA-256 over all manifest fields except the ID itself,
    using deterministic JSON serialization.  It is therefore derived rather
    than an independently trusted identifier.
    """

    parent_id: str | None
    mutation_kind: str
    hypothesis: str
    changed_files: tuple[str, ...]
    config_hash: str
    budget: Mapping[str, Any]
    manifest_version: str = MANIFEST_VERSION
    candidate_id: str = ""

    def __post_init__(self) -> None:
        if self.manifest_version != MANIFEST_VERSION:
            raise CandidateManifestError(
                f"unsupported manifest_version: {self.manifest_version!r}"
            )
        if self.parent_id is not None:
            _validate_hash(self.parent_id, "parent_id")
        if self.mutation_kind not in MUTATION_KINDS:
            raise CandidateManifestError(
                f"mutation_kind must be one of: {', '.join(sorted(MUTATION_KINDS))}"
            )
        if not isinstance(self.hypothesis, str) or not self.hypothesis.strip():
            raise CandidateManifestError("hypothesis is required")
        if not isinstance(self.changed_files, tuple):
            object.__setattr__(self, "changed_files", tuple(self.changed_files))
        if not self.changed_files or any(
            not isinstance(path, str) or not path.strip() for path in self.changed_files
        ):
            raise CandidateManifestError("changed_files must contain at least one path")
        if len(set(self.changed_files)) != len(self.changed_files):
            raise CandidateManifestError("changed_files must not contain duplicates")
        _validate_hash(self.config_hash, "config_hash")
        frozen_budget = _freeze_json(self.budget)
        if not isinstance(frozen_budget, dict):
            raise CandidateManifestError("budget must be a JSON object")
        object.__setattr__(self, "budget", frozen_budget)

        expected = self._content_hash()
        if self.candidate_id:
            _validate_hash(self.candidate_id, "candidate_id")
            if self.candidate_id != expected:
                raise CandidateManifestError("candidate_id does not match manifest content")
        else:
            object.__setattr__(self, "candidate_id", expected)

    def _content_mapping(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "parent_id": self.parent_id,
            "mutation_kind": self.mutation_kind,
            "hypothesis": self.hypothesis,
            "changed_files": list(self.changed_files),
            "config_hash": self.config_hash,
            "budget": self.budget,
        }

    def _content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self._content_mapping()).encode("utf-8")).hexdigest()

    def to_mapping(self) -> dict[str, Any]:
        result = self._content_mapping()
        result["candidate_id"] = self.candidate_id
        return result

    def to_json(self) -> str:
        return _canonical_json(self.to_mapping())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CandidateManifest":
        if not isinstance(value, Mapping):
            raise CandidateManifestError("candidate manifest must be a JSON object")
        required = {
            "manifest_version", "parent_id", "mutation_kind", "hypothesis",
            "changed_files", "config_hash", "budget", "candidate_id",
        }
        missing = required - set(value)
        unknown = set(value) - required
        if missing:
            raise CandidateManifestError(f"missing manifest fields: {', '.join(sorted(missing))}")
        if unknown:
            raise CandidateManifestError(f"unknown manifest fields: {', '.join(sorted(unknown))}")
        files = value["changed_files"]
        if not isinstance(files, list):
            raise CandidateManifestError("changed_files must be a list")
        return cls(
            manifest_version=value["manifest_version"], parent_id=value["parent_id"],
            mutation_kind=value["mutation_kind"], hypothesis=value["hypothesis"],
            changed_files=tuple(files), config_hash=value["config_hash"],
            budget=value["budget"], candidate_id=value["candidate_id"],
        )

    @classmethod
    def from_json(cls, text: str) -> "CandidateManifest":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CandidateManifestError("invalid candidate manifest JSON") from exc
        return cls.from_mapping(value)


class CandidateRegistry:
    """Append-only JSONL storage for validated candidate manifests."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def list(self) -> list[CandidateManifest]:
        if not self.path.exists():
            return []
        records: list[CandidateManifest] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise CandidateRegistryError(f"cannot read registry: {exc}") from exc
        seen: set[str] = set()
        for number, line in enumerate(lines, 1):
            if not line.strip():
                raise CandidateRegistryError(f"blank registry line at {number}")
            try:
                manifest = CandidateManifest.from_json(line)
            except CandidateManifestError as exc:
                raise CandidateRegistryError(f"invalid registry line {number}: {exc}") from exc
            if manifest.candidate_id in seen:
                raise CandidateRegistryError(f"duplicate candidate_id: {manifest.candidate_id}")
            seen.add(manifest.candidate_id)
            records.append(manifest)
        return records

    def get(self, candidate_id: str) -> CandidateManifest | None:
        _validate_hash(candidate_id, "candidate_id")
        for manifest in self.list():
            if manifest.candidate_id == candidate_id:
                return manifest
        return None

    def register(self, manifest: CandidateManifest) -> CandidateManifest:
        if not isinstance(manifest, CandidateManifest):
            raise CandidateRegistryError("register expects a CandidateManifest")
        existing = self.list()
        if any(item.candidate_id == manifest.candidate_id for item in existing):
            raise CandidateRegistryError(f"duplicate candidate_id: {manifest.candidate_id}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(manifest.to_json() + "\n")
        except OSError as exc:
            raise CandidateRegistryError(f"cannot append registry: {exc}") from exc
        return manifest


__all__ = [
    "MANIFEST_VERSION", "MUTATION_KINDS", "CandidateManifest",
    "CandidateManifestError", "CandidateRegistry", "CandidateRegistryError",
]
