"""Read-only Notion page activity metadata, not a historical audit log."""
from __future__ import annotations

from datetime import datetime
import os
import re
import httpx

NOTION_VERSION = "2025-09-03"
UUID = re.compile(r"(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\Z")


def utc_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Notion timestamp is missing.")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Notion timestamp is malformed.") from exc
    if dt.tzinfo is None:
        raise ValueError("Notion timestamp has no timezone.")
    return dt


def parse_notion_page_metadata(payload: dict, expected_id: str) -> dict:
    """Use fields as reported by Notion; do not authenticate a human actor."""
    if not isinstance(payload, dict) or payload.get("object") != "page":
        raise ValueError("Notion response is not a page.")
    if payload.get("id", "").replace("-", "").lower() != expected_id.replace("-", "").lower():
        raise ValueError("Notion page identity does not match the requested page.")
    edited_by = payload.get("last_edited_by")
    created_by = payload.get("created_by")
    if not isinstance(edited_by, dict) or not isinstance(edited_by.get("id"), str):
        raise ValueError("Notion last-editor attribution is unavailable.")
    if not isinstance(created_by, dict) or not isinstance(created_by.get("id"), str):
        raise ValueError("Notion creator attribution is unavailable.")
    created = utc_timestamp(payload.get("created_time"))
    edited = utc_timestamp(payload.get("last_edited_time"))
    if edited < created:
        raise ValueError("Notion edit time is earlier than creation.")
    return {
        "page_id": payload["id"],
        "page_url": payload.get("url") if isinstance(payload.get("url"), str) else None,
        "created_at": payload["created_time"],
        "created_by_notion_id": created_by["id"],
        "last_edited_at": payload["last_edited_time"],
        "last_edited_by_notion_id": edited_by["id"],
        "source": "notion_page_metadata",
        "read_only": True,
        "actor_identity_verified": False,
        "complete_edit_history_available": False,
        "event_provenance_independently_verified": False,
        "notice": (
            "Notion supplies creation and most-recent-edit metadata only. "
            "This is not a complete edit history, an authenticated human audit "
            "trail, or evidence of what text changed."
        ),
    }


async def read_notion_page_activity(
    page_id: str, *, notion_token: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    if not isinstance(page_id, str) or not UUID.fullmatch(page_id):
        raise ValueError("page_id must be a Notion page UUID.")
    token = notion_token if notion_token is not None else os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError("NOTION_TOKEN is required for the read-only Notion API call.")
    async with httpx.AsyncClient(
        base_url="https://api.notion.com", follow_redirects=False,
        timeout=30.0, transport=transport, headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
        },
    ) as client:
        response = await client.get(f"/v1/pages/{page_id}")
        response.raise_for_status()
        return parse_notion_page_metadata(response.json(), page_id)
