import pytest
from scientific_extraction_harness import AssetEntry, AssetManifest, AssetRef, DocumentBundle, canonical_json, sha256_bytes

def test_content_addressed_assets_and_canonical_json():
    data = b"pixels"
    ref = AssetRef.from_bytes(data)
    assert ref.asset_id == "asset:sha256:" + sha256_bytes(data)
    entry = AssetEntry.from_bytes(data, kind="page", mime="image/png", page=1)
    assert entry.sha256 == ref.sha256
    manifest = AssetManifest("sha256:" + "a" * 64, (entry,))
    assert manifest.canonical_json() == canonical_json(manifest)

def test_crop_hash_includes_parent_and_bbox():
    a = AssetEntry.from_bytes(b"x", kind="crop", mime="image/png", parent_asset_id="asset:sha256:"+"a"*64, bbox_px=(1,2,3,4))
    b = AssetEntry.from_bytes(b"x", kind="crop", mime="image/png", parent_asset_id="asset:sha256:"+"a"*64, bbox_px=(1,2,3,5))
    assert a.sha256 != b.sha256

def test_tampered_hash_and_sensitive_input_rejected():
    with pytest.raises(ValueError): AssetRef("asset:sha256:"+"0"*64, "1"*64)
    with pytest.raises(ValueError): AssetManifest("sha256:"+"a"*64, (AssetEntry("asset:sha256:"+"a"*64,"page","a"*64,"x",metadata={"token":"bad"}),))

def test_bundle_is_immutable_and_validates_source():
    with pytest.raises(ValueError): DocumentBundle("sha256:"+"b"*64, "a"*64, 1, {}, {})
    bundle = DocumentBundle("sha256:"+"a"*64, "a"*64, 0, {}, {})
    with pytest.raises(TypeError): bundle.policy["x"] = 1
