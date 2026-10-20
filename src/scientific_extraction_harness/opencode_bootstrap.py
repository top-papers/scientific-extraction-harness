"""Safe installation of the project's bundled OpenCode agent definition.

This module deliberately installs a reviewed, package-bundled markdown file. It
never evaluates agent content, runs a downloaded script, or embeds credentials.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import os
import re
import tempfile


_AGENT_NAME = "scientific-extraction-expert.md"
_AGENT_SHA256 = "0a229d51e04f9a905b8e9139de8634ebef50deb7b13abcc44b3cd7a676fe627c"
_FRONTMATTER = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*\n", re.DOTALL)


def bundled_agent_path() -> Path:
    return Path(__file__).with_name("agents") / _AGENT_NAME


def _validated_agent() -> bytes:
    data = bundled_agent_path().read_bytes()
    if sha256(data).hexdigest() != _AGENT_SHA256:
        raise ValueError("bundled OpenCode agent failed integrity validation")
    text = data.decode("utf-8")
    match = _FRONTMATTER.match(text)
    if not match or "description:" not in match.group("body"):
        raise ValueError("bundled OpenCode agent has invalid frontmatter")
    if "```" in text or "python -c" in text or "powershell -" in text:
        raise ValueError("bundled OpenCode agent contains executable content")
    return data


def install_bundled_agent(project_root: str | Path = ".", *, force: bool = False) -> Path:
    """Install the reviewed agent into ``<project>/.opencode/agents``.

    The destination is local and deterministic. Existing files are preserved by
    default; replacement requires the explicit ``force`` flag.
    """
    data = _validated_agent()
    root = Path(project_root).resolve()
    destination = root / ".opencode" / "agents" / _AGENT_NAME
    if destination.exists() and not force:
        raise FileExistsError(f"agent already exists: {destination} (use --force to replace)")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{_AGENT_NAME}.", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


__all__ = ["bundled_agent_path", "install_bundled_agent"]
