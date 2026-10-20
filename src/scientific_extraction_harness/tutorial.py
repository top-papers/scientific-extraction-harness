"""Ограниченное локальное обучение для Windows; без установок, сетевых вызовов и вывода секретов."""
from __future__ import annotations
from dataclasses import dataclass
import os, shutil, sys
from html import escape
from typing import Mapping

OPENCODE_PROMPT = """Работай в явно названном проекте https://github.com/top-papers/scientific-extraction-harness и только в его текущем локальном корне. Это операционное задание: продолжай до финального результата или точной блокировки, а не останавливайся после общего плана.

Сначала осмотри текущий проект, git-состояние, README.md, AGENTS.md, opencode.jsonc и относящиеся к задаче документы. Подтверди фактический корень и доступные команды; не предполагай, что это другой репозиторий. Не меняй глобальную конфигурацию OpenCode, пользовательскую конфигурацию, другие репозитории или файлы за пределами корня проекта.

Если harness или его CLI отсутствует в текущем окружении, подготовь безопасные локальные шаги, описанные в README (изолированное .venv и локальная установка пакета). Перед установкой, изменением окружения, сетью или загрузкой зависимостей остановись и попроси явное подтверждение; после подтверждения выполни разрешённую установку сам и проверь результат. Не запускай удалённые скрипты и не обходи отказ разрешения инструмента.

После разрешённой установки автономно выполни все разрешённые локальные шаги: установку проверенного bundled-агента проекта, проверки, локальный expert/tutorial workflow, извлечение, нормализацию, provenance, экспертную проверку и локальный экспорт. Используй только доступные локальные команды и сервисы проекта. Для каждого значения сохраняй идентификатор документа, страницу, modality и locator; при неоднозначности abstain/помечай неопределённость, не выдумывай. Не заявляй, что браузер, сервер, модель, команда или экспорт сработали, пока это не проверено фактическим результатом.

Обязательные действия человека — не выполняй и не имитируй их:
- одобрить установку, сетевой доступ, вход/auth и публикацию;
- ввести токен Hugging Face самостоятельно через `hf auth login` (или официальный браузерный flow) в локальном терминале/браузере; никогда не проси токен, пароль или код в чате, не вставляй их в команды, файлы, логи или отчёты;
- выбрать и подтвердить PDF, на обработку которого у человека есть разрешение;
- проверить каждое извлечённое значение и provenance, выставить оценку 0–10;
- отдельно одобрить PR/публикацию в Hugging Face после просмотра обезличенного результата.
Перед каждым таким действием сообщи, что именно заблокировано, почему, какие обезличенные данные будут затронуты и какое точное действие требуется от человека. После получения разрешения продолжай автоматически до следующей блокировки. Если инструмент или политика отклонили действие, честно сообщи отказ и не пытайся его обойти.

Безопасность: никогда не раскрывай секреты или персональные данные, не сохраняй токены в проекте и не отправляй исходный PDF/необезличенные данные. Не делай commit/push/публикацию без отдельного разрешения. В финале дай точный статус: корень проекта, обнаруженное состояние, все выполненные команды и наблюдаемые результаты, изменённые файлы, локальные outputs, проверки, оставшиеся блокеры и конкретное обязательное действие человека. Никогда не утверждай unsupported action."""


def render_opencode_prompt_html() -> str:
    return "<section class='prompt-box'><h2>Промпт для OpenCode</h2><p>Скопируйте этот безопасный запрос и вставьте его в чат OpenCode в папке проекта.</p><textarea id='opencode-prompt' readonly aria-label='Промпт для OpenCode'>{}</textarea><button id='copy-prompt' type='button'>Скопировать промпт</button><p class='prompt-note'><strong>Безопасность:</strong> этот текст не содержит токенов. OpenCode должен спрашивать подтверждение перед сетью, аутентификацией и действиями с токенами; никогда не отправляйте секреты в чат.</p></section>".format(escape(OPENCODE_PROMPT))

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
    prompt_block = render_opencode_prompt_html()
    script = "<script>document.getElementById('copy-prompt').addEventListener('click',function(){var field=document.getElementById('opencode-prompt');navigator.clipboard.writeText(field.value).then(function(){var button=document.getElementById('copy-prompt');button.textContent='Скопировано';setTimeout(function(){button.textContent='Скопировать промпт'},1200)})});</script>"
    return "<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Руководство эксперта для Windows</title><style>body{font:16px system-ui;max-width:850px;margin:2rem auto;padding:0 1rem;color:#17221f} .ok{color:green}.missing{color:#a33}code{background:#eee;padding:.2rem}.warning,.prompt-note{border:1px solid #c88;padding:1rem}.prompt-box{margin:2rem 0;padding:1.25rem;background:#eef5ef;border:1px solid #9ab5a0;border-radius:8px}.prompt-box textarea{display:block;width:100%;min-height:270px;padding:.8rem;box-sizing:border-box;font:14px/1.45 monospace;border:1px solid #78927d;border-radius:5px;background:#fff;color:#17221f}.prompt-box button{margin-top:.75rem;padding:.65rem 1rem;cursor:pointer}</style></head><body><h1>Руководство эксперта для Windows</h1><p>Ограниченная настройка с приоритетом локальной работы.</p><h2>Локальные проверки</h2><ul>" + rows + "</ul><h2>Точные следующие шаги в PowerShell</h2><ol>" + commands + "</ol>" + prompt_block + "<div class='warning'><b>Подтвердите действие перед началом:</b> установка и команда <code>hf auth login</code> используют вашу среду и сеть. Никогда не вставляйте токены в команды, журналы или исходный код.</div><p><a href='/'>Вернуться в ExpertApp</a></p>" + script + "</body></html>"
