from scientific_extraction_harness.adapters.llm import LLMAdapter


class Doc:
    document_id = "paper-1"
    sha256 = "abc"


def test_disabled_by_default_and_fail_closed():
    calls = []
    result = LLMAdapter(lambda request: calls.append(request)).extract(Doc(), config={})
    assert result.abstained and result.diagnostics[0].code == "external-calls-disabled"
    assert not calls


def test_opt_in_request_is_deterministic_and_candidates_only():
    seen = []

    def transport(request):
        seen.append(request)
        return {"candidates": [{"page": 2, "modality": "table", "locator": "table:1/row:2", "field": "yield", "value": "4", "unit": "%", "confidence": .8}]}

    config = {"external_calls": True, "explicit_opt_in": True, "credential": "secret", "model": "m", "prompt": "extract", "run_metadata": {"run_id": "r"}}
    result = LLMAdapter(transport).extract(Doc(), config=config)
    assert len(result.candidates) == 1
    assert result.candidates[0].status == "candidate"
    assert seen[0]["prompt"] == "extract"
    assert "prompt_sha256" in seen[0]
    assert seen[0]["prompt_hash_basis"] == "original"
    assert "credential" not in seen[0]["config"]
    assert seen[0]["retry"] is False


def test_transport_prompt_and_metadata_are_redacted_but_ordinary_text_preserved():
    seen = []

    def transport(request):
        seen.append(request)
        return {"candidates": [{"page": 1, "modality": "text", "locator": "page:1", "field": "x", "value": "1", "confidence": 1.0}]}

    prompt = "Extract yield from the source. email alice@example.com token=tok-123 password:pw authorization: Bearer abc"
    config = {
        "external_calls": True,
        "explicit_opt_in": True,
        "credential": "super-secret",
        "model": "m",
        "prompt": prompt,
        "run_metadata": {"owner": "bob@example.com", "nested": {"api_key": "nested-secret", "note": "keep this"}},
        "extra": {"password": "config-secret", "ordinary": "safe"},
    }
    result = LLMAdapter(transport).extract(Doc(), config=config)
    assert not result.abstained
    envelope = seen[0]
    serialized = repr(envelope)
    for secret in ("alice@example.com", "tok-123", "pw", "super-secret", "bob@example.com", "nested-secret", "config-secret"):
        assert secret not in serialized
    assert "Extract yield from the source." in envelope["prompt"]
    assert "[REDACTED_EMAIL]" in envelope["prompt"]
    assert "[REDACTED]" in envelope["prompt"]
    assert envelope["run_metadata"]["nested"]["api_key"] == "[REDACTED]"
    assert envelope["config"]["extra"]["password"] == "[REDACTED]"


def test_malformed_response_abstains_without_source_text():
    result = LLMAdapter(lambda _: {"candidates": [{"page": 1}]}).extract(
        Doc(), config={"external_calls": True, "explicit_opt_in": True, "credential": "x", "model": "m", "prompt": "private source"}
    )
    assert result.abstained
    assert result.diagnostics[0].code == "malformed-response"
    assert "private source" not in result.diagnostics[0].message


def test_env_credentials_require_explicit_allowlist():
    result = LLMAdapter(lambda _: []).extract(
        Doc(), config={"external_calls": True, "explicit_opt_in": True, "credential_env": "MISSING", "model": "m", "prompt": "p"}
    )
    assert result.diagnostics[0].code == "credentials-missing"
