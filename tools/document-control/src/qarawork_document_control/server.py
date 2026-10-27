"""Read-only MCP entrypoint for synthetic document-control assessments.

The client supplies document metadata and reference digests. This interface
does NOT authenticate approvals or baseline provenance and never writes data.
"""
from __future__ import annotations

from datetime import date
import base64
import binascii
import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .assessment import assess_document, assess_document_register, sha256_bytes
from .notion import read_notion_document_register
from .signed_evidence import verify_signed_evidence, MAX_BYTES
from .notion_signed_verification import verify_notion_revision_bundle
from .local_snapshot import read_local_signed_artifacts
from .plain_language import summarize_register_record, summarize_source_file_result
from .document_overview import make_document_overview
from .notion_content import read_notion_page_content
from .notion_page_baseline import read_page_baseline
import hashlib
import httpx

mcp = FastMCP("QARAWORK Document Control")


def _evaluation_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("on_date must be a valid ISO date (YYYY-MM-DD)") from exc
    if parsed.isoformat() != value:
        raise ValueError("on_date must use canonical YYYY-MM-DD format")
    return parsed


@mcp.tool()
def check_document_revision(
    document: dict, reference_baseline: dict | None = None,
    on_date: str | None = None,
) -> dict:
    """Check a document revision for metadata, lifecycle, and digest mismatches.

    Read-only. A caller-provided reference_baseline is comparison data, not
    proof of independent preservation, authentic approval, or identity.
    An absent reference for an Approved revision is reported as a blocker.
    No connection to Notion is made.

    Args:
        document: document_id, title, owner, revision, status and any relevant
            approved_by, approved_at, effective_date, content_sha256 fields.
        reference_baseline: optional separate document_id, revision, content_sha256.
        on_date: evaluation date YYYY-MM-DD, default server's local date.
    """
    return assess_document(document, baseline=reference_baseline,
                           on_date=_evaluation_date(on_date))


@mcp.tool()
def check_document_register(
    documents: list[dict], reference_baselines: list[dict] | None = None,
    on_date: str | None = None,
) -> dict:
    """Check a document register for missing evidence or conflicting revisions.

    Read-only. Each reference is matched by (document_id, revision).
    Duplicate or malformed references fail closed. References must be obtained
    from a separately trustworthy source for the results to carry evidentiary
    weight. No approval or platform access control is performed.

    Args:
        documents: list of document metadata records.
        reference_baselines: optional list of document_id, revision,
            content_sha256 mappings, supplied separately by the caller.
        on_date: evaluation date YYYY-MM-DD, default server's local date.
    """
    references: dict[tuple[str, str], dict] = {}
    for item in reference_baselines or []:
        if not isinstance(item, dict):
            raise ValueError("Each reference baseline must be an object.")
        key = (item.get("document_id"), item.get("revision"))
        if not all(isinstance(v, str) and v.strip() for v in key):
            raise ValueError("Reference baseline needs document_id and revision.")
        if key in references:
            raise ValueError("Duplicate reference baseline for the same revision.")
        references[key] = item
    return assess_document_register(documents, baselines=references,
                                    on_date=_evaluation_date(on_date))



