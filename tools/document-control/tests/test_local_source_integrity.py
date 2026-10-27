"""Server-read file integrity tests; all Notion calls mocked."""
from __future__ import annotations

import json
from datetime import date

import pytest

from test_signed_evidence import CONTENT, fixture
from qarawork_document_control.local_snapshot import read_local_signed_artifacts
from qarawork_document_control.server import verify_notion_source_file_integrity, mcp

DS_ID = "12345678-1234-1234-1234-123456789abc"


def prepare(tmp_path, monkeypatch):
    doc, envelope, trust = fixture()
    root = tmp_path / "snapshots"
    root.mkdir()
    (root / "SOP-002--1.0.bin").write_bytes(CONTENT)
    (root / "SOP-002--1.0.evidence.json").write_text(json.dumps(envelope))
    trust_file = tmp_path / "trusted-keys.json"
    trust_file.write_text(json.dumps(trust))
    monkeypatch.setenv("QARAWORK_DC_SNAPSHOT_ROOT", str(root))
    monkeypatch.setenv("QARAWORK_DC_TRUST_STORE", str(trust_file))
    return doc, root


@pytest.mark.asyncio
async def test_live_register_plus_actual_local_file_positive(tmp_path, monkeypatch):
    doc, root = prepare(tmp_path, monkeypatch)
    async def notion_reader(ds):
        assert ds == DS_ID
        return [{**doc, "notion_page_id": "fake-page", "notion_url": "https://notion.so/fake"}]
    monkeypatch.setattr("qarawork_document_control.server.read_notion_document_register", notion_reader)
    result = await verify_notion_source_file_integrity(
        DS_ID, "SOP-002", "1.0", on_date="2026-10-26"
    )
    assert result["signed_snapshot_verified"] is True
    assert result["notion_metadata_matches_signed_snapshot"] is True
    assert result["source_file_matches_signed_fingerprint"] is True
    assert result["file_bytes_read_by_server"] == len(CONTENT)
    assert result["errors"] == []
    assert result["document_overview"]["recorded_status"] == "Approved"
    assert result["document_overview"]["file_integrity"] == "Matches recorded reference"
    assert result["document_overview"]["human_approval"] == "Not verified"
    assert result["document_overview"]["authorized_for_use"] is False
    assert result["notion_page_content_verified"] is False
    assert result["verified_as_current_document"] is False


@pytest.mark.asyncio
async def test_one_modified_source_file_byte_rejected(tmp_path, monkeypatch):
    doc, root = prepare(tmp_path, monkeypatch)
    (root / "SOP-002--1.0.bin").write_bytes(b"T" + CONTENT[1:])
    async def notion_reader(_):
        return [doc]
    monkeypatch.setattr("qarawork_document_control.server.read_notion_document_register", notion_reader)
    result = await verify_notion_source_file_integrity(DS_ID, "SOP-002", "1.0", "2026-10-26")
    assert result["cryptographic_checks_passed"] is True
    assert result["source_file_matches_signed_fingerprint"] is False
    assert result["document_overview"]["file_integrity"] == "Mismatch"
    assert result["notion_metadata_matches_signed_snapshot"] is False
    assert any("Exact document bytes differ" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_notion_approval_date_tampering_rejected(tmp_path, monkeypatch):
    doc, _ = prepare(tmp_path, monkeypatch)
    doc["approved_at"] = "2026-10-23"
    async def notion_reader(_):
        return [doc]
    monkeypatch.setattr("qarawork_document_control.server.read_notion_document_register", notion_reader)
    result = await verify_notion_source_file_integrity(DS_ID, "SOP-002", "1.0", "2026-10-26")
    assert result["signed_snapshot_verified"] is False
    assert not result["notion_metadata_matches_signed_snapshot"]
    assert result["source_file_matches_signed_fingerprint"] is True
    assert result["document_overview"]["file_integrity"] == "Not verified"


@pytest.mark.parametrize("bad_id,bad_rev", [
    ("../secret", "1.0"), ("SOP/002", "1.0"),
    ("SOP-002", "../1.0"), ("SOP-002", "."), ("", "1.0"),
])
def test_path_traversal_and_unsafe_identity_rejected(tmp_path, bad_id, bad_rev):
    root = tmp_path / "snapshots"
    root.mkdir()
    with pytest.raises(ValueError, match="invalid"):
        read_local_signed_artifacts(str(root), bad_id, bad_rev)


def test_missing_and_symlinked_files_rejected(tmp_path):
    root = tmp_path / "snapshots"
    root.mkdir()
    with pytest.raises(ValueError, match="missing"):
        read_local_signed_artifacts(str(root), "SOP-002", "1.0")
    source = tmp_path / "external.bin"
    source.write_bytes(CONTENT)
    (root / "SOP-002--1.0.bin").symlink_to(source)
    with pytest.raises(ValueError, match="symbolic"):
        read_local_signed_artifacts(str(root), "SOP-002", "1.0")


def test_oversized_file_rejected(tmp_path):
    root = tmp_path / "snapshots"
    root.mkdir()
    (root / "SOP-002--1.0.bin").write_bytes(b"0" * 2_000_001)
    with pytest.raises(ValueError, match="limit"):
        read_local_signed_artifacts(str(root), "SOP-002", "1.0")


@pytest.mark.asyncio
async def test_missing_source_refuses_before_notion_call(tmp_path, monkeypatch):
    root = tmp_path / "snapshots"
    root.mkdir()
    monkeypatch.setenv("QARAWORK_DC_SNAPSHOT_ROOT", str(root))
    async def fail_if_called(_):
        raise AssertionError("Notion must not be queried when source is absent")
    monkeypatch.setattr("qarawork_document_control.server.read_notion_document_register", fail_if_called)
    with pytest.raises(ValueError, match="missing"):
        await verify_notion_source_file_integrity(DS_ID, "SOP-002", "1.0")


def test_sixth_tool_is_registered():
    assert "verify_notion_source_file_integrity" in mcp._tool_manager._tools
