from __future__ import annotations

import json
import pytest
from scientific_extraction_harness.hf_dataset import HuggingFacePublishError, HuggingFacePublisher


class Response:
    def __init__(self, value):
        self.value = value

    def read(self):
        return json.dumps(self.value).encode()


def test_token_required(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
    with pytest.raises(HuggingFacePublishError, match="token"):
        HuggingFacePublisher()


def test_current_commit_pr_request_and_metadata_without_token_leakage():
    calls = []

    def transport(request, timeout=0):
        calls.append(request)
        assert request.get_header("Authorization") == "Bearer secret"
        if request.full_url.endswith("/api/datasets/org/repo"):
            return Response({})
        assert request.full_url == "https://hf/api/datasets/org/repo/commit/main?create_pr=true"
        payload = json.loads(request.data)
        assert set(payload) == {"summary", "description", "files"}
        assert payload["files"] == [{"path": "a" * 64 + ".yaml", "content": "review: true\n", "encoding": "utf-8"}]
        return Response({"pr_url": "https://hf/pr/1", "commit_url": "https://hf/commit/1"})

    result = HuggingFacePublisher(token="secret", repo_id="org/repo", transport=transport, api_base="https://hf/api").publish(
        "review: true\n", article_hash="a" * 64
    )
    assert result.pull_request_url == "https://hf/pr/1"
    assert result.commit_url == "https://hf/commit/1"
    assert result.status == "pull_request_created"
    assert result.branch == "main"
    assert all("secret" not in str(c.data) for c in calls)
    assert "secret" not in str(result.to_dict())


def test_create_repo_uses_namespace_and_dataset_type():
    calls = []

    class NotFound(Exception):
        code = 404

    def transport(request, timeout=0):
        calls.append(request)
        if request.full_url.endswith("/datasets/org/repo"):
            from urllib.error import HTTPError
            raise HTTPError(request.full_url, 404, "missing", {}, None)
        if request.full_url.endswith("/repos/create"):
            assert json.loads(request.data) == {"name": "repo", "organization": "org", "type": "dataset"}
            return Response({})
        return Response({"url": "https://hf/pr/2"})

    result = HuggingFacePublisher(token="x", repo_id="org/repo", create_repo=True, transport=transport, api_base="https://hf/api").publish(
        "review: true\n", document_id="paper-7"
    )
    assert result.pull_request_url == "https://hf/pr/2"


def test_invalid_repo_filename_and_pdf_fail_closed():
    with pytest.raises(HuggingFacePublishError):
        HuggingFacePublisher(token="x", repo_id="bad")
    publisher = HuggingFacePublisher(token="x", repo_id="org/repo", transport=lambda *a, **k: Response({}))
    with pytest.raises(HuggingFacePublishError):
        publisher.publish("x", document_id="../escape")
    with pytest.raises(HuggingFacePublishError, match="PDF"):
        publisher.publish("%PDF-raw bytes", document_id="paper")
