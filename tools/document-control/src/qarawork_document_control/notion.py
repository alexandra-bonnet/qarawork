"""Read-only Notion data-source adapter for the Document Control MCP.

The adapter only queries a specifically supplied Notion data-source UUID.
It never writes to Notion, follows redirects, or treats Notion properties
as independently authenticated approvals or protected fingerprints.
"""
from __future__ import annotations

import os
import re

import httpx

NOTION_VERSION = "2025-09-03"
NOTION_UUID = re.compile(r"(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\Z")
MAX_ROWS = 2000
MAX_PAGES = 21
PROPERTY_NAMES = (
    "Document ID", "Title", "Revision", "Status", "Owner", "Approved By",
    "Approved At", "Effective Date", "Content SHA-256",
)


def _text(prop: object) -> str:
    if not isinstance(prop, dict):
        return ""
    chunks = prop.get("title") if prop.get("type") == "title" else (
        prop.get("rich_text") if prop.get("type") == "rich_text" else []
    )
    if not isinstance(chunks, list):
        return ""
    return "".join(str(part.get("plain_text", "")) for part in chunks if isinstance(part, dict)).strip()


def _field(properties: dict, name: str) -> str:
    prop = properties.get(name, {})
    if not isinstance(prop, dict):
        return ""
    if prop.get("type") in ("title", "rich_text"):
        return _text(prop)
    if prop.get("type") in ("select", "status"):
        return str((prop.get(prop["type"]) or {}).get("name") or "").strip()
    if prop.get("type") == "date":
        return str((prop.get("date") or {}).get("start") or "").strip()
    if prop.get("type") == "people":
        people = prop.get("people") or []
        if not isinstance(people, list):
            return ""
        return ", ".join(str(p.get("name") or p.get("id") or "").strip()
                         for p in people if isinstance(p, dict)).strip()
    return ""


def parse_document_page(page: dict) -> dict:
    """Normalize a Notion page; no approval, access or evidence authenticity inferred."""
    if not isinstance(page, dict) or not isinstance(page.get("properties"), dict):
        raise ValueError("Notion document page is malformed.")
    p = page["properties"]
    return {
        "document_id": _field(p, "Document ID"),
        "title": _field(p, "Title"),
        "revision": _field(p, "Revision"),
        "status": _field(p, "Status"),
        "owner": _field(p, "Owner"),
        "approved_by": _field(p, "Approved By"),
        "approved_at": _field(p, "Approved At"),
        "effective_date": _field(p, "Effective Date"),
        "content_sha256": _field(p, "Content SHA-256"),
        "notion_page_id": str(page.get("id") or ""),
        "notion_url": str(page.get("url") or ""),
    }


def validate_document_schema(properties: dict) -> None:
    """Fail on missing or unsupported columns, rather than silently misreading a register."""
    expected = {
        "Document ID": {"rich_text"},
        "Title": {"title"},
        "Revision": {"rich_text"},
        "Status": {"select", "status"},
        "Owner": {"rich_text", "people"},
        "Approved By": {"rich_text", "people"},
        "Approved At": {"date"},
        "Effective Date": {"date"},
        "Content SHA-256": {"rich_text"},
    }
    missing = [name for name in expected if name not in properties]
    wrong = [name for name, allowed in expected.items()
             if name in properties and properties[name].get("type") not in allowed]
    if missing or wrong:
        raise ValueError(f"Notion document-register schema mismatch: missing={missing}; wrong_type={wrong}")


async def read_notion_document_register(
    notion_data_source_id: str,
    *,
    notion_token: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict]:
    """Read a complete, bounded document register; reject incomplete results."""
    if not isinstance(notion_data_source_id, str) or not NOTION_UUID.fullmatch(notion_data_source_id):
        raise ValueError("notion_data_source_id must be a Notion data-source UUID.")
    token = notion_token if notion_token is not None else os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError("NOTION_TOKEN is required; use an integration with read-content access.")
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    results: list[dict] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    async with httpx.AsyncClient(
        base_url="https://api.notion.com", headers=headers,
        timeout=30.0, follow_redirects=False, transport=transport,
    ) as client:
        metadata = await client.get(f"/v1/data_sources/{notion_data_source_id}")
        metadata.raise_for_status()
        source = metadata.json()
        if not isinstance(source, dict) or not isinstance(source.get("properties"), dict):
            raise ValueError("Notion data-source metadata is malformed.")
        validate_document_schema(source["properties"])
        for _ in range(MAX_PAGES):
            body: dict = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            response = await client.post(
                f"/v1/data_sources/{notion_data_source_id}/query", json=body
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                raise ValueError("Malformed Notion query response.")
            if any(not isinstance(page, dict) for page in payload["results"]):
                raise ValueError("Malformed Notion page in results.")
            results.extend(payload["results"])
            if len(results) > MAX_ROWS:
                raise ValueError("Notion data-source scan exceeds the configured limit.")
            if not isinstance(payload.get("has_more"), bool):
                raise ValueError("Notion pagination flag missing.")
            if not payload["has_more"]:
                return [parse_document_page(page) for page in results]
            next_cursor = payload.get("next_cursor")
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                raise ValueError("Invalid or repeated Notion pagination cursor.")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
    raise ValueError("Notion pagination exceeds the configured number of pages.")