@mcp.tool()
async def inspect_notion_document_register(
    notion_data_source_id: str, on_date: str | None = None,
    verify_page_content: bool = False,
) -> dict:
    """Read and check a Notion document register, without changing any Notion data.

    The integration must have read-content access to the specified data source.
    Requires NOTION_TOKEN in this MCP server process. The data source must
    match the documented QARAWORK schema. Records are checked fail-closed:
    no independently protected approved baseline is available from Notion,
    so Approved revisions are not certified eligible as current.

    Args:
        notion_data_source_id: Notion data-source UUID, not a database URL or ID.
        on_date: evaluation date YYYY-MM-DD; optional.
        verify_page_content: when true, read actual Notion page blocks and compare
            to separately provisioned page-content reference. Never signs or approves.
    """
    records = await read_notion_document_register(notion_data_source_id)
    report = assess_document_register(
        records, baselines={}, on_date=_evaluation_date(on_date)
    )
    report["source"] = "notion"
    report["notion_data_source_id"] = notion_data_source_id
    report["read_only"] = True
    report["documents_scanned"] = len(records)
    report["notice"] = (
        "Notion metadata is not independent approval or content-integrity evidence. "
        "No trusted external approved-revision baselines were supplied; "
        "Approved revisions are therefore not eligible as current."
    )
    for result, source in zip(report["records"], records):
        result["notion_page_id"] = source["notion_page_id"]
        result["notion_url"] = source["notion_url"]
        result["review_summary"] = summarize_register_record(result)
        result["document_overview"] = make_document_overview(
            result.get("status"), register_errors=result.get("errors")
        )
    if verify_page_content:
        baseline_root = os.getenv("QARAWORK_DC_NOTION_BASELINE_ROOT")
        for result, source in zip(report["records"], records):
            overview = result["document_overview"]
            check = {
                "status": "Not verified",
                "matches_captured_reference": False,
                "notion_page_body_checked": False,
                "human_approval_verified": False,
                "authorized_for_use": False,
            }
            try:
                reference = read_page_baseline(
                    baseline_root, source["document_id"], source["revision"],
                    source["notion_page_id"], notion_data_source_id,
                )
                if reference is None:
                    check["status"] = "Reference missing"
                    check["message"] = "No separately captured Notion page-content reference exists."
                else:
                    actual, notion_edited_at = await read_notion_page_content(
                        source["notion_page_id"]
                    )
                    current_digest = hashlib.sha256(actual).hexdigest()
                    matched = current_digest == reference
                    check.update({
                        "status": "Matches captured reference" if matched else "Changed since reference",
                        "matches_captured_reference": matched,
                        "notion_page_body_checked": True,
                        "notion_last_edited_at": notion_edited_at,
                        "current_content_sha256": current_digest,
                        "reference_content_sha256": reference,
                        "message": (
                            "Notion page text and structure match the captured demo reference."
                            if matched else
                            "Actual Notion page content differs from the captured reference. "
                            "Investigate the change and follow human review/reapproval procedures."
                        ),
                    })
            except (ValueError, OSError, httpx.HTTPError) as exc:
                check["status"] = "Not verified"
                check["message"] = "Cannot safely verify Notion page content: " + str(exc)
            result["notion_page_content_check"] = check
            overview["page_content_integrity"] = check["status"]
            overview["scope_note"] = (
                "The live Notion page body was read and compared with a separately "
                "captured local demo reference."
                if check["notion_page_body_checked"]
                else "The live Notion page body could not be verified against "
                "a separately captured local demo reference."
            ) + (
                " This check does not validate Notion attachments, authenticate "
                "human approval, establish an immutable approved baseline, "
                "or authorize the revision for official use."
            )
            if check["status"] == "Changed since reference":
                overview["next_action"] = (
                    "The actual Notion page changed since its captured reference. "
                    "Review the changes and arrange human reapproval before relying on this content."
                )
            elif check["status"] != "Matches captured reference":
                overview["next_action"] = (
                    "Establish or repair the separately controlled page-content reference "
                    "and complete human approval checks before use."
                )
            overview["human_approval"] = "Not verified"
            overview["human_approval_verified"] = False
            overview["authorized_for_use"] = False
    else:
        for result in report["records"]:
            result["document_overview"]["page_content_integrity"] = "Not checked"
    # Without any independently trusted baseline, this adapter never authorizes selection.
    report["allowed_to_select_current"] = False
    if not records:
        report["notice"] += " Empty register: no revision can be selected."
    return report



