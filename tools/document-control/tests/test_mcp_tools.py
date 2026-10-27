"""Integration-level tests of MCP tool wrappers, without external services."""
from datetime import date

import pytest

from qarawork_document_control.assessment import sha256_bytes
from qarawork_document_control.server import (
    check_document_register, check_document_revision, mcp,
)


def approved():
    return {
        "document_id": "SOP-001",
        "title": "Synthetic SOP",
        "owner": "Quality",
        "revision": "1.0",
        "status": "Approved",
        "approved_by": "Synthetic reviewer",
        "approved_at": "2026-10-24",
        "effective_date": "2026-10-25",
        "content_sha256": sha256_bytes(b"synthetic SOP"),
    }


def baseline(doc):
    return {key: doc[key] for key in ("document_id", "revision", "content_sha256")}


def test_two_mcp_tools_registered():
    assert {"check_document_revision", "check_document_register"}.issubset(
        set(mcp._tool_manager._tools)
    )


def test_check_revision_good_reference():
    doc = approved()
    response = check_document_revision(doc, baseline(doc), "2026-10-26")
    assert response["eligible_as_current"] is True


def test_check_revision_missing_reference_rejects():
    response = check_document_revision(approved(), on_date="2026-10-26")
    assert response["eligible_as_current"] is False
    assert any("baseline" in r for r in response["errors"])


def test_check_revision_invalid_date_rejects():
    with pytest.raises(ValueError):
        check_document_revision(approved(), on_date="not-a-date")


def test_check_register_matching_reference():
    doc = approved()
    result = check_document_register([doc], [baseline(doc)], "2026-10-26")
    assert result["allowed_to_select_current"] is True


def test_check_register_duplicate_references_rejected():
    doc = approved()
    with pytest.raises(ValueError, match="Duplicate"):
        check_document_register([doc], [baseline(doc), baseline(doc)])


def test_check_register_missing_reference_rejects():
    response = check_document_register([approved()], on_date="2026-10-26")
    assert response["allowed_to_select_current"] is False


def test_check_register_rejects_competing_versions():
    doc = approved()
    next_revision = dict(doc, revision="2.0")
    result = check_document_register(
        [doc, next_revision],
        [baseline(doc), baseline(next_revision)],
        "2026-10-26",
    )
    assert result["allowed_to_select_current"] is False
