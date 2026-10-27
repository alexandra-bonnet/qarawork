"""Synthetic live Notion-page content verification, with no Notion write calls."""
import hashlib
import json

import httpx
import pytest

from qarawork_document_control.notion_content import (
    canonical_block, canonical_bytes, read_notion_page_content,
)
from qarawork_document_control.server import inspect_notion_document_register, mcp

PAGE = "00000000-0000-4000-8000-000000000001"
DS = "00000000-0000-4000-8000-000000000002"


def paragraph(value, *, block_id="12345678-1234-1234-1234-123456789abc", children=False):
    return {
        "id": block_id, "type": "paragraph", "has_children": children,
        "paragraph": {"rich_text": [{
            "type": "text", "plain_text": value, "text": {"content": value, "link": None},
            "annotations": {"bold": False},
        }]},
    }


def mock_page(*, value="Original", altered_during_read=False, unsupported=False,
              child=False, forbidden=False):
    calls = []
    def handler(req):
        calls.append((req.method, req.url.path))
        assert req.method == "GET"
        if forbidden:
            return httpx.Response(403, json={"message": "Forbidden"})
        if req.url.path == f"/v1/pages/{PAGE}":
            n = sum(path == req.url.path for _, path in calls)
            return httpx.Response(200, json={
                "last_edited_time": "2026-10-26T09:01:00.000Z"
                if not altered_during_read or n == 1 else "2026-10-26T09:02:00.000Z",
            })
        if req.url.path == f"/v1/blocks/{PAGE}/children":
            block = paragraph(value, children=child)
            if unsupported:
                block["type"] = "image"
                block["image"] = {"type": "external", "external": {"url": "https://example.com/a"}}
            return httpx.Response(200, json={
                "results": [block], "has_more": False, "next_cursor": None
            })
        if req.url.path == "/v1/blocks/12345678-1234-1234-1234-123456789abc/children":
            return httpx.Response(200, json={
                "results": [paragraph("Nested text", block_id="12345678-1234-1234-1234-123456789abd")],
                "has_more": False, "next_cursor": None,
            })
        raise AssertionError(req.url.path)
    return httpx.MockTransport(handler), calls


@pytest.mark.asyncio
async def test_live_page_reads_complete_actual_text_and_nested_children():
    transport, calls = mock_page(child=True)
    content, version = await read_notion_page_content(
        PAGE, notion_token="demo-token", transport=transport,
    )
    assert b"Original" in content and b"Nested text" in content
    assert version.startswith("2026-10-26")
    assert len(calls) == 4
    assert all(method == "GET" for method, _ in calls)


@pytest.mark.asyncio
async def test_one_character_change_changes_actual_page_digest():
    original, _ = await read_notion_page_content(
        PAGE, notion_token="demo", transport=mock_page(value="Approved text")[0],
    )
    changed, _ = await read_notion_page_content(
        PAGE, notion_token="demo", transport=mock_page(value="Approved texts")[0],
    )
    assert hashlib.sha256(original).hexdigest() != hashlib.sha256(changed).hexdigest()


@pytest.mark.asyncio
async def test_unsupported_image_block_fails_closed():
    with pytest.raises(ValueError, match="Unsupported Notion block"):
        await read_notion_page_content(
            PAGE, notion_token="demo", transport=mock_page(unsupported=True)[0]
        )


@pytest.mark.asyncio
async def test_concurrent_edit_fails_closed():
    with pytest.raises(ValueError, match="changed during verification"):
        await read_notion_page_content(
            PAGE, notion_token="demo", transport=mock_page(altered_during_read=True)[0]
        )


@pytest.mark.asyncio
async def test_inaccessible_page_fails_closed():
    with pytest.raises(httpx.HTTPStatusError):
        await read_notion_page_content(
            PAGE, notion_token="demo", transport=mock_page(forbidden=True)[0]
        )


def test_unknown_rich_text_fails_closed():
    block = paragraph("Original")
    block["paragraph"]["rich_text"] = [{"type": "mention", "mention": {"type": "user"}}]
    with pytest.raises(ValueError, match="Non-text or unsupported"):
        canonical_block(block)


