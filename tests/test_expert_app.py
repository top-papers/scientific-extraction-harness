from __future__ import annotations

import json

import pytest

from scientific_extraction_harness.expert_app import ExpertApp, ExpertAppError, _page, safe_yaml


def test_page_has_safe_five_step_windows_tutorial_and_recovery_copy():
    page = _page(ExpertApp())
    assert "Пройдите пять шагов" in page
    assert "Установить Python" in page
    assert "Установить OpenCode" in page
    assert "Скачать и запустить приложение" in page
    assert "Выбрать модель и безопасно пройти аутентификацию" in page
    assert "Запустить и проверить" in page
    assert "type='button' data-step='1'" in page
    assert "Не вставляйте токен на эту страницу" in page
    assert "Если извлечение недоступно" in page
    assert "127.0.0.1:8000" in page


def test_page_explains_review_submission_token_safety_after_intake():
    app = ExpertApp(lambda _data, _name: {"candidates": []}, lambda package: package)
    app.intake("paper.pdf", b"pdf")
    page = _page(app)
    assert "Экспортировать проверенный YAML" in page
    assert "hf auth login" in page
    assert "Отмечайте этот флажок" in page
    assert "Что вы проверили?" in page


def test_intake_keeps_provenance_and_separates_confidence_from_expert_score():
    exported = []
    app = ExpertApp(
        extractor=lambda data, name: {"candidates": [{
            "document_id": "paper-7", "page": 3, "modality": "table",
            "locator": "table 2, row 4", "field": "yield", "value": "81",
            "unit": "%", "confidence": 0.82,
        }]},
        exporter=exported.append,
    )

    candidates = app.intake("paper.pdf", b"%PDF-local")
    assert candidates[0]["extractor_confidence"] == 0.82
    assert "confidence" not in candidates[0]
    app.review("9", "Checked against table 2")

    package = exported[0]
    assert package["document"]["candidates"][0]["page"] == 3
    assert package["document"]["candidates"][0]["extractor_confidence"] == 0.82
    assert package["review"] == {"expert_score": 9, "comment": "Checked against table 2"}


def test_score_is_required_and_comment_is_optional():
    app = ExpertApp(lambda _data, _name: {"candidates": []}, lambda package: package)
    app.intake("paper.pdf", b"pdf")
    with pytest.raises(ExpertAppError, match="score is required"):
        app.review("")
    result = app.review(0)
    assert result["review"] == {"expert_score": 0, "comment": None}


def test_unavailable_extraction_fails_clearly():
    app = ExpertApp(exporter=lambda package: package)
    with pytest.raises(ExpertAppError, match="extraction unavailable"):
        app.intake("paper.pdf", b"pdf")


def test_export_failure_is_explicit_and_invalid_file_rejected():
    app = ExpertApp(lambda _data, _name: {"candidates": []}, lambda _package: (_ for _ in ()).throw(RuntimeError("disk full")))
    with pytest.raises(ExpertAppError, match="\.pdf"):
        app.intake("notes.txt", b"text")
    app.intake("paper.pdf", b"pdf")
    with pytest.raises(ExpertAppError, match="export failed"):
        app.review(5)


def test_safe_yaml_quotes_scalars_and_is_round_trip_friendly():
    text = safe_yaml({"review": {"expert_score": 10, "comment": "looks: good # checked"}, "items": [{"value": "001"}]})
    assert '"comment": "looks: good # checked"' in text
    assert '"value": "001"' in text
    assert "!!python" not in text
