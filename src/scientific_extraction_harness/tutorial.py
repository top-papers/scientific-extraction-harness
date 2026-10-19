"""Bounded local-first Windows onboarding; no installs, network calls, or secret output."""
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
    mark = lambda ok: "OK" if ok else "MISSING"
    return "\n".join([
        "Scientific Extraction Harness — bounded Windows tutorial", "",
        "LOCAL CHECKS (no network calls; token values are never printed)",
        f"  Python 3.11+: {mark(s.python_ok)} ({s.python})",
        f"  OpenCode on PATH: {mark(s.opencode_ok)} ({s.opencode})",
        f"  OPENCODE_MODEL: {mark(s.model_configured)} (value hidden)",
        f"  Hugging Face token: {mark(s.hf_token_configured)} (value hidden)", "",
        "1. cd C:\\path\\to\\scientific-extraction-harness",
        "2. Review, then optionally run: py -m pip install -e .",
        "3. Configure locally: $env:OPENCODE_MODEL = 'provider/model'",
        "4. Authenticate only when needed: hf auth login",
        "5. Start the app: scientific-extraction-harness expert serve",
        "6. Open http://127.0.0.1:8000/tutorial, then upload an authorized PDF.", "",
        "SAFETY: installs, authentication, and dataset submission require explicit user action. Nothing runs automatically.",
    ])

def render_tutorial_html(status: EnvironmentStatus | None = None) -> str:
    s = status or check_environment()
    rows = "".join(f"<li><b>{escape(label)}</b>: <span class='{('ok' if ok else 'missing')}'>{escape(value)}</span></li>" for label, ok, value in (("Python 3.11+", s.python_ok, s.python), ("OpenCode on PATH", s.opencode_ok, s.opencode), ("OPENCODE_MODEL", s.model_configured, "configured (value hidden)" if s.model_configured else "not configured (value hidden)"), ("Hugging Face token", s.hf_token_configured, "configured (value hidden)" if s.hf_token_configured else "not configured (value hidden)")))
    commands = "".join(f"<li><code>{escape(x)}</code></li>" for x in ("cd C:\\path\\to\\scientific-extraction-harness", "py -m pip install -e .", "$env:OPENCODE_MODEL = 'provider/model'", "hf auth login", "scientific-extraction-harness expert serve"))
    return "<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Windows tutorial</title><style>body{font:16px system-ui;max-width:850px;margin:2rem auto;padding:0 1rem}.ok{color:green}.missing{color:#a33}code{background:#eee;padding:.2rem}.warning{border:1px solid #c88;padding:1rem}</style></head><body><h1>Windows expert tutorial</h1><p>Bounded, local-first setup.</p><h2>Local checks</h2><ul>" + rows + "</ul><h2>Exact PowerShell next steps</h2><ol>" + commands + "</ol><div class='warning'><b>Confirm before acting:</b> installs and <code>hf auth login</code> use your environment/network. Never paste tokens into commands, logs, or source.</div><p><a href='/'>Return to ExpertApp</a></p></body></html>"