def test_canonical_content_is_stable_across_block_ids():
    first = canonical_block(paragraph("Example", block_id="a"))
    second = canonical_block(paragraph("Example", block_id="b"))
    assert canonical_bytes([first]) == canonical_bytes([second])


@pytest.mark.asyncio
async def test_existing_register_mcp_matches_then_detects_live_page_edit(tmp_path, monkeypatch):
    from qarawork_document_control.notion_page_baseline import filename_for
    root = tmp_path / "baselines"
    root.mkdir()
    monkeypatch.setenv("QARAWORK_DC_NOTION_BASELINE_ROOT", str(root))
    row = {
        "document_id": "SOP-002", "revision": "1.0",
        "title": "Test document", "owner": "Quality", "status": "Approved",
        "approved_by": "Fictional Reviewer", "approved_at": "2026-10-24",
        "effective_date": "2026-10-25", "content_sha256": "a" * 64,
        "notion_page_id": PAGE, "notion_url": "https://notion.so/synthetic",
    }
    async def register(_):
        return [row]
    monkeypatch.setattr(
        "qarawork_document_control.server.read_notion_document_register", register
    )
    base_bytes, _ = await read_notion_page_content(
        PAGE, notion_token="demo", transport=mock_page(value="Original")[0]
    )
    baseline = {
        "schema": "qarawork-notion-page-baseline-v1",
        "document_id": "SOP-002", "revision": "1.0",
        "notion_page_id": PAGE, "notion_data_source_id": DS,
        "content_sha256": hashlib.sha256(base_bytes).hexdigest(),
    }
    (root / filename_for("SOP-002", "1.0")).write_text(json.dumps(baseline))
    async def content_original(_):
        return await read_notion_page_content(
            PAGE, notion_token="demo", transport=mock_page(value="Original")[0]
        )
    monkeypatch.setattr(
        "qarawork_document_control.server.read_notion_page_content", content_original
    )
    ok = await inspect_notion_document_register(DS, "2026-10-26", True)
    doc = ok["records"][0]
    assert doc["notion_page_content_check"]["status"] == "Matches captured reference"
    assert doc["document_overview"]["page_content_integrity"] == "Matches captured reference"
    assert doc["document_overview"]["human_approval_verified"] is False
    assert "live Notion page body was read" in doc["document_overview"]["scope_note"]
    assert "does not validate Notion attachments" in doc["document_overview"]["scope_note"]

    async def content_changed(_):
        return await read_notion_page_content(
            PAGE, notion_token="demo", transport=mock_page(value="Original changed")[0]
        )
    monkeypatch.setattr(
        "qarawork_document_control.server.read_notion_page_content", content_changed
    )
    changed = await inspect_notion_document_register(DS, "2026-10-26", True)
    item = changed["records"][0]
    assert item["notion_page_content_check"]["status"] == "Changed since reference"
    assert "reapproval" in item["document_overview"]["next_action"]
    assert item["document_overview"]["authorized_for_use"] is False
    assert not changed["allowed_to_select_current"]


@pytest.mark.asyncio
async def test_missing_page_reference_is_not_treated_as_match(tmp_path, monkeypatch):
    root = tmp_path / "empty"
    root.mkdir()
    monkeypatch.setenv("QARAWORK_DC_NOTION_BASELINE_ROOT", str(root))
    row = {
        "document_id": "SOP-002", "revision": "1.0", "title": "Test",
        "owner": "Quality", "status": "Approved",
        "approved_by": "Fictional", "approved_at": "2026-10-24",
        "effective_date": "2026-10-25", "content_sha256": "a" * 64,
        "notion_page_id": PAGE, "notion_url": "https://notion.so/fake",
    }
    async def register(_):
        return [row]
    async def forbidden_call(_):
        raise AssertionError("Missing baseline should not read live page content")
    monkeypatch.setattr("qarawork_document_control.server.read_notion_document_register", register)
    monkeypatch.setattr("qarawork_document_control.server.read_notion_page_content", forbidden_call)
    r = await inspect_notion_document_register(DS, "2026-10-26", True)
    assert r["records"][0]["notion_page_content_check"]["status"] == "Reference missing"
    assert "could not be verified" in r["records"][0]["document_overview"]["scope_note"]


def test_six_existing_tools_still_only_six():
    assert len(mcp._tool_manager._tools) == 6
