"""Synthetic cryptographic tests; never use these fixture keys for real approval."""
import base64
import copy
import json
from datetime import date

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from qarawork_document_control.signed_evidence import (
    canonical_statement, verify_signed_evidence,
)
from qarawork_document_control.server import verify_signed_document_approval, mcp

TODAY = date(2026, 10, 26)
CONTENT = b"Synthetic QARAWORK SOP-002 revision 1.0\nNo regulated use.\n"
SEED = bytes(range(32))  # public test-only fixture; no security value.


def fixture():
    from hashlib import sha256
    private = Ed25519PrivateKey.from_private_bytes(SEED)
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    document = {
        "document_id": "SOP-002", "title": "Synthetic approved SOP",
        "owner": "Quality", "revision": "1.0", "status": "Approved",
        "approved_by": "Fictional Reviewer",
        "approved_at": "2026-10-24", "effective_date": "2026-10-25",
        "content_sha256": sha256(CONTENT).hexdigest(),
    }
    statement = {
        "schema_version": "qarawork-approval-v1", "decision": "Approved",
        **{name: document[name] for name in (
            "document_id", "revision", "content_sha256", "approved_by",
            "approved_at", "effective_date",
        )},
    }
    signed = base64.b64encode(private.sign(canonical_statement(statement))).decode()
    envelope = {"key_id": "synthetic-approver", "statement": statement, "signature_base64": signed}
    trust = {"keys": {"synthetic-approver": {
        "public_key_base64": base64.b64encode(public).decode(),
        "identity": "Fictional Reviewer", "role": "document_approver", "active": True,
    }}}
    return document, envelope, trust


def verify(doc=None, envelope=None, trust=None, content=CONTENT):
    d, e, t = fixture()
    return verify_signed_evidence(
        doc if doc is not None else d, content,
        envelope if envelope is not None else e,
        trust if trust is not None else t, on_date=TODAY,
    )


def test_positive_signed_exact_revision():
    result = verify()
    assert result["cryptographic_checks_passed"] is True
    assert result["eligible_as_current_under_prototype_rules"] is True
    assert not result["errors"]


def test_changed_bytes_fail():
    result = verify(content=CONTENT + b"altered")
    assert not result["eligible_as_current_under_prototype_rules"]
    assert any("bytes differ" in msg for msg in result["errors"])


def test_changed_signature_fail():
    _, env, _ = fixture()
    env["signature_base64"] = base64.b64encode(bytes(64)).decode()
    result = verify(envelope=env)
    assert not result["cryptographic_checks_passed"]
    assert not result["eligible_as_current_under_prototype_rules"]


def test_signer_does_not_match_mapped_identity():
    _, env, trust = fixture()
    trust["keys"]["synthetic-approver"]["identity"] = "Someone else"
    result = verify(envelope=env, trust=trust)
    assert not result["eligible_as_current_under_prototype_rules"]
    assert any("not the identity" in m for m in result["errors"])


def test_disabled_or_missing_key_blocks():
    _, _, trust = fixture()
    trust["keys"]["synthetic-approver"]["active"] = False
    assert not verify(trust=trust)["eligible_as_current_under_prototype_rules"]
    assert not verify(trust={"keys": {}})["eligible_as_current_under_prototype_rules"]


def test_document_approval_metadata_tampered():
    doc, _, _ = fixture()
    doc["approved_at"] = "2026-10-23"
    result = verify(doc=doc)
    assert not result["eligible_as_current_under_prototype_rules"]
    assert any("approved_at differs" in m for m in result["errors"])


def test_unsigned_extra_field_rejected():
    _, env, _ = fixture()
    env["statement"]["extra"] = "bypass"
    assert not verify(envelope=env)["eligible_as_current_under_prototype_rules"]


def test_future_effective_date_blocks():
    doc, env, _ = fixture()
    # The signed statement must still be consistent: use a valid new signature.
    priv = Ed25519PrivateKey.from_private_bytes(SEED)
    doc["effective_date"] = "2026-11-30"
    env["statement"]["effective_date"] = "2026-11-30"
    env["signature_base64"] = base64.b64encode(
        priv.sign(canonical_statement(env["statement"]))
    ).decode()
    result = verify(doc=doc, envelope=env)
    assert result["cryptographic_checks_passed"]
    assert not result["eligible_as_current_under_prototype_rules"]


def test_server_uses_configured_local_trust_store(tmp_path, monkeypatch):
    doc, env, trust = fixture()
    file = tmp_path / "trusted-keys.json"
    file.write_text(json.dumps(trust))
    monkeypatch.setenv("QARAWORK_DC_TRUST_STORE", str(file))
    result = verify_signed_document_approval(
        doc, base64.b64encode(CONTENT).decode(), env, "2026-10-26"
    )
    assert result["eligible_as_current_under_prototype_rules"]


def test_server_fails_without_trust_store(monkeypatch):
    doc, env, _ = fixture()
    monkeypatch.delenv("QARAWORK_DC_TRUST_STORE", raising=False)
    import pytest
    with pytest.raises(ValueError, match="TRUST_STORE"):
        verify_signed_document_approval(doc, base64.b64encode(CONTENT).decode(), env)


def test_signed_verification_mcp_registered():
    assert "verify_signed_document_approval" in mcp._tool_manager._tools
