import pytest

from scientific_extraction_harness import (
    CONFIDENCE_POLICY_VERSION,
    ConfidencePolicy,
    ConfidenceResult,
    compose_confidence,
)


def test_composition_is_deterministic_and_explainable() -> None:
    policy = ConfidencePolicy()
    first = policy.score(
        locator_quality=0.9, parser_agreement=0.8, source_quality=0.7
    )
    second = policy.score(
        locator_quality=0.9, parser_agreement=0.8, source_quality=0.7
    )

    assert first == second
    assert first.confidence == pytest.approx(0.815)
    assert first.policy_version == CONFIDENCE_POLICY_VERSION
    assert first.components == {
        "locator_quality": 0.9,
        "parser_agreement": 0.8,
        "source_quality": 0.7,
    }
    assert first.to_dict()["explanations"]


def test_weak_locator_reduces_confidence() -> None:
    strong = compose_confidence(
        locator_quality=0.9, parser_agreement=1, source_quality=1
    )
    weak = compose_confidence(
        locator_quality=0.2, parser_agreement=1, source_quality=1
    )

    assert weak.weak_locator is True
    assert weak.locator_penalty == 0.75
    assert weak.confidence < strong.confidence
    assert any("penalty" in explanation for explanation in weak.explanations)


def test_ocr_quality_is_optional_and_bounded() -> None:
    result = compose_confidence(
        locator_quality=1, parser_agreement=1, source_quality=1, ocr_quality=0
    )
    assert result.ocr_quality == 0
    assert 0 <= result.confidence <= 1
    assert result.confidence == pytest.approx(0.875)


def test_invalid_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="locator_quality"):
        compose_confidence(locator_quality=1.1, parser_agreement=1, source_quality=1)
    with pytest.raises(ValueError, match="weak_locator_penalty"):
        ConfidencePolicy(weak_locator_penalty=-0.1)


def test_confidence_result_does_not_encode_approval() -> None:
    result = ConfidenceResult(
        confidence=0.99,
        locator_quality=1,
        parser_agreement=1,
        source_quality=1,
        ocr_quality=None,
        weak_locator=False,
        locator_penalty=1,
    )
    assert "status" not in result.to_dict()
    assert "approved" not in result.to_dict()
