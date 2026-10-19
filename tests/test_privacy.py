from pathlib import Path

import pytest

from scientific_extraction_harness.privacy import (
    AuditReceipt,
    ExternalCallDenied,
    LicenseTermsReceipt,
    PathPolicyError,
    PrivacyPolicy,
    TermsReceiptError,
    UnauthorizedInputError,
    gate_external_call,
    make_audit_receipt,
    redact_sensitive,
    validate_local_input,
)


def test_local_input_requires_authorization_and_containment(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "paper.pdf"
    source.write_bytes(b"fixture")
    policy = PrivacyPolicy(allowed_roots=(allowed,))
    assert validate_local_input(source, authorized=True, policy=policy) == source.resolve()
    with pytest.raises(UnauthorizedInputError):
        validate_local_input(source, authorized=False, policy=policy)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"fixture")
    with pytest.raises(PathPolicyError):
        validate_local_input(outside, authorized=True, policy=policy)


def test_external_calls_are_fail_closed_and_need_dual_opt_in():
    with pytest.raises(ExternalCallDenied):
        gate_external_call(adapter="remote", cli_acknowledged=True)
    policy = PrivacyPolicy(external_calls=True, external_adapters=frozenset({"remote"}))
    terms = LicenseTermsReceipt("remote", "1", "MIT", "model terms v1")
    with pytest.raises(ExternalCallDenied):
        gate_external_call(adapter="remote", policy=policy, terms_receipt=terms)
    payload, receipt = gate_external_call(
        adapter="remote", policy=policy, cli_acknowledged=True, terms_receipt=terms,
        payload={"prompt": "raw source", "api_token": "secret", "email": "person@example.org", "safe": 1},
    )
    assert payload["prompt"] == "[REDACTED]"
    assert payload["api_token"] == "[REDACTED]"
    assert payload["email"] == "[REDACTED]"
    assert payload["safe"] == 1
    assert receipt.as_dict()["redacted"] is True


def test_unknown_terms_are_rejected():
    policy = PrivacyPolicy(external_calls=True)
    with pytest.raises(TermsReceiptError):
        gate_external_call(adapter="optional", policy=policy, cli_acknowledged=True,
                           terms_receipt={"adapter": "optional", "version": "1", "license": "unknown", "model_terms": "v1"})


def test_redaction_is_recursive_and_receipts_are_metadata_only():
    value = redact_sensitive({"nested": ["person@example.com", "Bearer abc"], "raw_source": "text"})
    assert "person@example.com" not in repr(value)
    assert "abc" not in repr(value)
    assert value["raw_source"] == "[REDACTED]"
    receipt = make_audit_receipt(action="local", adapter="text", allowed=True, input_value=b"source", metadata={"token": "secret", "page": 2})
    assert isinstance(receipt, AuditReceipt)
    result = receipt.as_dict()
    assert result["input_sha256"]
    assert result["metadata"]["token"] == "[REDACTED]"
    assert "source" not in repr(result)
