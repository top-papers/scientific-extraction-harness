"""Небольшое локальное веб-приложение для экспертной проверки кандидатов извлечения.

В приложении намеренно нет анализатора PDF и зависимости от frontend. Вызывающая
сторона передаёт сервис извлечения и экспортёр; браузер взаимодействует только
с этим локальным процессом, а загруженный PDF хранится в памяти текущего
экземпляра приложения.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from email.parser import BytesParser
from email.policy import default
import html
import http.server
import json
import re
import threading
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlsplit

from .tutorial import render_opencode_prompt_html, render_tutorial_html


class ExpertAppError(ValueError):
    """Возникает при недействительной загрузке или отправке проверки."""


ExtractionService = Callable[[bytes, str], Any]
Exporter = Callable[[Mapping[str, Any]], Any]
Publisher = Callable[[str, Mapping[str, Any]], Any]


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    # JSON quoted strings are valid YAML and prevent values/comments from
    # becoming YAML syntax.  No source PDF text is copied into this package.
    return json.dumps(str(value), ensure_ascii=False)


def safe_yaml(value: Any, indent: int = 0) -> str:
    """Serialize basic package data without unsafe YAML tags or dependencies."""
    value = _plain(value)
    pad = " " * indent
    if isinstance(value, Mapping):
        if not value:
            return "{}"
        lines: list[str] = []
        for key, item in value.items():
            key_text = json.dumps(str(key), ensure_ascii=False)
            if isinstance(item, (Mapping, list, tuple)) and item:
                lines.append(f"{pad}{key_text}:")
                lines.append(safe_yaml(item, indent + 2))
            else:
                lines.append(f"{pad}{key_text}: {safe_yaml(item, indent + 2)}")
        return "\n".join(lines)
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        lines = []
        for item in value:
            if isinstance(item, (Mapping, list, tuple)) and item:
                lines.append(f"{pad}-")
                lines.append(safe_yaml(item, indent + 2))
            else:
                lines.append(f"{pad}- {safe_yaml(item, indent + 2)}")
        return "\n".join(lines)
    return _yaml_scalar(value)


def _candidate_payload(result: Any) -> list[dict[str, Any]]:
    result = _plain(result)
    if isinstance(result, Mapping):
        candidates = result.get("candidates", result.get("records", result.get("evidence")))
        if candidates is None:
            candidates = [result]
    else:
        candidates = result
    if not isinstance(candidates, (list, tuple)):
        raise ExpertAppError("сервис извлечения должен вернуть кандидатов или список кандидатов")
    payload: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate = _plain(candidate)
        if not isinstance(candidate, Mapping):
            raise ExpertAppError("каждый извлечённый кандидат должен быть отображением")
        item = dict(candidate)
        # Preserve extractor confidence under its own name; never turn it into
        # an expert score or review status.
        if "confidence" in item and "extractor_confidence" not in item:
            item["extractor_confidence"] = item.pop("confidence")
        payload.append(item)
    return payload


class ExpertApp:
    """Stateful, single-review workspace served by :mod:`http.server`.

    ``extractor`` receives ``(pdf_bytes, filename)``. ``exporter`` receives a
    YAML-safe mapping containing candidates and the explicit expert review and
    may return a path, text, or any result meaningful to the embedding caller.
    """

    def __init__(self, extractor: ExtractionService | None = None, exporter: Exporter | None = None, publisher: Publisher | None = None):
        self.extractor = extractor
        self.exporter = exporter
        self.publisher = publisher
        self._lock = threading.Lock()
        self._document: dict[str, Any] | None = None
        self._review: dict[str, Any] | None = None
        self.last_export: Any = None

    def intake(self, filename: str, pdf_bytes: bytes) -> list[dict[str, Any]]:
        if not filename.lower().endswith(".pdf"):
            raise ExpertAppError("для загрузки нужен файл .pdf")
        if not pdf_bytes:
            raise ExpertAppError("загруженный PDF пуст")
        if self.extractor is None:
            raise ExpertAppError("извлечение недоступно (extraction unavailable): настройте сервис извлечения")
        try:
            candidates = _candidate_payload(self.extractor(pdf_bytes, filename))
        except ExpertAppError:
            raise
        except Exception as exc:
            raise ExpertAppError(f"extraction failed: {exc}") from exc
        with self._lock:
            self._document = {"filename": filename, "candidates": candidates}
            self._review = None
            self.last_export = None
        return candidates

    def review(self, score: Any, comment: str | None = None, submit: bool = False) -> Any:
        try:
            numeric = int(score)
        except (TypeError, ValueError) as exc:
            raise ExpertAppError("expert score is required and must be an integer from 0 to 10") from exc
        if numeric < 0 or numeric > 10 or str(score).strip() != str(numeric):
            raise ExpertAppError("expert score is required and must be an integer from 0 to 10")
        if self._document is None:
            raise ExpertAppError("сначала извлеките данные из PDF")
        if comment is not None and len(comment) > 2000:
            raise ExpertAppError("комментарий слишком длинный")
        package = {"document": dict(self._document), "review": {"expert_score": numeric, "comment": comment or None}}
        self._review = package["review"]
        if self.exporter is None:
            raise ExpertAppError("экспорт недоступен: настройте экспортёр проверенного пакета")
        try:
            self.last_export = self.exporter(package)
            if submit:
                if self.publisher is None:
                    raise ExpertAppError("отправка набора данных недоступна: настройте издатель Hugging Face")
                self.last_export = {"local_export": self.last_export, "submission": self.publisher(str(self.last_export), package)}
        except ExpertAppError:
            raise
        except Exception as exc:
            raise ExpertAppError(f"экспорт проверенного YAML завершился ошибкой (export failed): {exc}") from exc
        return self.last_export

    def package(self) -> dict[str, Any] | None:
        if self._document is None:
            return None
        return {"document": dict(self._document), "review": self._review}


_CSS = """*{box-sizing:border-box}body{margin:0;background:#10211f;color:#eff4e9;font:16px system-ui,sans-serif;line-height:1.5}main{max-width:980px;margin:0 auto;padding:42px 22px 72px}header{border-bottom:1px solid #40615a;padding-bottom:28px;margin-bottom:22px}h1{font:700 42px Georgia,serif;letter-spacing:-1px;margin:0 0 8px;color:#f4c95d}h2{font-size:21px;color:#f4c95d;margin-top:0}h3{margin:0 0 6px}.eyebrow{color:#b8e3a7;font-size:13px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}.lede{max-width:680px;color:#c9d9ce}.steps{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:24px 0}.step-tab{margin:0;border:1px solid #40615a;border-radius:8px;background:#17332f;color:#c9d9ce;padding:10px 8px;font-size:13px;text-align:left}.step-tab[aria-current=true]{border-color:#f4c95d;color:#f4c95d;background:#243f36}.step-tab span{display:block;font-size:11px;color:#a9c1b4}.tutorial{background:#17332f;border:1px solid #40615a;border-radius:12px;padding:22px;margin:18px 0}.tutorial[hidden]{display:none}.check{color:#b8e3a7;font-weight:700}.safe{border-left:3px solid #b8e3a7;padding:10px 14px;background:#102522}.recovery{border-left:3px solid #e08b7c;padding:10px 14px;background:#342523}.command{position:relative;background:#0b1716;border:1px solid #40615a;border-radius:7px;padding:12px 42px 12px 14px;margin:10px 0;overflow:auto}code{color:#f4c95d}.copy{position:absolute;right:8px;top:7px;margin:0;padding:6px 9px;border-radius:5px;background:#40615a;color:#eff4e9;font-size:12px}section{background:#17332f;border:1px solid #40615a;border-radius:12px;padding:22px;margin:18px 0}label{display:block;font-weight:650;margin:15px 0 7px}input,textarea{width:100%;padding:11px;border:1px solid #64847a;border-radius:6px;background:#0d1b1a;color:#fff;font:inherit}input[type=checkbox]{width:auto;margin-right:8px}button{margin-top:18px;background:#f4c95d;color:#14231f;border:0;border-radius:999px;padding:12px 20px;font-weight:750;cursor:pointer}button:hover{background:#ffe49a}.next{float:right}.candidate{border-left:3px solid #f4c95d;padding:12px 16px;margin:12px 0;background:#102522}.meta{color:#a9c1b4;font-size:14px}.error{background:#542b2b;border-color:#e08b7c}.success{color:#b8e3a7}@media(max-width:700px){.steps{grid-template-columns:1fr 1fr}.step-tab:last-child{grid-column:span 2}}"""


def _page(app: ExpertApp, message: str = "", error: bool = False) -> str:
    package = app.package()
    candidates = package["document"]["candidates"] if package else []
    cards = "".join("<article class='candidate'>" + "".join(f"<div><b>{html.escape(str(k))}</b>: {html.escape(str(v))}</div>" for k, v in c.items()) + "</article>" for c in candidates)
    report = "<p class='meta'>Отчёта об извлечении пока нет. PDF остаётся в этом локальном процессе.</p>" if not package else f"<p class='meta'>Локальный документ: <code>{html.escape(str(package['document']['filename']))}</code> · кандидатов: {len(candidates)}</p>{cards}"
    notice = f"<section class={'error' if error else 'success'} role='alert'>{html.escape(message)}</section>" if message else ""
    review = "" if not package else "<section id='review'><p class='eyebrow'>Шаг 5 · Отправить рецензию</p><h2>Оцените то, что подтверждает источник</h2><p>Проверьте страницу, тип источника, локатор и неопределённость каждого кандидата. Оценка отражает ваше экспертное суждение; уверенность экстрактора показана отдельно.</p><form method='post' action='/review'><label for='score'>Экспертная оценка <span aria-label='required'>*</span> (0–10)</label><input id='score' name='score' type='number' min='0' max='10' step='1' required><label for='comment'>Что вы проверили? <span class='meta'>(необязательно)</span></label><textarea id='comment' name='comment' rows='4' maxlength='2000' placeholder='Например: проверена таблица 2, строка 4 на странице 3.'></textarea><label><input id='submit' name='submit' type='checkbox' value='1'> Отправить в настроенный набор данных Hugging Face</label><p class='safe'><strong>Безопасность токена:</strong> экспорт сначала выполняется локально. Отмечайте этот флажок, только если вы уже вошли через CLI Hugging Face или задали токен в этом терминале. Никогда не вставляйте токен на эту страницу, в PDF или файл проекта.</p><button type='submit'>Экспортировать проверенный YAML</button></form></section>"
    tutorial = "<section class='tutorial' id='tutorial'><p class='eyebrow'>Краткое руководство для Windows</p><h2>Пройдите пять шагов</h2><p class='lede'>Эта страница не запрашивает пароль или токен. Выполняйте команды в PowerShell, храните учётные данные в локальном сеансе, а затем вернитесь сюда для проверки.</p><nav class='steps' aria-label='Шаги руководства'>" + "".join(f"<button class='step-tab' type='button' data-step='{i}' aria-current={'true' if i == 1 else 'false'}><span>ШАГ {i}</span>{title}</button>" for i, title in enumerate(('Установить Python','Установить OpenCode','Получить приложение','Выбрать модель','Запустить процесс'), 1)) + "</nav>"
    tutorial += "<div class='tutorial-panel' data-panel='1'><h3>Установить Python</h3><p>В PowerShell установите Python 3.11 или новее. Затем откройте новое окно PowerShell.</p><pre class='command'><code>winget install Python.Python.3.12</code><button class='copy' type='button'>Копировать</button></pre><p class='meta'>Восстановление: если <code>py</code> не найден, переустановите Python и выберите <strong>Add python.exe to PATH</strong>.</p></div>"
    tutorial += "<div class='tutorial-panel' data-panel='2' hidden><h3>Установить OpenCode</h3><p>Установите OpenCode по официальной инструкции для Windows, затем проверьте работу команды.</p><pre class='command'><code>opencode --version</code><button class='copy' type='button'>Копировать</button></pre><p class='meta'>Восстановление: закройте и снова откройте PowerShell после установки. Если команда всё ещё недоступна, снова запустите официальный установщик; не запускайте неизвестные скрипты.</p></div>"
    tutorial += "<div class='tutorial-panel' data-panel='3' hidden><h3>Скачать и запустить приложение</h3><p>В папке загруженного проекта создайте изолированное окружение и установите приложение.</p><pre class='command'><code>py -m venv .venv\n.\\.venv\\Scripts\\Activate.ps1\npy -m pip install -e .</code><button class='copy' type='button'>Копировать</button></pre><p>Установите проверенный агент OpenCode и запустите локальный интерфейс:</p><pre class='command'><code>scientific-extraction-harness opencode-install\nscientific-extraction-harness expert serve</code><button class='copy' type='button'>Копировать</button></pre><p class='meta'>Откройте <code>http://127.0.0.1:8000/</code>. По умолчанию сервер доступен только локально.</p></div>"
    tutorial += "<div class='tutorial-panel' data-panel='4' hidden><h3>Выбрать модель и безопасно пройти аутентификацию</h3><p>Задайте поставщика и модель, которые поддерживает ваша установка OpenCode. Имя модели не является секретом.</p><pre class='command'><code>$env:OPENCODE_MODEL = 'provider/model'</code><button class='copy' type='button'>Копировать</button></pre><p>Для отправки в набор данных выполните аутентификацию через CLI Hugging Face в этом терминале. Эта страница никогда не сохраняет токен.</p><pre class='command'><code>hf auth login</code><button class='copy' type='button'>Копировать</button></pre><p class='safe'><strong>Никогда:</strong> не помещайте токены в <code>opencode.jsonc</code>, историю PowerShell, исходный код, снимки экрана или комментарии к рецензии. Не вставляйте токен на эту страницу. Если токен утёк, немедленно отзовите его.</p></div>"
    tutorial += "<div class='tutorial-panel' data-panel='5' hidden><h3>Запустить и проверить</h3><p>Выберите ниже разрешённый научный PDF и нажмите <strong>Извлечь локально</strong>. Перед оценкой сопоставьте каждого кандидата с источником.</p><p class='recovery'>Если извлечение недоступно, для этого автономного сервера это ожидаемо: вызывающая сторона должна передать сервис извлечения, сохраняющий происхождение данных. Нельзя принимать утверждение без страницы, типа источника, локатора и неопределённости.</p></div></section>"
    tutorial += render_opencode_prompt_html()
    intake = "<section id='intake'><p class='eyebrow'>Шаг 5 · Запустить процесс</p><h2>Выберите разрешённый PDF</h2><form method='post' action='/intake' enctype='multipart/form-data'><label for='pdf'>Научный PDF</label><input id='pdf' name='pdf' type='file' accept='.pdf,application/pdf' required><button type='submit'>Извлечь локально</button></form></section>"
    return f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Локальная проверка извлечения</title><style>{_CSS}</style></head><body><main><header><p class='eyebrow'>Локально · проверяемо · проверено человеком</p><h1>Доказательства, а не догадки.</h1><p class='lede'>Пять шагов: от чистого терминала Windows до проверенного извлечения. Ваш PDF остаётся в этом локальном процессе.</p><p><a href='/tutorial'>Открыть отдельные проверки требований и точные следующие шаги</a></p></header>{notice}{tutorial}{intake}<section><p class='eyebrow'>Результаты</p><h2>Готовый отчёт</h2>{report}</section>{review}</main><script>document.querySelectorAll('.step-tab').forEach(function(tab){{tab.addEventListener('click',function(){{var step=tab.dataset.step;document.querySelectorAll('.tutorial-panel').forEach(function(panel){{panel.hidden=panel.dataset.panel!==step}});document.querySelectorAll('.step-tab').forEach(function(item){{item.setAttribute('aria-current',item===tab?'true':'false')}})}})}});document.querySelectorAll('.copy').forEach(function(button){{button.addEventListener('click',function(){{var text=button.parentElement.querySelector('code').innerText;navigator.clipboard.writeText(text);button.textContent='Скопировано';setTimeout(function(){{button.textContent='Копировать'}},1200)}})}});var promptButton=document.getElementById('copy-prompt');if(promptButton){{promptButton.addEventListener('click',function(){{navigator.clipboard.writeText(document.getElementById('opencode-prompt').value).then(function(){{promptButton.textContent='Скопировано';setTimeout(function(){{promptButton.textContent='Скопировать промпт'}},1200)}})}})}});</script></body></html>"


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "ScientificExpertApp/1.0"
    def _send(self, body: str, status: int = 200, content_type: str = "text/html; charset=utf-8") -> None:
        encoded = body.encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
    @property
    def app(self) -> ExpertApp:
        return self.server.expert_app  # type: ignore[attr-defined]
    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/tutorial":
            self._send(render_tutorial_html())
            return
        if path != "/": self._send("не найдено", 404); return
        self._send(_page(self.app))
    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            if path == "/intake":
                content_type = self.headers.get("Content-Type", "")
                message = BytesParser(policy=default).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
                part = next((p for p in message.walk() if p.get("name") == "pdf"), None)
                if part is None: raise ExpertAppError("выберите PDF, чтобы начать")
                self.app.intake(part.get_filename() or "upload.pdf", part.get_payload(decode=True) or b"")
                self._send(_page(self.app, "Извлечение готово. Перед оценкой проверьте происхождение данных.")); return
            if path == "/review":
                fields = parse_qs(body.decode("utf-8"), keep_blank_values=True)
                self.app.review(fields.get("score", [""])[0], fields.get("comment", [""])[0] or None, bool(fields.get("submit")))
                self._send(_page(self.app, "Проверенный YAML успешно экспортирован.")); return
            self._send("не найдено", 404); return
        except ExpertAppError as exc:
            self._send(_page(self.app, str(exc), True), 400 if "unavailable" not in str(exc) else 503)
        except Exception as exc:
            self._send(_page(self.app, f"запрос завершился ошибкой: {exc}", True), 400)
    def log_message(self, *_: Any) -> None: return


def create_server(address: tuple[str, int] = ("127.0.0.1", 8000), *, extractor: ExtractionService | None = None, exporter: Exporter | None = None, publisher: Publisher | None = None) -> http.server.ThreadingHTTPServer:
    """Create a local server; call ``serve_forever`` or use as a context manager."""
    app = ExpertApp(extractor, exporter, publisher)
    server = http.server.ThreadingHTTPServer(address, _Handler)
    server.expert_app = app  # type: ignore[attr-defined]
    return server


__all__ = ["ExpertApp", "ExpertAppError", "create_server", "safe_yaml"]