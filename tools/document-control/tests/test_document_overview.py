"""Acceptance tests for one QARA-friendly status, including fail-closed cases."""
from qarawork_document_control.document_overview import make_document_overview


def test_register_only_approved_does_not_claim_file_verified():
    o = make_document_overview("Approved", register_errors=[
        "Independent approved revision baseline is unavailable."
    ])
    assert o["recorded_status"] == "Approved"
    assert o["file_integrity"] == "Not checked"
    assert o["human_approval"] == "Not verified"
    assert o["authorized_for_use"] is False


def test_in_review_is_clear_to_qara():
    o = make_document_overview("In Review")
    assert o["recorded_status"] == "In Review"
    assert o["file_integrity"] == "Not checked"
    assert "Complete the human review" in o["next_action"]


def test_clean_file_is_not_regulatory_approval():
    o = make_document_overview("Approved", file_result={
        "matched_revision_count": 1,
        "source_file_matches_signed_fingerprint": True,
        "notion_metadata_matches_signed_snapshot": True,
        "errors": [],
    })
    assert o["file_integrity"] == "Matches recorded reference"
    assert o["human_approval_verified"] is False
    assert o["authorized_for_use"] is False
    assert "human approval" in o["next_action"]


def test_one_byte_tamper_requires_review():
    o = make_document_overview("Approved", file_result={
        "matched_revision_count": 1,
        "source_file_matches_signed_fingerprint": False,
        "notion_metadata_matches_signed_snapshot": False,
        "errors": ["Exact document bytes differ from signed SHA-256 fingerprint."],
    })
    assert o["file_integrity"] == "Mismatch"
    assert "reapproval" in o["next_action"]
    assert o["authorized_for_use"] is False


def test_changed_approval_date_not_mislabeled_as_file_tamper():
    o = make_document_overview("Approved", file_result={
        "matched_revision_count": 1,
        "source_file_matches_signed_fingerprint": False,
        "notion_metadata_matches_signed_snapshot": False,
        "errors": ["Signed approved_at differs from the document record."],
    })
    assert o["file_integrity"] == "Not verified"


def test_missing_or_duplicate_revision_is_never_a_match():
    for n in (0, 2):
        o = make_document_overview("Unknown", file_result={
            "matched_revision_count": n,
            "source_file_matches_signed_fingerprint": True,
            "notion_metadata_matches_signed_snapshot": True,
            "errors": [],
        })
        assert o["file_integrity"] == "Not verified"


def test_obsolete_record_stays_unapproved():
    o = make_document_overview("Obsolete")
    assert o["recorded_status"] == "Obsolete"
    assert not o["authorized_for_use"]


def test_approved_with_inconsistent_dates_requests_correction():
    o = make_document_overview("Approved", register_errors=[
        "Effective date predates approval."
    ])
    assert "Correct approval-record gaps" in o["next_action"]
