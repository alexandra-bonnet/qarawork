"""Synthetic and reproducible Document Control test cases."""
from datetime import date

from qarawork_document_control.assessment import (
    assess_document, assess_document_register, sha256_bytes,
)

TODAY = date(2026, 10, 26)
DIGEST = sha256_bytes(b"Synthetic approved SOP revision one")


def approved():
    doc = {
        "document_id": "SOP-001",
        "title": "Synthetic document control procedure",
        "owner": "Quality manager",
        "revision": "1.0",
        "status": "Approved",
        "approved_by": "Human QARA reviewer",
        "approved_at": "2026-10-24",
        "effective_date": "2026-10-25",
        "content_sha256": DIGEST,
    }
    return doc


def baseline(record):
    return {
        "document_id": record["document_id"],
        "revision": record["revision"],
        "content_sha256": record["content_sha256"],
    }


def test_approved_revision_with_matching_independent_baseline():
    doc = approved()
    result = assess_document(doc, baseline=baseline(doc), on_date=TODAY)
    assert result["conformant_to_checked_rules"]
    assert result["eligible_as_current"]


def test_approved_revision_fails_closed_without_baseline():
    result = assess_document(approved(), on_date=TODAY)
    assert not result["eligible_as_current"]
    assert any("baseline is unavailable" in e for e in result["errors"])


def test_modified_content_fingerprint_invalidates_approval():
    doc = approved()
    original = baseline(doc)
    doc["content_sha256"] = sha256_bytes(b"Modified revision")
    result = assess_document(doc, baseline=original, on_date=TODAY)
    assert not result["eligible_as_current"]
    assert any("differs" in e for e in result["errors"])


def test_approved_without_human_approver_is_not_current():
    doc = approved()
    doc["approved_by"] = ""
    result = assess_document(doc, baseline=baseline(doc), on_date=TODAY)
    assert not result["eligible_as_current"]


def test_future_effective_revision_not_current():
    doc = approved()
    doc["effective_date"] = "2026-11-01"
    result = assess_document(doc, baseline=baseline(doc), on_date=TODAY)
    assert result["conformant_to_checked_rules"]
    assert not result["eligible_as_current"]


def test_invalid_approval_dates_rejected():
    doc = approved()
    doc["approved_at"] = "2026-10-27"
    result = assess_document(doc, baseline=baseline(doc), on_date=TODAY)
    assert any("future" in e for e in result["errors"])
    doc["approved_at"] = "2026-10-25"
    doc["effective_date"] = "2026-10-24"
    result = assess_document(doc, baseline=baseline(doc), on_date=TODAY)
    assert any("predates" in e for e in result["errors"])


def test_draft_never_eligible_as_current():
    doc = approved()
    doc["status"] = "Draft"
    result = assess_document(doc, on_date=TODAY)
    assert not result["eligible_as_current"]


def test_duplicate_revision_detection():
    doc = approved()
    report = assess_document_register([doc, dict(doc)], baselines={
        ("SOP-001", "1.0"): baseline(doc)
    }, on_date=TODAY)
    assert not report["allowed_to_select_current"]
    assert report["error_count"] >= 1


def test_competing_approved_versions_rejected():
    doc = approved()
    v2 = dict(doc, revision="2.0")
    report = assess_document_register([doc, v2], baselines={
        ("SOP-001", "1.0"): baseline(doc),
        ("SOP-001", "2.0"): baseline(v2),
    }, on_date=TODAY)
    assert not report["allowed_to_select_current"]
    assert all(not x["eligible_as_current"] for x in report["records"])


def test_does_not_modify_input():
    doc = approved()
    snap = dict(doc)
    assess_document(doc, baseline=baseline(doc), on_date=TODAY)
    assert doc == snap
