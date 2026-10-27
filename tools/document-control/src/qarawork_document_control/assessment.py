"""Pure, fail-closed document revision assessments.

This package does not approve records, enforce permissions, sign documents,
maintain an audit trail, or provide compliant record retention. A caller must
obtain approval data and integrity baselines from independently trusted sources.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date

ALLOWED_STATUSES = frozenset({"Draft", "In Review", "Approved", "Obsolete"})
SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")


def _date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        result = date.fromisoformat(value)
    except ValueError:
        return None
    return result if result.isoformat() == value else None


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def assess_document(record: dict, *, baseline: dict | None = None,
                    on_date: date | None = None) -> dict:
    """Report evidence and lifecycle gaps without mutating the input.

    baseline must be independently obtained and trust-verified by the caller;
    accepting an arbitrary baseline is not an integrity guarantee.
    """
    if not isinstance(record, dict):
        raise TypeError("record must be a dictionary")
    today = on_date or date.today()
    errors: list[str] = []
    warnings: list[str] = []
    status = record.get("status")
    doc_id = record.get("document_id")
    revision = record.get("revision")

    for field in ("document_id", "revision", "title", "owner"):
        if not _nonempty(record.get(field)):
            errors.append(f"{field} is missing.")
    if status not in ALLOWED_STATUSES:
        errors.append("status must be Draft, In Review, Approved, or Obsolete.")

    approved = status == "Approved"
    if approved:
        if not _nonempty(record.get("approved_by")):
            errors.append("Approved revision has no named human approver.")
        approval_date = _date(record.get("approved_at"))
        effective_date = _date(record.get("effective_date"))
        if approval_date is None:
            errors.append("Approved revision has no valid approval date.")
        if effective_date is None:
            errors.append("Approved revision has no valid effective date.")
        if approval_date is not None and effective_date is not None and approval_date > effective_date:
            errors.append("Effective date predates approval.")
        if approval_date is not None and approval_date > today:
            errors.append("Approval date is in the future.")
        digest = record.get("content_sha256")
        if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
            errors.append("Approved revision has no valid SHA-256 content fingerprint.")
        if not isinstance(baseline, dict):
            errors.append("Independent approved revision baseline is unavailable.")
        else:
            if baseline.get("document_id") != doc_id or baseline.get("revision") != revision:
                errors.append("Approved baseline does not identify this document revision.")
            trusted_digest = baseline.get("content_sha256")
            if not isinstance(trusted_digest, str) or not SHA256_PATTERN.fullmatch(trusted_digest):
                errors.append("Approved baseline fingerprint is invalid.")
            elif not isinstance(digest, str) or trusted_digest.lower() != digest.lower():
                errors.append("Document fingerprint differs from approved baseline.")
        if effective_date is not None and effective_date > today:
            warnings.append("Approved revision is not yet effective.")
    elif status == "In Review":
        if not _nonempty(record.get("reviewer")):
            warnings.append("Review record has no assigned reviewer.")

    applicable = approved and not errors and _date(record.get("effective_date")) <= today
    return {
        "document_id": doc_id,
        "revision": revision,
        "status": status,
        "eligible_as_current": bool(applicable),
        "conformant_to_checked_rules": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def assess_document_register(records: list[dict], *,
                             baselines: dict[tuple[str, str], dict] | None = None,
                             on_date: date | None = None) -> dict:
    """Assess revisions and reject ambiguous or duplicate applicable baselines.

    baselines keys are (document_id, revision). This routine never infers that
    the baseline store is tamper-proof or that the evidence is authentic.
    """
    if not isinstance(records, list):
        raise TypeError("records must be a list")
    baselines = baselines or {}
    if not isinstance(baselines, dict):
        raise TypeError("baselines must be a mapping")
    results = []
    seen: set[tuple[str, str]] = set()
    current_by_document: dict[str, list[int]] = {}
    for rec in records:
        if not isinstance(rec, dict):
            raise TypeError("all records must be dictionaries")
        key = (rec.get("document_id"), rec.get("revision"))
        baseline = baselines.get(key) if all(isinstance(v, str) for v in key) else None
        result = assess_document(rec, baseline=baseline, on_date=on_date)
        if key in seen:
            result["errors"].append("Duplicate document ID and revision.")
        seen.add(key)
        if result["eligible_as_current"]:
            current_by_document.setdefault(str(key[0]), []).append(len(results))
        results.append(result)
    for _, indexes in current_by_document.items():
        if len(indexes) > 1:
            for idx in indexes:
                results[idx]["errors"].append("Multiple approved effective revisions exist for this document.")
    for result in results:
        result["conformant_to_checked_rules"] = not result["errors"]
        result["eligible_as_current"] = bool(result["eligible_as_current"] and not result["errors"])
    return {
        "allowed_to_select_current": all(not r["errors"] for r in results)
        and all(len(ix) <= 1 for ix in current_by_document.values()),
        "records": results,
        "error_count": sum(len(r["errors"]) for r in results),
    }


def sha256_bytes(content: bytes) -> str:
    """Utility for hashing exact bytes; no claims of signature or source authenticity."""
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    return hashlib.sha256(content).hexdigest()
