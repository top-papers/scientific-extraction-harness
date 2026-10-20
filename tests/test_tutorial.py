from scientific_extraction_harness.cli import main
from scientific_extraction_harness.tutorial import EnvironmentStatus, check_environment, render_tutorial_html, render_tutorial_text

def test_environment_hides_token():
    status = check_environment({'HF_TOKEN': 'secret', 'OPENCODE_MODEL': 'provider/model'})
    text = render_tutorial_text(status)
    assert status.hf_token_configured and 'secret' not in text and 'значение скрыто' in text

def test_tutorial_commands_and_safety():
    text = render_tutorial_text(EnvironmentStatus('3.12.0', True, 'opencode.exe', True, False, False))
    assert 'py -m pip install -e .' in text and 'hf auth login' in text
    assert 'Ничего не запускается автоматически' in text

def test_html_tutorial():
    html = render_tutorial_html(EnvironmentStatus('3.11.0', True, 'missing', False, True, True))
    assert 'Руководство эксперта для Windows' in html and 'настроен (значение скрыто)' in html and 'hf auth login' in html

def test_cli_tutorial(capsys):
    assert main(['tutorial']) == 0
    assert 'expert serve' in capsys.readouterr().out
