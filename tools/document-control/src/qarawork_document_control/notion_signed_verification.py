"""Combine live Notion register metadata with independently supplied signed bytes.

This function does not fetch the actual contents of Notion pages. Its result
explicitly separates signed-snapshot verification from source-content integrity.
"""
from __future__ import annotations

from datetime import date
from .signed_evidence import verify_signed_evidence


def verify_notion_revision_bundle(
    records: list[dict], document_id: str, revision: str, content: bytes,
    signed_evidence: dict, trust_store: dict, *, on_date: date | None = None,
) -> dict:
    """Inspect exactly one Notion register row against external evidence.

    An external payload cannot prove that the Notion page body or attached
    files match the signed snapshot. Never assert the current official version
    or authenticated human approval from this routine.
    """
    result = {
        "document_id": document_id,
        "revision": revision,
        "source": "notion_register",
        "read_only": True,
        "matched_revision_count": 0,
        "signed_snapshot_verified": False,
        "notion_metadata_matches_signed_snapshot": False,
        "notion_page_content_verified": False,
        "verified_as_current_document": False,
        "errors": [],
        "warnings": [
            "Notion page body and attachments are NOT read or compared to the signed bytes.",
            "Caller-supplied snapshot provenance and signer identity are NOT established.",
            "This result is not an authenticated approval, current-version authorization or regulatory conformity claim.",
        ],
    }
    if not isinstance(document_id, str) or not document_id.strip() or not isinstance(revision, str) or not revision.strip():
        result["errors"].append("Nonempty document ID and revision are required.")
        return result
    matches = [r for r in records if r.get("document_id") == document_id and r.get("revision") == revision]
    result["matched_revision_count"] = len(matches)
    if len(matches) != 1:
        result["errors"].append(
            "Expected exactly one matching Notion revision, found %d." % len(matches)
        )
        return result

    row = matches[0]
    result["recorded_status"] = row.get("status")
    result["notion_page_id"] = row.get("notion_page_id")
    result["notion_url"] = row.get("notion_url")
    if not isinstance(row.get("title"), str) or not row["title"].strip():
        result["errors"].append("Notion document title is missing.")
    if not isinstance(row.get("owner"), str) or not row["owner"].strip():
        result["errors"].append("Notion document owner is missing.")

    signed = verify_signed_evidence(
        row, content, signed_evidence, trust_store, on_date=on_date,
    )
    result["cryptographic_checks_passed"] = signed["cryptographic_checks_passed"]
    result["signed_snapshot_verified"] = signed["eligible_as_current_under_prototype_rules"]
    result["errors"].extend(signed["errors"])
    result["notion_metadata_matches_signed_snapshot"] = bool(
        signed["eligible_as_current_under_prototype_rules"] and not result["errors"]
    )
    result["verification_scope"] = "Notion REGISTER METADATA vs independently supplied signed snapshot"
    result["key_id"] = signed_evidence.get("key_id") if isinstance(signed_evidence, dict) else None
    return result
