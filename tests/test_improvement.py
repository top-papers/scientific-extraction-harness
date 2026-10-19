import hashlib
import json

import pytest

from scientific_extraction_harness import (
    CandidateManifest,
    CandidateManifestError,
    CandidateRegistry,
    CandidateRegistryError,
)


def make_manifest(**overrides):
    values = {
        "parent_id": None,
        "mutation_kind": "config",
        "hypothesis": "A tighter threshold reduces false positives.",
        "changed_files": ("configs/default.toml",),
        "config_hash": "a" * 64,
        "budget": {"max_candidates": 100, "seed": 0},
    }
    values.update(overrides)
    return CandidateManifest(**values)


def test_candidate_id_is_content_addressed_and_round_trips():
    manifest = make_manifest()
    assert len(manifest.candidate_id) == 64
    assert CandidateManifest.from_json(manifest.to_json()) == manifest
    assert manifest.to_json() == CandidateManifest.from_mapping(manifest.to_mapping()).to_json()


def test_invalid_mutation_kind_and_hash_are_rejected():
    with pytest.raises(CandidateManifestError):
        make_manifest(mutation_kind="execute")
    with pytest.raises(CandidateManifestError):
        make_manifest(config_hash="not-a-hash")
    manifest = make_manifest()
    payload = manifest.to_mapping()
    payload["candidate_id"] = "b" * 64
    with pytest.raises(CandidateManifestError, match="does not match"):
        CandidateManifest.from_mapping(payload)


def test_registry_is_append_only_and_rejects_duplicates(tmp_path):
    registry = CandidateRegistry(tmp_path / "candidates.jsonl")
    first = registry.register(make_manifest())
    second = registry.register(make_manifest(hypothesis="A different hypothesis."))
    assert registry.list() == [first, second]
    assert registry.get(first.candidate_id) == first
    with pytest.raises(CandidateRegistryError, match="duplicate"):
        registry.register(first)
    assert len((tmp_path / "candidates.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_registry_detects_tampered_hash_on_read(tmp_path):
    registry_path = tmp_path / "candidates.jsonl"
    manifest = make_manifest()
    payload = manifest.to_mapping()
    payload["hypothesis"] = "tampered"
    registry_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(CandidateRegistryError, match="candidate_id"):
        CandidateRegistry(registry_path).list()


def test_canonical_serialization_is_stable():
    first = make_manifest(budget={"seed": 0, "max_candidates": 100})
    second = make_manifest(budget={"max_candidates": 100, "seed": 0})
    assert first.candidate_id == second.candidate_id
    assert hashlib.sha256(first.to_json().encode()).hexdigest() != first.candidate_id
