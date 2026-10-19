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


_CSS = """*{box-sizing:border-box}body{margin:0;background:#10211f;color:#eff4e9;font:16px system-ui,sans-serif}main{max-width:920px;margin:0 auto;padding:48px 22px}header{border-bottom:1px solid #40615a;padding-bottom:30px;margin-bottom:28px}h1{font:700 42px Georgia,serif;letter-spacing:-1px;margin:0 0 8px;color:#f4c95d}h2{font-size:20px;color:#f4c95d}section{background:#17332f;border:1px solid #40615a;border-radius:12px;padding:22px;margin:18px 0}label{display:block;font-weight:650;margin:15px 0 7px}input,textarea{width:100%;padding:11px;border:1px solid #64847a;border-radius:6px;background:#0d1b1a;color:#fff;font:inherit}button{margin-top:18px;background:#f4c95d;color:#14231f;border:0;border-radius:999px;padding:12px 20px;font-weight:750;cursor:pointer}button:hover{background:#ffe49a}.candidate{border-left:3px solid #f4c95d;padding:12px 16px;margin:12px 0;background:#102522}.meta{color:#a9c1b4;font-size:14px}.error{background:#542b2b;border-color:#e08b7c}.success{color:#b8e3a7}code{color:#f4c95d}"""


def _page(app: ExpertApp, message: str = "", error: bool = False) -> str:
    package = app.package()
    candidates = package["document"]["candidates"] if package else []
    cards = "".join("<article class='candidate'>" + "".join(f"<div><b>{html.escape(str(k))}</b>: {html.escape(str(v))}</div>" for k, v in c.items()) + "</article>" for c in candidates)
    report = "<p class='meta'>No extraction report yet. The PDF stays in this local process.</p>" if not package else f"<p class='meta'>Local document: <code>{html.escape(str(package['document']['filename']))}</code> · {len(candidates)} candidate(s)</p>{cards}"
    notice = f"<section class={'error' if error else 'success'} role='alert'>{html.escape(message)}</section>" if message else ""
    review = "" if not package else "<section><h2>Expert review</h2><form method='post' action='/review'><label for='score'>Expert score <span aria-label='required'>*</span> (0–10)</label><input id='score' name='score' type='number' min='0' max='10' step='1' required><label for='comment'>Comment <span class='meta'>(optional)</span></label><textarea id='comment' name='comment' rows='4' maxlength='2000'></textarea><label><input id='submit' name='submit' type='checkbox' value='1'> Submit a pull request to the configured Hugging Face dataset</label><p class='meta'>Optional: local export always happens first. If no token is configured, leave this unchecked; set HF_TOKEN or HUGGINGFACE_TOKEN locally to submit.</p><button type='submit'>Export reviewed YAML</button></form><p class='meta'>Extractor confidence is shown above and is separate from your expert score.</p></section>"
    setup = "<section><h2>Before you begin</h2><p class='meta'>OpenCode model setup: configure <code>OPENCODE_MODEL</code> with a provider/model supported by your local OpenCode installation. This app does not guess a model or request credentials.</p><p class='meta'>Extraction service unavailable: this standalone server has no extractor configured and will refuse PDF extraction until an embedding caller injects a provenance-preserving local service.</p></section>"
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Local extraction review</title><style>{_CSS}</style></head><body><main><header><h1>Evidence, not guesswork.</h1><p>Local PDF intake · candidate report · expert review</p></header>{notice}{setup}<section><h2>1 / Intake</h2><form method='post' action='/intake' enctype='multipart/form-data'><label for='pdf'>Scientific PDF</label><input id='pdf' name='pdf' type='file' accept='.pdf,application/pdf' required><button type='submit'>Extract locally</button></form></section><section><h2>2 / Ready report</h2>{report}</section>{review}</main></body></html>"


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "ScientificExpertApp/1.0"
    def _send(self, body: str, status: int = 200, content_type: str = "text/html; charset=utf-8") -> None:
        encoded = body.encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
    @property
    def app(self) -> ExpertApp:
        return self.server.expert_app  # type: ignore[attr-defined]
    def do_GET(self) -> None:
        if urlsplit(self.path).path != "/": self._send("not found", 404); return
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