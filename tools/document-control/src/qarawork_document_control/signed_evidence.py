"""Experimental detached approval evidence verifier.

The trusted public-key registry MUST be provisioned separately from untrusted
document and evidence inputs. A valid Ed25519 signature only proves possession
of the corresponding private key, not human identity, consent, or QMS validation.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from datetime import date

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

FIELDS = (
    "schema_version", "decision", "document_id", "revision", "content_sha256",
    "approved_by", "approved_at", "effective_date",
)
SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
MAX_BYTES = 2_000_000


def canonical_statement(statement: dict) -> bytes:
    """Produce deterministic signed bytes using only V1 fields."""
    if not isinstance(statement, dict) or set(statement) != set(FIELDS):
        raise ValueError("Signed statement has missing or unexpected fields.")
    if any(not isinstance(statement[k], str) or not statement[k].strip() for k in FIELDS):
        raise ValueError("Signed statement has blank or non-string fields.")
    return json.dumps(statement, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _base64(value: object, expected_length: int | None = None) -> bytes:
    if not isinstance(value, str):
        raise ValueError("Encoded evidence is not base64 text.")
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Encoded evidence is not valid base64.") from exc
    if expected_length is not None and len(data) != expected_length:
        raise ValueError("Encoded evidence length is invalid.")
    return data


def _date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def verify_signed_evidence(
    document: dict, content: bytes, envelope: dict, trust_store: dict, *,
    on_date: date | None = None,
) -> dict:
    """Fail-closed V1 checks; caller must establish provenance of trust_store.

    Required trust_store:
      {"keys": {key_id: {"public_key_base64": "...", "identity": "...",
                          "role": "document_approver", "active": true}}}
    A valid signature proves only that the corresponding key signed the statement.
    No role, identity or authority is inferred from Notion fields alone.
    """
    errors: list[str] = []
    today = on_date or date.today()
    result = {
        "document_id": document.get("document_id") if isinstance(document, dict) else None,
        "revision": document.get("revision") if isinstance(document, dict) else None,
        "cryptographic_checks_passed": False,
        "eligible_as_current_under_prototype_rules": False,
        "errors": errors,
        "limitations": [
            "A trusted key mapping is a prerequisite, not proof of verified human identity.",
            "No electronic-signature, regulatory-conformity or validated-QMS claim.",
            "No revocation, trusted timestamp, key rotation or durable audit trail implemented.",
        ],
    }
    if not isinstance(document, dict) or not isinstance(envelope, dict) or not isinstance(trust_store, dict):
        errors.append("Document, evidence and trust store must be objects.")
        return result
    if not isinstance(content, bytes) or len(content) > MAX_BYTES:
        errors.append("Document content must be exact bytes of no more than 2 MB.")
        return result
    if set(envelope) != {"key_id", "statement", "signature_base64"}:
        errors.append("Evidence envelope must contain exactly key_id, statement and signature_base64.")
        return result
    statement = envelope["statement"]
    try:
        signed = canonical_statement(statement)
    except ValueError as exc:
        errors.append(str(exc))
        return result
    if statement["schema_version"] != "qarawork-approval-v1" or statement["decision"] != "Approved":
        errors.append("Unsupported approval statement or decision.")
    key_id = envelope.get("key_id")
    keys = trust_store.get("keys")
    key = keys.get(key_id) if isinstance(keys, dict) and isinstance(key_id, str) else None
    if not isinstance(key, dict) or key.get("active") is not True or key.get("role") != "document_approver":
        errors.append("Signing key is not present as an active, authorized document approver.")
    elif not isinstance(key.get("identity"), str) or not key["identity"].strip():
        errors.append("Signing key lacks a configured human identity mapping.")
    else:
        try:
            public = Ed25519PublicKey.from_public_bytes(_base64(key.get("public_key_base64"), 32))
            public.verify(_base64(envelope.get("signature_base64"), 64), signed)
            result["cryptographic_checks_passed"] = True
        except (ValueError, InvalidSignature) as exc:
            errors.append("Detached Ed25519 signature verification failed.")
    if statement["document_id"] != document.get("document_id") or statement["revision"] != document.get("revision"):
        errors.append("Signed document ID or revision does not match the record.")
    if statement["approved_by"] != document.get("approved_by"):
        errors.append("Signed approver does not match the document record.")
    if isinstance(key, dict) and statement["approved_by"] != key.get("identity"):
        errors.append("Signed approver is not the identity authorized for the signing key.")
    for field in ("approved_at", "effective_date"):
        if statement[field] != document.get(field):
            errors.append(f"Signed {field} differs from the document record.")
    if document.get("status") != "Approved":
        errors.append("Document status is not Approved.")
    digest = hashlib.sha256(content).hexdigest()
    if not SHA256.fullmatch(statement["content_sha256"]):
        errors.append("Signed SHA-256 fingerprint has invalid syntax.")
    elif statement["content_sha256"].lower() != digest:
        errors.append("Exact document bytes differ from signed SHA-256 fingerprint.")
    if not isinstance(document.get("content_sha256"), str) or document["content_sha256"].lower() != digest:
        errors.append("Document metadata fingerprint differs from exact bytes.")
    approved_at = _date(statement["approved_at"])
    effective = _date(statement["effective_date"])
    if approved_at is None or effective is None:
        errors.append("Approval or effective date is invalid.")
    else:
        if approved_at > effective:
            errors.append("Effective date predates approval.")
        if approved_at > today:
            errors.append("Approval date is in the future.")
        if effective > today:
            errors.append("Revision is approved but not yet effective.")
    result["eligible_as_current_under_prototype_rules"] = bool(
        result["cryptographic_checks_passed"] and not errors
    )
    return result
