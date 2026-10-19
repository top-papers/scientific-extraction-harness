"""Local document loading with deterministic content fingerprints."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from .manifest import IngestionManifest, ManifestError


@dataclass(frozen=True)
class IngestedDocument:
    document_id: str
    path: Path
    content: bytes
    sha256: str

    @classmethod
    def from_manifest(cls, manifest: IngestionManifest, path: Path) -> "IngestedDocument":
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ManifestError(f"cannot read document: {path}") from exc
        digest = hashlib.sha256(content).hexdigest()
        if manifest.sha256 is not None and digest != manifest.sha256:
            raise ManifestError(
                f"sha256 mismatch for {manifest.document_id}: expected {manifest.sha256}, got {digest}"
            )
        return cls(manifest.document_id, path, content, digest)

    @classmethod
    def load(cls, manifest: IngestionManifest, input_root: Path) -> "IngestedDocument":
        root = Path(input_root).resolve()
        path = (root / manifest.path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ManifestError("document path is outside input_root") from exc
        if not path.is_file():
            raise ManifestError(f"document file does not exist: {manifest.path}")
        return cls.from_manifest(manifest, path)
