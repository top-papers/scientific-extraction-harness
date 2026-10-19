"""Versioned, local-only ingestion manifests."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping


_MANIFEST_VERSION = "1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_MODALITIES = {"text", "table", "figure", "scan"}
_REQUIRED_FIELDS = {"manifest_version", "document_id", "path", "permission"}
_OPTIONAL_FIELDS = {"sha256", "language", "expected_pages", "allowed_modalities"}
_FORBIDDEN_FIELD_PARTS = {
    "url", "uri", "token", "password", "passwd", "secret", "credential",
    "credentials", "api_key", "apikey", "access_key", "private_key",
    "username", "email",
}


class ManifestError(ValueError):
    """Raised when a manifest is invalid or points outside the input root."""


@dataclass(frozen=True)
class IngestionManifest:
    """The validated description of one permitted local document."""

    manifest_version: str
    document_id: str
    path: str
    permission: str
    sha256: str | None = None
    language: str | None = None
    expected_pages: int | None = None
    allowed_modalities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.manifest_version != _MANIFEST_VERSION:
            raise ManifestError(f"unsupported manifest_version: {self.manifest_version!r}")
        if not isinstance(self.document_id, str) or not self.document_id.strip():
            raise ManifestError("document_id is required")
        if not isinstance(self.path, str) or not self.path.strip():
            raise ManifestError("path is required")
        if not isinstance(self.permission, str) or not self.permission.strip():
            raise ManifestError("permission is required")
        _validate_relative_path(self.path)
        if self.sha256 is not None and (
            not isinstance(self.sha256, str) or not _SHA256_RE.fullmatch(self.sha256)
        ):
            raise ManifestError("sha256 must be 64 lowercase hexadecimal characters")
        if self.expected_pages is not None and (
            not isinstance(self.expected_pages, int) or isinstance(self.expected_pages, bool)
            or self.expected_pages < 1
        ):
            raise ManifestError("expected_pages must be a positive integer")
        if not isinstance(self.allowed_modalities, tuple) or not set(self.allowed_modalities) <= _ALLOWED_MODALITIES:
            raise ManifestError("allowed_modalities contains an unsupported modality")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "IngestionManifest":
        if not isinstance(value, Mapping):
            raise ManifestError("manifest must be a JSON object")
        _reject_sensitive_fields(value)
        keys = set(value)
        missing = _REQUIRED_FIELDS - keys
        unknown = keys - _REQUIRED_FIELDS - _OPTIONAL_FIELDS
        if missing:
            raise ManifestError(f"missing manifest fields: {', '.join(sorted(missing))}")
        if unknown:
            raise ManifestError(f"unknown manifest fields: {', '.join(sorted(unknown))}")
        modalities = value.get("allowed_modalities", ())
        if isinstance(modalities, list):
            modalities = tuple(modalities)
        elif modalities != ():
            raise ManifestError("allowed_modalities must be a list")
        return cls(
            manifest_version=value["manifest_version"], document_id=value["document_id"],
            path=value["path"], permission=value["permission"], sha256=value.get("sha256"),
            language=value.get("language"), expected_pages=value.get("expected_pages"),
            allowed_modalities=modalities,
        )


def _reject_sensitive_fields(value: Any, location: str = "manifest") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(part in normalized.split("_") for part in _FORBIDDEN_FIELD_PARTS):
                raise ManifestError(f"forbidden URL/credential field: {location}.{key}")
            _reject_sensitive_fields(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_fields(child, f"{location}[{index}]")


def _validate_relative_path(path: str) -> None:
    candidate = Path(path)
    if candidate.is_absolute() or candidate.drive or path.startswith(("/", "\\")):
        raise ManifestError("path must be relative")
    if any(part == ".." for part in candidate.parts):
        raise ManifestError("path traversal is not allowed")


class ManifestLoader:
    """Load manifests and resolve their document only within a local input root."""

    def __init__(self, input_root: Path, *, require_sha256: bool = False) -> None:
        self.input_root = Path(input_root).resolve()
        self.require_sha256 = require_sha256

    def load(self, manifest_path: Path) -> IngestionManifest:
        try:
            payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError(f"cannot read manifest: {exc}") from exc
        manifest = IngestionManifest.from_mapping(payload)
        if self.require_sha256 and manifest.sha256 is None:
            raise ManifestError("sha256 is required")
        self.resolve_path(manifest)
        return manifest

    def resolve_path(self, manifest: IngestionManifest) -> Path:
        root = self.input_root
        path = (root / manifest.path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ManifestError("document path is outside input_root") from exc
        if not path.exists():
            raise ManifestError(f"document file does not exist: {manifest.path}")
        if not path.is_file():
            raise ManifestError(f"document path is not a file: {manifest.path}")
        return path

    def load_document(self, manifest_path: Path):
        from .ingest import IngestedDocument
        manifest = self.load(manifest_path)
        return IngestedDocument.from_manifest(manifest, self.resolve_path(manifest))
