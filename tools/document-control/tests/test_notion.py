"""Fully synthetic Notion API tests. No network credentials or live SMQ required."""
import json
from datetime import date

import httpx
import pytest

from qarawork_document_control.notion import (
    NOTION_VERSION, parse_document_page, read_notion_document_register,
    validate_document_schema,
)
from qarawork_document_control.server import mcp, inspect_notion_document_register

DS_ID = "12345678-1234-1234-1234-123456789abc"
DOC_HASH = "a" * 64
FIELDS = {
    "Document ID": "rich_text",
    "Title": "title",
    "Revision": "rich_text",
    "Status": "status",
    "Owner": "rich_text",
    "Approved By": "people",
    "Approved At": "date",
    "Effective Date": "date",
    "Content SHA-256": "rich_text",
}


def schema():
    return {name: {"type": kind} for name, kind in FIELDS.items()}


def rich(value):
    return {"type": "rich_text", "rich_text": [{"plain_text": value}]}


def notion_page(status="Approved", revision="1.0"):
    return {
        "id": "page-1",
        "url": "https://www.notion.so/synthetic-page",
        "properties": {
            "Document ID": rich("SOP-001"),
            "Title": {"type": "title", "title": [{"plain_text": "Synthetic SOP"}]},
            "Revision": rich(revision),
            "Status": {"type": "status", "status": {"name": status}},
            "Owner": rich("Quality"),
            "Approved By": {"type": "people", "people": [{"id": "fake-person", "name": "Fictional Reviewer"}]},
            "Approved At": {"type": "date", "date": {"start": "2026-10-24"}},
            "Effective Date": {"type": "date", "date": {"start": "2026-10-25"}},
            "Content SHA-256": rich(DOC_HASH),
        },
    }


def mock_api(*, results=None, malformed_schema=False, broken_cursor=False):
    calls = []
    def responder(request):
        calls.append(request)
        assert request.headers["notion-version"] == NOTION_VERSION
        assert request.headers["authorization"] == "Bearer synthetic-token"
        if request.method == "GET":
            data = schema()
            if malformed_schema:
                data.pop("Content SHA-256")
            return httpx.Response(200, json={"properties": data})
        assert request.method == "POST"
        payload = json.loads(request.content)
        if broken_cursor:
            return httpx.Response(200, json={
                "results": [notion_page()], "has_more": True, "next_cursor": None,
            })
        if payload.get("start_cursor") is None and results is None:
            return httpx.Response(200, json={
                "results": [notion_page()], "has_more": True, "next_cursor": "next",
            })
        return httpx.Response(200, json={
            "results": results if results is not None else [notion_page("Draft", "2.0")],
            "has_more": False, "next_cursor": None,
        })
    return httpx.MockTransport(responder), calls


@pytest.mark.asyncio
async def test_read_schema_and_full_pagination():
    transport, calls = mock_api()
    rows = await read_notion_document_register(
        DS_ID, notion_token="synthetic-token", transport=transport,
    )
    assert len(rows) == 2
    assert rows[0]["document_id"] == "SOP-001"
    assert rows[0]["approved_by"] == "Fictional Reviewer"
    assert [request.method for request in calls] == ["GET", "POST", "POST"]


@pytest.mark.asyncio
async def test_read_empty_register():
    transport, _ = mock_api(results=[])
    rows = await read_notion_document_register(
        DS_ID, notion_token="synthetic-token", transport=transport,
    )
    assert rows == []


@pytest.mark.asyncio
async def test_missing_column_fails_before_query():
    transport, calls = mock_api(malformed_schema=True)
    with pytest.raises(ValueError, match="schema mismatch"):
        await read_notion_document_register(
            DS_ID, notion_token="synthetic-token", transport=transport,
        )
    assert [request.method for request in calls] == ["GET"]


@pytest.mark.asyncio
async def test_incomplete_pagination_rejected():
    transport, _ = mock_api(broken_cursor=True)
    with pytest.raises(ValueError, match="cursor"):
        await read_notion_document_register(
            DS_ID, notion_token="synthetic-token", transport=transport,
        )


@pytest.mark.asyncio
async def test_invalid_uuid_or_missing_token_refused(monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    with pytest.raises(ValueError, match="UUID"):
        await read_notion_document_register("not-a-uuid", notion_token="synthetic-token")
    with pytest.raises(ValueError, match="NOTION_TOKEN"):
        await read_notion_document_register(DS_ID)


@pytest.mark.asyncio
async def test_notion_403_propagates_without_write():
    def forbidden(req):
        assert req.method == "GET"
        return httpx.Response(403, json={"message": "Forbidden"})
    with pytest.raises(httpx.HTTPStatusError):
        await read_notion_document_register(
            DS_ID, notion_token="synthetic-token",
            transport=httpx.MockTransport(forbidden),
        )


def test_page_parsing_missing_metadata_preserves_gaps():
    page = notion_page()
    page["properties"]["Approved By"] = {"type": "people", "people": []}
    parsed = parse_document_page(page)
    assert parsed["approved_by"] == ""
    assert parsed["status"] == "Approved"
    assert parsed["content_sha256"] == DOC_HASH


def test_invalid_property_type_rejected():
    props = schema()
    props["Status"] = {"type": "number"}
    with pytest.raises(ValueError, match="wrong_type"):
        validate_document_schema(props)


def test_notion_mcp_tool_registered():
    assert "inspect_notion_document_register" in mcp._tool_manager._tools


@pytest.mark.asyncio
async def test_mcp_results_fail_closed_without_external_baseline(monkeypatch):
    async def fake_read(data_source_id):
        return [parse_document_page(notion_page())]
    monkeypatch.setattr(
        "qarawork_document_control.server.read_notion_document_register", fake_read
    )
    report = await inspect_notion_document_register(DS_ID, "2026-10-26")
    assert report["documents_scanned"] == 1
    assert not report["records"][0]["eligible_as_current"]
    assert any("baseline" in error for error in report["records"][0]["errors"])
    assert report["records"][0]["notion_url"].startswith("https://")


@pytest.mark.asyncio
async def test_empty_register_not_allowed(monkeypatch):
    async def fake_empty(data_source_id):
        return []
    monkeypatch.setattr(
        "qarawork_document_control.server.read_notion_document_register", fake_empty
    )
    report = await inspect_notion_document_register(DS_ID, "2026-10-26")
    assert report["allowed_to_select_current"] is False
