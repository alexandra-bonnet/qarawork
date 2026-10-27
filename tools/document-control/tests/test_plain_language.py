"""QARA-facing explanatory labels are recommendations, not approvals."""
from qarawork_document_control.plain_language import (
    summarize_register_record, summarize_source_file_result,
)


def test_register_draft():
    r = summarize_register_record({"status": "Draft", "errors": [], "warnings": []})
    assert r["label"] == "Draft"
    assert not r["authorized_for_use"]


def test_register_in_review_without_reviewer():
    r = summarize_register_record({
        "status": "In Review", "errors": [],
        "warnings": ["Review record has no assigned reviewer."],
    })
    assert r["label"] == "In review"
    assert "Assign a reviewer" in r["next_action"]


def test_register_approved_without_independent_evidence():
    r = summarize_register_record({
        "status": "Approved",
        "errors": ["Independent approved revision baseline is unavailable."],
        "warnings": [],
    })
    assert r["label"] == "Approved in register, evidence not established"
    assert r["human_approval_verified"] is False
    assert r["authorized_for_use"] is False


def test_register_approved_even_with_clean_metadata_not_authentic():
    r = summarize_register_record({"status": "Approved", "errors": [], "warnings": []})
    assert r["label"] == "Approved in register"
    assert r["human_approval_verified"] is False
    assert r["authorized_for_use"] is False


def test_register_obsolete():
    r = summarize_register_record({"status": "Obsolete", "errors": [], "warnings": []})
    assert r["label"] == "Obsolete"
    assert "replacement" in r["next_action"]


def test_file_verification_positive_is_not_human_approval():
    r = summarize_source_file_result({
        "matched_revision_count": 1,
        "source_file_matches_signed_fingerprint": True,
        "notion_metadata_matches_signed_snapshot": True,
        "errors": [],
    })
    assert r["label"] == "File matches recorded reference"
    assert not r["human_approval_verified"]
    assert not r["authorized_for_use"]


def test_file_modified_one_byte_requires_investigation():
    r = summarize_source_file_result({
        "matched_revision_count": 1,
        "source_file_matches_signed_fingerprint": False,
        "notion_metadata_matches_signed_snapshot": False,
        "errors": [
            "Exact document bytes differ from signed SHA-256 fingerprint.",
            "Document metadata fingerprint differs from exact bytes.",
        ],
    })
    assert r["label"] == "File does not match recorded reference"
    assert "reapproval" in r["next_action"]
    assert not r["authorized_for_use"]


def test_metadata_mismatch_is_not_mislabeled_file_change():
    r = summarize_source_file_result({
        "matched_revision_count": 1,
        "source_file_matches_signed_fingerprint": False,
        "notion_metadata_matches_signed_snapshot": False,
        "errors": ["Signed approved_at differs from the document record."],
    })
    assert r["label"] == "Approval evidence needs review"


def test_duplicate_or_missing_notion_revision():
    for n in (0, 2):
        r = summarize_source_file_result({
            "matched_revision_count": n, "errors": ["Unexpected revision count."]
        })
        assert r["label"] == "Document record needs review"
        assert not r["authorized_for_use"]
