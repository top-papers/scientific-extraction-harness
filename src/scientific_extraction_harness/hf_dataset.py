"""Secure, local-only publisher for reviewed YAML artifacts on Hugging Face."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_REPO_ID = "chaotic-good-project/scientific-extraction-review"
_API = "https://huggingface.co/api"
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.ya?ml$")


class HuggingFacePublishError(RuntimeError):
    """Raised when a dataset publication cannot be completed safely."""


@dataclass(frozen=True)
class PublishResult:
    repo_id: str
    branch: str
    filename: str
    status: str
    pull_request_url: str
    commit_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"repo_id": self.repo_id, "branch": self.branch, "filename": self.filename,
                "status": self.status, "pull_request_url": self.pull_request_url,
                "commit_url": self.commit_url}


def _token(explicit: str | None) -> str:
    value = explicit if explicit is not None else (os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN"))
    if not value or not value.strip():
        raise HuggingFacePublishError("Hugging Face token is required (pass token or set HF_TOKEN/HUGGINGFACE_TOKEN)")
    return value.strip()


def _filename(article_hash: str | None, document_id: str | None) -> str:
    raw = article_hash or document_id
    if not raw or not isinstance(raw, str) or not raw.strip():
        raise HuggingFacePublishError("article_hash or document_id is required")
    raw = raw.strip()
    if article_hash and re.fullmatch(r"[0-9a-fA-F]{64}", raw):
        return f"{raw.lower()}.yaml"
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", raw)
    if safe != raw or not _NAME.fullmatch(safe + ".yaml"):
        raise HuggingFacePublishError("unsafe document identifier for dataset filename")
    return safe + ".yaml"


class HuggingFacePublisher:
    """Publish one reviewed YAML file through a Hub branch and pull request."""
    def __init__(self, *, token: str | None = None, repo_id: str = DEFAULT_REPO_ID,
                 create_repo: bool = False, transport: Callable[..., Any] | None = None,
                 api_base: str = _API):
        if not isinstance(repo_id, str) or not _REPO.fullmatch(repo_id):
            raise HuggingFacePublishError("invalid Hugging Face repo_id")
        self.token = _token(token)
        self.repo_id, self.create_repo = repo_id, create_repo
        self.transport = transport or urlopen
        self.api_base = api_base.rstrip("/")

    def _request(self, method: str, path: str, payload: Any = None, *, content_type: str = "application/json") -> Any:
        data = None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if payload is not None:
            if content_type == "application/x-ndjson":
                data = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
            else:
                data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            headers["Content-Type"] = content_type
        request = Request(self.api_base + path, data=data, headers=headers, method=method)
        try:
            response = self.transport(request, timeout=30)
            body = response.read()
            return json.loads(body.decode()) if body else {}
        except HTTPError as exc:
            if exc.code == 404:
                raise HuggingFacePublishError("Hugging Face repository was not found") from exc
            raise HuggingFacePublishError(f"Hugging Face API request failed (HTTP {exc.code})") from exc
        except (URLError, OSError, ValueError) as exc:
            raise HuggingFacePublishError("Hugging Face API request failed") from exc

    def publish(self, reviewed_yaml: str, *, article_hash: str | None = None,
                document_id: str | None = None) -> PublishResult:
        if not isinstance(reviewed_yaml, str) or not reviewed_yaml.strip():
            raise HuggingFacePublishError("reviewed YAML is required")
        if "%PDF-" in reviewed_yaml or "JVBERi0" in reviewed_yaml:
            raise HuggingFacePublishError("PDF bytes are not allowed in dataset content")
        filename = _filename(article_hash, document_id)
        digest = hashlib.sha256(reviewed_yaml.encode()).hexdigest()[:12]
        branch = f"review/{digest}"
        namespace, name = self.repo_id.split("/", 1)
        try:
            self._request("GET", f"/datasets/{self.repo_id}")
        except HuggingFacePublishError as exc:
            if not self.create_repo or "not found" not in str(exc):
                raise
            self._request("POST", "/repos/create", {"name": name, "organization": namespace, "type": "dataset"})
        commit = self._request(
            "POST", f"/datasets/{self.repo_id}/commit/main?create_pr=true",
            {"summary": f"Add reviewed extraction {filename}",
             "description": "Reviewed YAML dataset artifact.",
             "files": [{"path": filename, "content": reviewed_yaml, "encoding": "utf-8"}]},
        )
        if not isinstance(commit, Mapping):
            raise HuggingFacePublishError("Hugging Face API returned invalid pull request metadata")
        url = commit.get("pr_url") or commit.get("pull_request_url") or commit.get("url") or commit.get("html_url")
        if not isinstance(url, str) or not url:
            pr_number = commit.get("pr_number") or commit.get("pullRequestNumber")
            if pr_number:
                url = f"https://huggingface.co/datasets/{self.repo_id}/discussions/{pr_number}"
        if not isinstance(url, str) or not url:
            raise HuggingFacePublishError("Hugging Face API did not return pull request metadata")
        commit_url = commit.get("commit_url") or commit.get("commitUrl")
        return PublishResult(self.repo_id, "main", filename, "pull_request_created", url,
                             commit_url if isinstance(commit_url, str) else None)


__all__ = ["DEFAULT_REPO_ID", "HuggingFacePublishError", "HuggingFacePublisher", "PublishResult"]
