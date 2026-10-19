from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scientific_extraction_harness import IngestedDocument, ManifestError, ManifestLoader


def write_manifest(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_valid_manifest_loads_and_ingests(tmp_path: Path) -> None:
    root = tmp_path / "input"
    root.mkdir()
    document = root / "paper.txt"
    document.write_bytes(b"synthetic source")
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    manifest = write_manifest(tmp_path, {
        "manifest_version": "1", "document_id": "paper-1", "path": "paper.txt",
        "sha256": digest, "permission": "authorized-local",
    })

    loaded = ManifestLoader(root).load_document(manifest)

    assert isinstance(loaded, IngestedDocument)
    assert loaded.content == b"synthetic source"
    assert loaded.sha256 == digest


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path, {
        "manifest_version": "1", "document_id": "missing", "path": "missing.pdf",
        "permission": "authorized-local",
    })
    with pytest.raises(ManifestError, match="does not exist"):
        ManifestLoader(tmp_path).load(manifest)


def test_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "input"
    root.mkdir()
    (root / "paper.txt").write_bytes(b"actual")
    manifest = write_manifest(tmp_path, {
        "manifest_version": "1", "document_id": "paper", "path": "paper.txt",
        "sha256": "0" * 64, "permission": "authorized-local",
    })
    with pytest.raises(ManifestError, match="sha256 mismatch"):
        ManifestLoader(root).load_document(manifest)


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path, {
        "manifest_version": "1", "document_id": "escape", "path": "../secret.pdf",
        "permission": "authorized-local",
    })
    with pytest.raises(ManifestError, match="traversal|relative"):
        ManifestLoader(tmp_path).load(manifest)


def test_url_and_credential_fields_are_rejected(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path, {
        "manifest_version": "1", "document_id": "remote", "path": "paper.pdf",
        "permission": "authorized-local", "url": "https://example.invalid/paper.pdf",
    })
    with pytest.raises(ManifestError, match="forbidden"):
        ManifestLoader(tmp_path).load(manifest)
