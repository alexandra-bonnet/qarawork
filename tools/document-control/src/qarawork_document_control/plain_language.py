"""Human-readable QARA-facing summaries, separate from machine-verification fields.

These labels are *observations and recommended review actions*. They never
represent real human approval, electronic signing, release or use authorization.
"""
from __future__ import annotations


def summarize_register_record(record: dict) -> dict:
    """Explain a Notion/status metadata assessment without certifying approval."""
    status = record.get("status")
    errors = record.get("errors", [])
    warnings = record.get("warnings", [])
    if status == "Draft":
        label = "Draft"
        finding = "This revision is recorded as a draft, not as approved."
        next_action = "Continue drafting and submit it for human review when ready."
    elif status == "In Review":
        label = "In review"
        finding = "This revision is under review, not recorded as approved."
        next_action = (
            "Assign a reviewer and complete the human review process."
            if any("no assigned reviewer" in w.lower() for w in warnings)
            else "Complete the human review process before relying on the revision."
        )
    elif status == "Obsolete":
        label = "Obsolete"
        finding = "This revision is marked obsolete in the register."
        next_action = "Find the applicable replacement through your controlled document process."
    elif status == "Approved":
        label = "Approved in register, evidence not established" if errors else "Approved in register"
        finding = (
            "Notion records this revision as Approved, but this check does not authenticate "
            "the person or establish that the referenced content was validly approved."
        )
        next_action = (
            "Review the listed metadata/evidence gaps and obtain independent approval evidence."
            if errors else
            "Verify the exact controlled content and approval authority before using this revision."
        )
    else:
        label = "Status needs review"
        finding = "The register does not contain a recognized document status."
        next_action = "Correct the document's status and review its required metadata."

    return {
        "label": label,
        "finding": finding,
        "next_action": next_action,
        "human_approval_verified": False,
        "authorized_for_use": False,
    }


def summarize_source_file_result(result: dict) -> dict:
    """Explain exact-file comparison without conflating it with human approval."""
    match = result.get("matched_revision_count") == 1
    errors = result.get("errors", [])
    if not match:
        label = "Document record needs review"
        finding = "The requested revision could not be uniquely matched to the Notion register."
        next_action = "Check the document ID and revision and resolve missing or duplicate register rows."
    elif any("Exact document bytes differ from signed SHA-256 fingerprint." in str(error) for error in errors):
        label = "File does not match recorded reference"
        finding = (
            "The file read by the MCP does not pass the checks for the recorded "
            "version. The previous technical reference cannot support this file."
        )
        next_action = (
            "Do not rely on the old approval reference for this file. Investigate the "
            "change and follow the document review and reapproval process if the change is intended."
        )
    elif errors or not result.get("notion_metadata_matches_signed_snapshot"):
        label = "Approval evidence needs review"
        finding = "The file or register evidence is incomplete or inconsistent."
        next_action = "Investigate the reported errors before relying on the recorded revision."
    else:
        label = "File matches recorded reference"
        finding = (
            "The server-read file matches the configured signed technical reference "
            "and the Notion register metadata."
        )
        next_action = (
            "Confirm human approval authority, controlled source and current applicability "
            "under your organization's procedures before use."
        )
    return {
        "label": label,
        "finding": finding,
        "next_action": next_action,
        "human_approval_verified": False,
        "authorized_for_use": False,
    }
