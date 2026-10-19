import json

import pytest

from scientific_extraction_harness.cache import CacheCorruption, CacheMiss, StageCache, cache_key


def make_key(**overrides):
    values = {"source_hash": "source", "stage": "render", "adapter": "local", "version": "1", "config": {"seed": 0}, "asset_hashes": ["b", "a"]}
    values.update(overrides)
    return cache_key(**values)


def test_key_is_deterministic_and_includes_inputs():
    assert make_key() == make_key(asset_hashes=["a", "b"])
    assert make_key(stage="ocr") != make_key()
    assert make_key(config={"seed": 1}) != make_key()
    assert make_key(asset_hashes=["a", "c"]) != make_key()


def test_atomic_cache_round_trip_and_receipt(tmp_path):
    cache = StageCache(tmp_path / "cache")
    key = make_key()
    receipt = cache.put(key, b"result", metadata={"stage": "render"})
    assert cache.get(key) == b"result"
    assert cache.receipt(key) == receipt
    assert list((tmp_path / "cache").rglob(".*")) == []


def test_missing_and_tampered_entries_are_detected(tmp_path):
    cache = StageCache(tmp_path)
    key = make_key()
    with pytest.raises(CacheMiss): cache.get(key)
    cache.put(key, b"safe")
    data_path = next(tmp_path.rglob(f"{key}.bin"))
    data_path.write_bytes(b"tampered")
    with pytest.raises(CacheCorruption): cache.get(key)


def test_malformed_metadata_is_corruption_without_raw_payload_in_error(tmp_path):
    cache = StageCache(tmp_path)
    key = make_key()
    cache.put(key, b"sensitive payload")
    meta_path = next(tmp_path.rglob(f"{key}.json"))
    meta_path.write_text("not json", encoding="utf-8")
    with pytest.raises(CacheCorruption) as error: cache.get(key)
    assert "sensitive payload" not in str(error.value)
