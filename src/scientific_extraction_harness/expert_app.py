"""Small local expert review web app for extraction candidates.

The app intentionally has no PDF parser and no frontend dependency.  A caller
injects an extraction service and an exporter; the browser only ever talks to
this local process and the uploaded PDF is retained in memory for the current
app instance.
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

from .tutorial import render_tutorial_html


class ExpertAppError(ValueError):
    """Raised for an invalid intake or review submission."""


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
        raise ExpertAppError("extraction service must return candidates or a candidate list")
    payload: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate = _plain(candidate)
        if not isinstance(candidate, Mapping):
            raise ExpertAppError("each extracted candidate must be a mapping")
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
            raise ExpertAppError("PDF intake requires a .pdf file")
        if not pdf_bytes:
            raise ExpertAppError("uploaded PDF is empty")
        if self.extractor is None:
            raise ExpertAppError("extraction unavailable: configure an extraction service")
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
            raise ExpertAppError("extract a PDF before reviewing")
        if comment is not None and len(comment) > 2000:
            raise ExpertAppError("comment is too long")
        package = {"document": dict(self._document), "review": {"expert_score": numeric, "comment": comment or None}}
        self._review = package["review"]
        if self.exporter is None:
            raise ExpertAppError("export unavailable: configure a reviewed-package exporter")
        try:
            self.last_export = self.exporter(package)
            if submit:
                if self.publisher is None:
                    raise ExpertAppError("dataset submission unavailable: configure a Hugging Face publisher")
                self.last_export = {"local_export": self.last_export, "submission": self.publisher(str(self.last_export), package)}
        except ExpertAppError:
            raise
        except Exception as exc:
            raise ExpertAppError(f"reviewed YAML export failed: {exc}") from exc
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
    report = "<p class='meta'>No extraction report yet. The PDF stays in this local process.</p>" if not package else f"<p class='meta'>Local document: <code>{html.escape(str(package['document']['filename']))}</code> · {len(candidates)} candidate(s)</p>{cards}"
    notice = f"<section class={'error' if error else 'success'} role='alert'>{html.escape(message)}</section>" if message else ""
    review = "" if not package else "<section id='review'><p class='eyebrow'>Step 5 · Submit review</p><h2>Score what the source supports</h2><p>Check the page, modality, locator, and uncertainty for every candidate. Your score is your expert judgment; extractor confidence is shown separately.</p><form method='post' action='/review'><label for='score'>Expert score <span aria-label='required'>*</span> (0–10)</label><input id='score' name='score' type='number' min='0' max='10' step='1' required><label for='comment'>What did you verify? <span class='meta'>(optional)</span></label><textarea id='comment' name='comment' rows='4' maxlength='2000' placeholder='For example: checked table 2, row 4 on page 3.'></textarea><label><input id='submit' name='submit' type='checkbox' value='1'> Submit to the configured Hugging Face dataset</label><p class='safe'><strong>Token safety:</strong> export happens locally first. Only check this box if you have already authenticated with the Hugging Face CLI or set a token in this terminal. Never paste a token into this page, a PDF, or a project file.</p><button type='submit'>Export reviewed YAML</button></form></section>"
    tutorial = "<section class='tutorial' id='tutorial'><p class='eyebrow'>A short Windows walkthrough</p><h2>Follow the five steps</h2><p class='lede'>This page never asks for your password or token. Run commands in PowerShell, keep credentials in your local session, then return here to review.</p><nav class='steps' aria-label='Tutorial steps'>" + "".join(f"<button class='step-tab' type='button' data-step='{i}' aria-current={'true' if i == 1 else 'false'}><span>STEP {i}</span>{title}</button>" for i, title in enumerate(('Install Python','Install OpenCode','Get the app','Choose model','Start workflow'), 1)) + "</nav>"
    tutorial += "<div class='tutorial-panel' data-panel='1'><h3>Install Python</h3><p>In PowerShell, install Python 3.11 or newer. Then open a new PowerShell window.</p><pre class='command'><code>winget install Python.Python.3.12</code><button class='copy' type='button'>Copy</button></pre><p class='meta'>Recovery: if <code>py</code> is not found, reinstall Python and select <strong>Add python.exe to PATH</strong>.</p></div>"
    tutorial += "<div class='tutorial-panel' data-panel='2' hidden><h3>Install OpenCode</h3><p>Install OpenCode from its official Windows instructions, then confirm the command works.</p><pre class='command'><code>opencode --version</code><button class='copy' type='button'>Copy</button></pre><p class='meta'>Recovery: close and reopen PowerShell after installation. If the command is still missing, use the official installer again; do not run an unknown script.</p></div>"
    tutorial += "<div class='tutorial-panel' data-panel='3' hidden><h3>Download and run the app</h3><p>From the downloaded project folder, create an isolated environment and install this app.</p><pre class='command'><code>py -m venv .venv\n.\\.venv\\Scripts\\Activate.ps1\npy -m pip install -e .</code><button class='copy' type='button'>Copy</button></pre><p>Install the reviewed OpenCode agent and start the local UI:</p><pre class='command'><code>scientific-extraction-harness opencode-install\nscientific-extraction-harness expert serve</code><button class='copy' type='button'>Copy</button></pre><p class='meta'>Open <code>http://127.0.0.1:8000/</code>. This server is local-only by default.</p></div>"
    tutorial += "<div class='tutorial-panel' data-panel='4' hidden><h3>Choose a model and authenticate safely</h3><p>Set a provider/model that your own OpenCode installation supports. The model name is not a secret.</p><pre class='command'><code>$env:OPENCODE_MODEL = 'provider/model'</code><button class='copy' type='button'>Copy</button></pre><p>For dataset submission, authenticate with the Hugging Face CLI in this terminal. The token is never stored by this page.</p><pre class='command'><code>hf auth login</code><button class='copy' type='button'>Copy</button></pre><p class='safe'><strong>Never:</strong> put tokens in <code>opencode.jsonc</code>, PowerShell history, source code, screenshots, or review comments. Never paste a token into this page. If a token leaks, revoke it immediately.</p></div>"
    tutorial += "<div class='tutorial-panel' data-panel='5' hidden><h3>Start, then review</h3><p>Choose a permitted scientific PDF below and select <strong>Extract locally</strong>. Read each candidate against its source before scoring.</p><p class='recovery'>If extraction is unavailable, that is expected for this standalone server: an embedding caller must inject a provenance-preserving extraction service. No claim should be accepted without page, modality, locator, and uncertainty.</p></div></section>"
    intake = "<section id='intake'><p class='eyebrow'>Step 5 · Start workflow</p><h2>Choose a permitted PDF</h2><form method='post' action='/intake' enctype='multipart/form-data'><label for='pdf'>Scientific PDF</label><input id='pdf' name='pdf' type='file' accept='.pdf,application/pdf' required><button type='submit'>Extract locally</button></form></section>"
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Local extraction review</title><style>{_CSS}</style></head><body><main><header><p class='eyebrow'>Local · auditable · human reviewed</p><h1>Evidence, not guesswork.</h1><p class='lede'>A five-step guide from a clean Windows terminal to a reviewed extraction. Your PDF stays in this local process.</p><p><a href='/tutorial'>Open the standalone prerequisite checks and exact next steps</a></p></header>{notice}{tutorial}{intake}<section><p class='eyebrow'>Results</p><h2>Ready report</h2>{report}</section>{review}</main><script>document.querySelectorAll('.step-tab').forEach(function(tab){{tab.addEventListener('click',function(){{var step=tab.dataset.step;document.querySelectorAll('.tutorial-panel').forEach(function(panel){{panel.hidden=panel.dataset.panel!==step}});document.querySelectorAll('.step-tab').forEach(function(item){{item.setAttribute('aria-current',item===tab?'true':'false')}})}})}});document.querySelectorAll('.copy').forEach(function(button){{button.addEventListener('click',function(){{var text=button.parentElement.querySelector('code').innerText;navigator.clipboard.writeText(text);button.textContent='Copied';setTimeout(function(){{button.textContent='Copy'}},1200)}})}});</script></body></html>"


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
        if path != "/": self._send("not found", 404); return
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
                if part is None: raise ExpertAppError("select a PDF to begin")
                self.app.intake(part.get_filename() or "upload.pdf", part.get_payload(decode=True) or b"")
                self._send(_page(self.app, "Extraction ready. Verify provenance before scoring.")); return
            if path == "/review":
                fields = parse_qs(body.decode("utf-8"), keep_blank_values=True)
                self.app.review(fields.get("score", [""])[0], fields.get("comment", [""])[0] or None, bool(fields.get("submit")))
                self._send(_page(self.app, "Reviewed YAML exported successfully.")); return
            self._send("not found", 404); return
        except ExpertAppError as exc:
            self._send(_page(self.app, str(exc), True), 400 if "unavailable" not in str(exc) else 503)
        except Exception as exc:
            self._send(_page(self.app, f"request failed: {exc}", True), 400)
    def log_message(self, *_: Any) -> None: return


def create_server(address: tuple[str, int] = ("127.0.0.1", 8000), *, extractor: ExtractionService | None = None, exporter: Exporter | None = None, publisher: Publisher | None = None) -> http.server.ThreadingHTTPServer:
    """Create a local server; call ``serve_forever`` or use as a context manager."""
    app = ExpertApp(extractor, exporter, publisher)
    server = http.server.ThreadingHTTPServer(address, _Handler)
    server.expert_app = app  # type: ignore[attr-defined]
    return server


__all__ = ["ExpertApp", "ExpertAppError", "create_server", "safe_yaml"]