"""Ограниченное локальное обучение для Windows; без установок, сетевых вызовов и вывода секретов."""
from __future__ import annotations
from dataclasses import dataclass
import os, shutil, sys
from html import escape
from typing import Mapping

@dataclass(frozen=True)
class EnvironmentStatus:
    python: str
    python_ok: bool
    opencode: str
    opencode_ok: bool
    model_configured: bool
    hf_token_configured: bool

def check_environment(environ: Mapping[str, str] | None = None) -> EnvironmentStatus:
    env = os.environ if environ is None else environ
    path = shutil.which("opencode")
    return EnvironmentStatus(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", sys.version_info >= (3, 11), path or "not found on PATH", path is not None, bool(env.get("OPENCODE_MODEL", "").strip()), bool((env.get("HF_TOKEN") or env.get("HUGGINGFACE_TOKEN") or "").strip()))

def render_tutorial_text(status: EnvironmentStatus | None = None) -> str:
    s = status or check_environment()
    mark = lambda ok: "ГОТОВО" if ok else "ОТСУТСТВУЕТ"
    return "\n".join([
        "Scientific Extraction Harness — ограниченный учебник для Windows", "",
        "ЛОКАЛЬНЫЕ ПРОВЕРКИ (сетевые вызовы не выполняются; значения токенов никогда не выводятся)",
        f"  Python 3.11+: {mark(s.python_ok)} ({s.python})",
        f"  OpenCode в PATH: {mark(s.opencode_ok)} ({s.opencode})",
        f"  OPENCODE_MODEL: {mark(s.model_configured)} (значение скрыто)",
        f"  Токен Hugging Face: {mark(s.hf_token_configured)} (значение скрыто)", "",
        "1. cd C:\\path\\to\\scientific-extraction-harness",
        "2. Проверьте проект и при необходимости выполните: py -m pip install -e .",
        "3. Настройте локально: $env:OPENCODE_MODEL = 'provider/model'",
        "4. Аутентифицируйтесь только при необходимости: hf auth login",
        "5. Запустите приложение: scientific-extraction-harness expert serve",
        "6. Откройте http://127.0.0.1:8000/tutorial и загрузите разрешённый PDF.", "",
        "БЕЗОПАСНОСТЬ: установка, аутентификация и отправка набора данных требуют явного действия пользователя. Ничего не запускается автоматически.",
    ])

def render_tutorial_html(status: EnvironmentStatus | None = None) -> str:
    s = status or check_environment()
    rows = "".join(f"<li><b>{escape(label)}</b>: <span class='{('ok' if ok else 'missing')}'>{escape(value)}</span></li>" for label, ok, value in (("Python 3.11+", s.python_ok, s.python), ("OpenCode в PATH", s.opencode_ok, s.opencode), ("OPENCODE_MODEL", s.model_configured, "настроен (значение скрыто)" if s.model_configured else "не настроен (значение скрыто)"), ("Токен Hugging Face", s.hf_token_configured, "настроен (значение скрыто)" if s.hf_token_configured else "не настроен (значение скрыто)")))
    commands = "".join(f"<li><code>{escape(x)}</code></li>" for x in ("cd C:\\path\\to\\scientific-extraction-harness", "py -m pip install -e .", "$env:OPENCODE_MODEL = 'provider/model'", "hf auth login", "scientific-extraction-harness expert serve"))
    return "<!doctype html><html lang='ru'><head><meta charset='utf-8'><title>Руководство эксперта для Windows</title><style>body{font:16px system-ui;max-width:850px;margin:2rem auto;padding:0 1rem}.ok{color:green}.missing{color:#a33}code{background:#eee;padding:.2rem}.warning{border:1px solid #c88;padding:1rem}</style></head><body><h1>Руководство эксперта для Windows</h1><p>Ограниченная настройка с приоритетом локальной работы.</p><h2>Локальные проверки</h2><ul>" + rows + "</ul><h2>Точные следующие шаги в PowerShell</h2><ol>" + commands + "</ol><div class='warning'><b>Подтвердите действие перед началом:</b> установка и команда <code>hf auth login</code> используют вашу среду и сеть. Никогда не вставляйте токены в команды, журналы или исходный код.</div><p><a href='/'>Вернуться в ExpertApp</a></p></body></html>"