@mcp.tool()
def verify_signed_document_approval(
    document: dict, content_base64: str, signed_evidence: dict,
    on_date: str | None = None,
) -> dict:
    """Verify exact bytes against a detached Ed25519 approval statement.

    Experimental read-only positive test tool. Public keys are loaded ONLY
    from a local trust registry path provisioned through QARAWORK_DC_TRUST_STORE
    in this process's environment, never from MCP caller arguments or Notion.
    A successful verification is NOT proof of a real person's identity,
    qualified approval or ISO 13485 / eQMS compliance.

    Args:
        document: controlled revision metadata (document_id, revision, title,
            owner, status, approved_by, approved_at, effective_date,
            content_sha256).
        content_base64: exact document bytes encoded with base64, up to 2 MB.
        signed_evidence: detached envelope with key_id, statement and
            signature_base64. The statement covers the exact content digest.
        on_date: optional ISO calendar date YYYY-MM-DD.
    """
    path = os.getenv("QARAWORK_DC_TRUST_STORE")
    if not path or not Path(path).is_absolute():
        raise ValueError("QARAWORK_DC_TRUST_STORE must point to a local absolute trust-store path.")
    try:
        registry = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Cannot read an initialized local trust store.") from exc
    if not isinstance(content_base64, str) or len(content_base64) > (MAX_BYTES * 4 // 3 + 8):
        raise ValueError("Document content payload is missing or exceeds 2 MB.")
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Document content_base64 is invalid.") from exc
    if len(content) > MAX_BYTES:
        raise ValueError("Document bytes exceed the 2 MB prototype limit.")
    return verify_signed_evidence(
        document, content, signed_evidence, registry,
        on_date=_evaluation_date(on_date),
    )



@mcp.tool()
async def verify_notion_signed_revision(
    notion_data_source_id: str, document_id: str, revision: str,
    content_base64: str, signed_evidence: dict,
    on_date: str | None = None,
) -> dict:
    """Cross-check one Notion register revision with external signed snapshot.

    Read-only. The Notion REGISTER metadata is read via API and checked
    against independently supplied exact bytes, a detached Ed25519 signature
    and a local public-key registry set by the MCP administrator.
    THIS DOES NOT DOWNLOAD/VERIFY NOTION PAGE CONTENT OR ATTACHMENTS.
    A passing comparison must never be reported as a compliant approval,
    current official version, or integrity proof of the live Notion page.
    """
    date_value = _evaluation_date(on_date)
    if not isinstance(content_base64, str) or len(content_base64) > (MAX_BYTES * 4 // 3 + 8):
        raise ValueError("Document content payload is missing or exceeds 2 MB.")
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Document content_base64 is invalid.") from exc
    if len(content) > MAX_BYTES:
        raise ValueError("Document bytes exceed the 2 MB prototype limit.")
    trust_path = os.getenv("QARAWORK_DC_TRUST_STORE")
    if not trust_path or not Path(trust_path).is_absolute():
        raise ValueError("QARAWORK_DC_TRUST_STORE must point to an absolute local trust-store file.")
    try:
        trust_store = json.loads(Path(trust_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Cannot read an initialized local trust store.") from exc
    rows = await read_notion_document_register(notion_data_source_id)
    result = verify_notion_revision_bundle(
        rows, document_id, revision, content, signed_evidence, trust_store,
        on_date=date_value,
    )
    result["notion_data_source_id"] = notion_data_source_id
    result["documents_scanned"] = len(rows)
    return result



@mcp.tool()
async def verify_notion_source_file_integrity(
    notion_data_source_id: str, document_id: str, revision: str,
    on_date: str | None = None,
) -> dict:
    """Read server-selected original file bytes, verify Ed25519 and Notion row.

    The caller supplies ONLY a Notion data source, document ID, revision and
    optional evaluation date. No caller-supplied bytes, signature, file path
    or trust keys are accepted. Files are selected from the admin-configured
    QARAWORK_DC_SNAPSHOT_ROOT directory (demo .bin + .evidence.json sidecar).
    This does NOT check the body or attachments of the Notion page itself,
    and a local snapshot folder is not immutable regulated evidence storage.
    """
    date_value = _evaluation_date(on_date)
    content, envelope, artifact_name = read_local_signed_artifacts(
        os.getenv("QARAWORK_DC_SNAPSHOT_ROOT"), document_id, revision
    )
    trust_path = os.getenv("QARAWORK_DC_TRUST_STORE")
    if not trust_path or not Path(trust_path).is_absolute():
        raise ValueError("QARAWORK_DC_TRUST_STORE must point to a local absolute trust-store path.")
    try:
        trust_store = json.loads(Path(trust_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Cannot read an initialized local trust store.") from exc
    rows = await read_notion_document_register(notion_data_source_id)
    result = verify_notion_revision_bundle(
        rows, document_id, revision, content, envelope, trust_store,
        on_date=date_value,
    )
    result["notion_data_source_id"] = notion_data_source_id
    result["documents_scanned"] = len(rows)
    result["artifact_name"] = artifact_name + ".bin"
    result["file_bytes_read_by_server"] = len(content)
    statement = envelope.get("statement") if isinstance(envelope, dict) else None
    expected_digest = statement.get("content_sha256") if isinstance(statement, dict) else None
    result["source_file_matches_signed_fingerprint"] = bool(
        isinstance(expected_digest, str)
        and len(expected_digest) == 64
        and all(c in "0123456789abcdefABCDEF" for c in expected_digest)
        and sha256_bytes(content) == expected_digest.lower()
    )
    result["notion_page_content_verified"] = False
    result["verified_as_current_document"] = False
    result["verification_scope"] = (
        "SERVER-READ LOCAL FILE BYTES vs detached signature and Notion register metadata; "
        "NOT Notion page body or attachments"
    )
    result["warnings"].append(
        "Local source file/evidence storage is not proven immutable, independently preserved or validated."
    )
    result["review_summary"] = summarize_source_file_result(result)
    result["document_overview"] = make_document_overview(
        result.get("recorded_status"), file_result=result
    )
    return result


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
