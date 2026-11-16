"""Contract checks for the offline review form that the notebook generates."""
from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest

NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks" / "scientific_experiment_review.ipynb"


def _form_constants() -> dict[str, str]:
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    source = next(
        "".join(cell["source"])
        for cell in cells
        if "FORM_JS" in "".join(cell["source"]) and "def render_form" in "".join(cell["source"])
    )
    values: dict[str, str] = {}
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            values[node.targets[0].id] = node.value.value
    return values


def test_form_has_markup_loader_controls():
    body = _form_constants()["FORM_BODY"]
    assert 'id="load"' in body
    assert 'id="loadFile"' in body
    assert 'type="file"' in body
    assert 'accept="application/json,.json"' in body


def test_form_javascript_restores_saved_markup():
    js = _form_constants()["FORM_JS"]
    assert "function applyMarkup(" in js
    assert "$('loadFile').addEventListener('change'" in js
    assert "field_reviews" in js
    assert "reviewer_note" in js
    assert "sha256" in js
    assert "Согласие эксперта подтвердите заново" in js


def test_form_keeps_existing_actions():
    body = _form_constants()["FORM_BODY"]
    for element_id in ("send", "download", "load", "reset", "status", "consent"):
        assert f'id="{element_id}"' in body


def test_form_javascript_parses(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    target = tmp_path / "form.js"
    target.write_text(_form_constants()["FORM_JS"], encoding="utf-8")
    done = subprocess.run([node, "--check", str(target)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
