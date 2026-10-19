import pytest
from scientific_extraction_harness import Locator
D = "sha256:" + "a" * 64

def test_structured_locator_renders_compatibility_string():
    loc = Locator(D, 3, "table", table={"id":"2", "row":4, "column":"yield", "cell":"C5"})
    assert loc.render() == "page:3/table:2/row:4/column:yield/cell:C5"

def test_text_locator_and_bounds():
    loc = Locator(D, 1, "text", char_start=2, char_end=8, bbox_norm=(0,0,1,1))
    assert loc.locator == "page:1/chars:2-8"
    with pytest.raises(ValueError): Locator(D, 0, "text")
    with pytest.raises(ValueError): Locator(D, 1, "text", bbox_norm=(0,0,2,1))

def test_locator_rejects_url_and_unknown_modality():
    with pytest.raises(ValueError): Locator(D, 1, "text", table={"url":"https://bad"})
    with pytest.raises(ValueError): Locator(D, 1, "video")
