from scientific_extraction_harness.render import (
    asset_id, canonical_json, crop_hash, crop_metadata, register_asset, register_page,
)


def test_page_registration_is_deterministic():
    first = register_page(b"page-bytes", 1, width=10, height=20)
    assert first == register_page(b"page-bytes", 1, width=10, height=20)
    assert first["asset_id"].startswith("page:")
    assert first["sha256"] == asset_id(b"page-bytes", kind="asset").split(":", 1)[1]


def test_crop_identity_includes_parent_coordinates_and_bytes():
    digest = crop_hash("page:parent", b"pixels", (1, 2, 3, 4))
    assert digest != crop_hash("page:other", b"pixels", (1, 2, 3, 4))
    assert digest != crop_hash("page:parent", b"pixels", (1, 2, 3, 5))
    assert digest != crop_hash("page:parent", b"other", (1, 2, 3, 4))
    metadata = crop_metadata("page:parent", b"pixels", (1, 2, 3, 4), page=1)
    assert metadata["asset_id"] == "crop:" + digest
    assert metadata["parent_asset_id"] == "page:parent"


def test_asset_registration_preserves_opaque_bytes_and_metadata():
    registered = register_asset(b"opaque", kind="render", mime="x/test", page=2)
    assert registered.as_dict()["byte_length"] == 6
    assert registered.as_dict()["page"] == 2
    assert canonical_json({"b": 1, "a": 2}).endswith(b"\n")
