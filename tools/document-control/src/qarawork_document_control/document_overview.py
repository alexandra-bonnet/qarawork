"""One plain-language QARA overview, preserving separate verification boundaries.

This is a reporting layer. No approval, current-version authorization,
signature of a real individual, content write, or Part 11 claim is made.
"""
from __future__ import annotations


def make_document_overview(
    recorded_status: str | None, *, file_result: dict | None = None,
    register_errors: list[str] | None = None,
) -> dict:
    """Explain record status, file integrity, and human approval independently."""
    known_statuses = {"Draft", "In Review", "Approved", "Obsolete"}
    status = recorded_status if recorded_status in known_statuses else "Unknown"
    if file_result is None:
        integrity = "Not checked"
        integrity_detail = (
            "This register-only check did not read or verify the document file."
        )
    else:
        errors = file_result.get("errors", [])
        if file_result.get("matched_revision_count") != 1:
            integrity = "Not verified"
            integrity_detail = "The register revision is missing or ambiguous."
        elif any(
            "Exact document bytes differ from signed SHA-256 fingerprint." in str(e)
            for e in errors
        ):
            integrity = "Mismatch"
            integrity_detail = (
                "The stored file differs from the signed technical reference. "
                "The existing reference does not cover these bytes."
            )
        elif (
            file_result.get("source_file_matches_signed_fingerprint") is True
            and file_result.get("notion_metadata_matches_signed_snapshot") is True
            and not errors
        ):
            integrity = "Matches recorded reference"
            integrity_detail = (
                "The server-read local file matches the technical reference and "
                "Notion register metadata. The Notion page body was not checked."
            )
        else:
            integrity = "Not verified"
            integrity_detail = (
                "The file and reference could not be verified consistently. "
                "Investigate the reported technical errors."
            )

    if status == "In Review":
        action = "Complete the human review before treating the revision as approved."
    elif status == "Draft":
        action = "Finish the draft and submit it for human review when ready."
    elif status == "Obsolete":
        action = "Identify the applicable replacement under your document process."
    elif status == "Unknown":
        action = "Correct or verify the status recorded in the register."
    elif integrity == "Mismatch":
        action = (
            "Investigate the file change. Do not rely on the previous technical "
            "reference for this file; follow review and reapproval procedures as needed."
        )
    elif register_errors and any(
        "no named human approver" in str(e).lower()
        or "predates approval" in str(e).lower()
        for e in register_errors
    ):
        action = "Correct approval-record gaps and obtain the required human review."
    elif integrity == "Matches recorded reference":
        action = (
            "Confirm authentic human approval, authority and current applicability "
            "before authorizing use."
        )
    else:
        action = (
            "Obtain and check independent approval evidence and the controlled "
            "document version before use."
        )

    return {
        "recorded_status": status,
        "file_integrity": integrity,
        "file_integrity_detail": integrity_detail,
        "human_approval": "Not verified",
        "human_approval_verified": False,
        "authorized_for_use": False,
        "next_action": action,
        "scope_note": (
            "This prototype reads Notion register metadata. It does not verify "
            "Notion page body or attachments, authenticate human approval, or "
            "authorize the revision for official use."
        ),
    }
