"""Synthetic tests for current Notion page activity and supplied event lists."""
import httpx
import pytest

from qarawork_audit_trail.notion_activity import (
    read_notion_page_activity, parse_notion_page_metadata,
)
from qarawork_audit_trail.events import review_event_sequence
from qarawork_audit_trail.server import mcp

PAGE = "00000000-0000-4000-8000-000000000001"


def page():
    return {
        "object": "page", "id": PAGE,
        "url": "https://www.notion.so/fake",
        "created_time": "2026-10-24T09:00:00.000Z",
        "created_by": {"object": "user", "id": "user-creator"},
        "last_edited_time": "2026-10-26T16:00:00.000Z",
        "last_edited_by": {"object": "user", "id": "user-editor"},
    }


@pytest.mark.asyncio
async def test_notion_read_only_metadata_and_no_authentic_identity_claim():
    calls = []
    def handler(req):
        calls.append(req)
        assert req.method == "GET"
        assert req.url.path == f"/v1/pages/{PAGE}"
        assert req.headers["notion-version"] == "2025-09-03"
        return httpx.Response(200, json=page())
    result = await read_notion_page_activity(
        PAGE, notion_token="synthetic", transport=httpx.MockTransport(handler),
    )
    assert len(calls) == 1
    assert result["last_edited_by_notion_id"] == "user-editor"
    assert result["last_edited_at"] == "2026-10-26T16:00:00.000Z"
    assert result["actor_identity_verified"] is False
    assert result["complete_edit_history_available"] is False


def test_missing_editor_or_time_fails():
    p = page()
    p["last_edited_by"] = None
    with pytest.raises(ValueError, match="attribution"):
        parse_notion_page_metadata(p, PAGE)
    p = page()
    p["last_edited_time"] = "yesterday"
    with pytest.raises(ValueError, match="timestamp"):
        parse_notion_page_metadata(p, PAGE)


def test_wrong_page_rejected():
    with pytest.raises(ValueError, match="identity"):
        parse_notion_page_metadata(page(), "12345678-1234-1234-1234-123456789abc")


@pytest.mark.asyncio
async def test_notion_missing_token_and_403():
    with pytest.raises(ValueError, match="NOTION_TOKEN"):
        await read_notion_page_activity(PAGE, notion_token="")
    def forbidden(req):
        assert req.method == "GET"
        return httpx.Response(403, json={"message": "Forbidden"})
    with pytest.raises(httpx.HTTPStatusError):
        await read_notion_page_activity(
            PAGE, notion_token="demo", transport=httpx.MockTransport(forbidden),
        )


def observed(seq, event_id, when, actor="fictional-reviewer"):
    return {
        "event_id": event_id, "sequence": seq,
        "timestamp": when, "object_id": "SOP-002:1.0",
        "operation": "page_edited", "actor_id": actor,
        "content_sha256": "a" * 64,
    }


def test_supplied_consistent_list_does_not_prove_complete_audit_trail():
    r = review_event_sequence([
        observed(1, "a", "2026-10-26T15:58:00Z"),
        observed(2, "b", "2026-10-26T16:00:00Z"),
    ], expected_object_id="SOP-002:1.0")
    assert r["internal_consistency_passed"] is True
    assert r["audit_trail_complete"] is False
    assert r["actor_identity_verified"] is False
    assert r["event_provenance_independently_verified"] is False


def test_gap_reordering_missing_actor_and_duplicate_ids_detected():
    r = review_event_sequence([
        observed(1, "duplicate", "2026-10-26T16:00:00Z"),
        observed(3, "duplicate", "2026-10-26T15:58:00Z", actor=""),
    ], expected_object_id="SOP-002:1.0")
    codes = {x["code"] for x in r["findings"]}
    assert {"SEQUENCE_GAP_OR_REORDER", "DUPLICATE_EVENT_ID", "ACTOR_MISSING", "TIME_REVERSED"} <= codes


def test_empty_events_never_claim_completeness():
    r = review_event_sequence([], expected_object_id="SOP-002:1.0")
    assert r["findings"][0]["code"] == "NO_EVENTS_SUPPLIED"
    assert not r["audit_trail_complete"]


def test_invalid_object_and_timestamp_detected():
    bad = observed(1, "a", "not-a-date")
    bad["object_id"] = "SOP-001"
    bad["content_sha256"] = "broken"
    r = review_event_sequence([bad], expected_object_id="SOP-002:1.0")
    assert {"OBJECT_MISMATCH", "INVALID_TIMESTAMP", "INVALID_DIGEST"} <= {
        x["code"] for x in r["findings"]
    }


def test_exactly_four_mcp_functions():
    assert set(mcp._tool_manager._tools) == {
        "inspect_notion_page_activity", "review_event_sequence", "inspect_github_pr_history",
        "verify_audit_evidence_capture"
    }
