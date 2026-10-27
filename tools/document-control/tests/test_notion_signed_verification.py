"""Synthetic integration tests: Notion API is always mocked, no live writes."""
import base64
import json

import pytest

from test_signed_evidence import CONTENT, fixture
from qarawork_document_control.notion_signed_verification import verify_notion_revision_bundle
from qarawork_document_control.server import verify_notion_signed_revision, mcp

DS_ID = "12345678-1234-1234-1234-123456789abc"


def row(document):
    return {
        **document,
        "notion_page_id": "synthetic-id",
        "notion_url": "https://www.notion.so/synthetic-page",
    }


def test_exact_signed_snapshot_matches_notion_register_metadata():
    doc, envelope, trust = fixture()
    report = verify_notion_revision_bundle(
        [row(doc)], "SOP-002", "1.0", CONTENT, envelope, trust
    )
    assert report["cryptographic_checks_passed"]
    assert report["signed_snapshot_verified"]
    assert report["notion_metadata_matches_signed_snapshot"]
    assert report["notion_page_content_verified"] is False
    assert report["verified_as_current_document"] is False
    assert not report["errors"]


def test_changed_snapshot_bytes_rejected():
    doc, envelope, trust = fixture()
    report = verify_notion_revision_bundle(
        [row(doc)], "SOP-002", "1.0", CONTENT + b"!", envelope, trust
    )
    assert report["cryptographic_checks_passed"]
    assert not report["notion_metadata_matches_signed_snapshot"]
    assert any("bytes differ" in error for error in report["errors"])


def test_changed_notion_approval_metadata_rejected():
    doc, envelope, trust = fixture()
    modified = row(doc)
    modified["approved_at"] = "2026-10-23"
    report = verify_notion_revision_bundle(
        [modified], "SOP-002", "1.0", CONTENT, envelope, trust
    )
    assert report["cryptographic_checks_passed"]
    assert not report["notion_metadata_matches_signed_snapshot"]
    assert any("approved_at differs" in error for error in report["errors"])


@pytest.mark.parametrize("records", [[], [dict(document_id="other", revision="1.0")]])
def test_no_matching_revision_rejected(records):
    _, envelope, trust = fixture()
    report = verify_notion_revision_bundle(
        records, "SOP-002", "1.0", CONTENT, envelope, trust
    )
    assert report["matched_revision_count"] == 0
    assert report["errors"]
    assert report["notion_metadata_matches_signed_snapshot"] is False


def test_duplicate_revision_rejected():
    doc, envelope, trust = fixture()
    report = verify_notion_revision_bundle(
        [row(doc), row(doc)], "SOP-002", "1.0", CONTENT, envelope, trust
    )
    assert report["matched_revision_count"] == 2
    assert report["errors"]
    assert report["notion_metadata_matches_signed_snapshot"] is False


def test_missing_notion_owner_rejected():
    doc, envelope, trust = fixture()
    modified = row(doc)
    modified["owner"] = ""
    report = verify_notion_revision_bundle(
        [modified], "SOP-002", "1.0", CONTENT, envelope, trust
    )
    assert not report["notion_metadata_matches_signed_snapshot"]


@pytest.mark.asyncio
async def test_mcp_fetches_notion_rows_and_local_trust_store(tmp_path, monkeypatch):
    doc, envelope, trust = fixture()
    trustfile = tmp_path / "trusted-public-keys.json"
    trustfile.write_text(json.dumps(trust))
    monkeypatch.setenv("QARAWORK_DC_TRUST_STORE", str(trustfile))
    calls = []
    async def mocked_reader(source_id):
        calls.append(source_id)
        return [row(doc)]
    monkeypatch.setattr(
        "qarawork_document_control.server.read_notion_document_register", mocked_reader
    )
    report = await verify_notion_signed_revision(
        DS_ID, "SOP-002", "1.0", base64.b64encode(CONTENT).decode(), envelope,
        "2026-10-26",
    )
    assert calls == [DS_ID]
    assert report["documents_scanned"] == 1
    assert report["notion_metadata_matches_signed_snapshot"]
    assert not report["notion_page_content_verified"]
    assert not report["verified_as_current_document"]


@pytest.mark.asyncio
async def test_mcp_invalid_content_rejected_before_notion_call(tmp_path, monkeypatch):
    _, envelope, trust = fixture()
    file = tmp_path / "trust.json"
    file.write_text(json.dumps(trust))
    monkeypatch.setenv("QARAWORK_DC_TRUST_STORE", str(file))
    async def should_never_call(source_id):
        raise AssertionError("Notion called with invalid content")
    monkeypatch.setattr(
        "qarawork_document_control.server.read_notion_document_register",
        should_never_call,
    )
    with pytest.raises(ValueError, match="base64"):
        await verify_notion_signed_revision(
            DS_ID, "SOP-002", "1.0", "not base64!", envelope
        )


@pytest.mark.asyncio
async def test_mcp_missing_trust_store_rejected_before_notion_call(monkeypatch):
    _, envelope, _ = fixture()
    monkeypatch.delenv("QARAWORK_DC_TRUST_STORE", raising=False)
    async def should_never_call(source_id):
        raise AssertionError("Notion called without trust")
    monkeypatch.setattr(
        "qarawork_document_control.server.read_notion_document_register",
        should_never_call,
    )
    with pytest.raises(ValueError, match="TRUST_STORE"):
        await verify_notion_signed_revision(
            DS_ID, "SOP-002", "1.0", base64.b64encode(CONTENT).decode(), envelope
        )


def test_unified_tool_registered():
    assert "verify_notion_signed_revision" in mcp._tool_manager._tools
