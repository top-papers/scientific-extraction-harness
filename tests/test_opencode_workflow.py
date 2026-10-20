from pathlib import Path

import pytest

from scientific_extraction_harness.cli import _parser
from scientific_extraction_harness.opencode_bootstrap import install_bundled_agent


def test_install_bundled_agent_is_validated_and_idempotent(tmp_path):
    destination = install_bundled_agent(tmp_path)
    text = destination.read_text(encoding="utf-8")
    assert "description:" in text
    assert "python -c" not in text
    with pytest.raises(FileExistsError):
        install_bundled_agent(tmp_path)


def test_cli_exposes_expert_serve_and_install():
    parser = _parser()
    assert parser.parse_args(["opencode-install"]).command == "opencode-install"
    args = parser.parse_args(["expert", "serve", "--port", "8123"])
    assert args.expert_command == "serve"
    assert args.port == 8123
    assert args.no_install is False


def test_expert_serve_accepts_install_flags(tmp_path):
    parser = _parser()
    args = parser.parse_args(["expert", "serve", "--project-root", str(tmp_path), "--force", "--no-install"])
    assert args.expert_command == "serve"
    assert args.project_root == tmp_path
    assert args.force is True
    assert args.no_install is True


def test_readme_and_copyable_prompt_name_project_and_human_gates():
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    prompt = __import__("scientific_extraction_harness.tutorial", fromlist=["OPENCODE_PROMPT"]).OPENCODE_PROMPT
    for text in (readme, prompt):
        assert "https://github.com/top-papers/scientific-extraction-harness" in text
        assert "hf auth login" in text
        assert "оценку 0–10" in text
        assert "не пытайся его обойти" in text
    assert "не проси токен" in prompt
    assert "глобальную конфигурацию" in prompt
    assert "PR/публикацию" in prompt


def test_project_config_uses_local_model_placeholder():
    config = Path(__file__).parents[1] / "opencode.jsonc"
    text = config.read_text(encoding="utf-8")
    assert '"agents"' in text
    assert '"model": "{env:OPENCODE_MODEL}"' in text
    assert '"$schema"' in text
    assert '"permissions"' in text
    assert "deepseek" not in text.lower()
