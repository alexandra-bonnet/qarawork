"""Read and canonicalize actual Notion page block content, fail closed.

This adapter is read-only and covers a deliberately limited class of text
documents. Unknown, embedded, inaccessible or changing content is NEVER
silently ignored or reported as matching.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

import httpx

from .notion import NOTION_VERSION, NOTION_UUID

MAX_BLOCKS = 500
MAX_DEPTH = 8
MAX_CONTENT_BYTES = 2_000_000
TEXT_TYPES = frozenset({
    "paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item",
    "numbered_list_item", "to_do", "toggle", "quote", "callout", "code",
})
SUPPORTED_TYPES = TEXT_TYPES | {"divider"}
SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _canonical_rich_text(parts: object) -> list[dict]:
    if not isinstance(parts, list):
        raise ValueError("Notion block rich_text is missing or malformed.")
    output = []
    for part in parts:
        if not isinstance(part, dict) or part.get("type") != "text":
            raise ValueError("Non-text or unsupported Notion rich-text content must not be ignored.")
        text = part.get("text")
        annotations = part.get("annotations") or {}
        if not isinstance(text, dict) or not isinstance(text.get("content"), str) or not isinstance(annotations, dict):
            raise ValueError("Malformed Notion rich-text segment.")
        href = text.get("link")
        if href is not None and (
            not isinstance(href, dict) or not isinstance(href.get("url"), str)
        ):
            raise ValueError("Unsupported Notion link representation.")
        output.append({
            "text": text["content"],
            "link": href["url"] if href else None,
            "bold": annotations.get("bold", False),
            "italic": annotations.get("italic", False),
            "strikethrough": annotations.get("strikethrough", False),
            "underline": annotations.get("underline", False),
            "code": annotations.get("code", False),
            "color": annotations.get("color", "default"),
        })
    return output


def canonical_block(block: dict) -> dict:
    """Return supported visible semantics, without volatile Notion IDs/times."""
    if not isinstance(block, dict) or block.get("type") not in SUPPORTED_TYPES:
        raise ValueError("Unsupported Notion block type; content integrity not verified.")
    kind = block["type"]
    details = block.get(kind)
    if not isinstance(details, dict):
        raise ValueError("Notion block has missing content.")
    result = {"type": kind}
    if kind in TEXT_TYPES:
        result["rich_text"] = _canonical_rich_text(details.get("rich_text"))
        if kind == "to_do":
            if not isinstance(details.get("checked"), bool):
                raise ValueError("Missing Notion checkbox state.")
            result["checked"] = details["checked"]
        if kind == "code":
            if not isinstance(details.get("language"), str):
                raise ValueError("Missing Notion code language.")
            result["language"] = details["language"]
        if kind == "callout":
            # Icons and files are outside the strictly supported text-only scope.
            if details.get("icon") is not None or block.get("icon") is not None:
                raise ValueError("Notion callout icons are not supported for canonicalization.")
        if details.get("caption"):
            raise ValueError("Notion block captions are not supported for canonicalization.")
    if "children" in block:
        result["children"] = block["children"]
    return result


def canonical_bytes(blocks: list[dict]) -> bytes:
    """Versioned canonical structure, preserving order, formatting and children."""
    if not isinstance(blocks, list):
        raise ValueError("Notion content must be a list of blocks.")
    payload = {
        "schema": "qarawork-notion-blocks-v1",
        "blocks": blocks,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_CONTENT_BYTES:
        raise ValueError("Notion page content exceeds the maximum allowed size.")
    return raw


async def read_notion_page_content(
    page_id: str, *, notion_token: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[bytes, str]:
    """Read all supported nested blocks and reject concurrent page edits.

    Return canonical page bytes and the Notion page last_edited_time.
    Only read API calls are made; unsupported content or broken pagination
    is a hard error, never a clean match.
    """
    if not isinstance(page_id, str) or not NOTION_UUID.fullmatch(page_id):
        raise ValueError("Notion page ID must be a UUID.")
    token = notion_token if notion_token is not None else os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError("NOTION_TOKEN is required.")
    headers = {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION}
    total = 0
    seen_ids: set[str] = set()
    async with httpx.AsyncClient(
        base_url="https://api.notion.com", headers=headers,
        timeout=30.0, follow_redirects=False, transport=transport,
    ) as client:
        async def page_version() -> str:
            response = await client.get(f"/v1/pages/{page_id}")
            response.raise_for_status()
            info = response.json()
            if not isinstance(info, dict) or not isinstance(info.get("last_edited_time"), str):
                raise ValueError("Notion page version metadata unavailable.")
            return info["last_edited_time"]

        async def children(parent_id: str, depth: int) -> list[dict]:
            nonlocal total
            if depth > MAX_DEPTH:
                raise ValueError("Notion page nesting exceeds supported limit.")
            collected: list[dict] = []
            cursor = None
            seen_cursors: set[str] = set()
            for _ in range(21):
                params = {"page_size": 100}
                if cursor:
                    params["start_cursor"] = cursor
                response = await client.get(
                    f"/v1/blocks/{parent_id}/children", params=params
                )
                response.raise_for_status()
                batch = response.json()
                if not isinstance(batch, dict) or not isinstance(batch.get("results"), list):
                    raise ValueError("Malformed Notion block response.")
                for block in batch["results"]:
                    total += 1
                    if total > MAX_BLOCKS:
                        raise ValueError("Notion page has more blocks than supported.")
                    if not isinstance(block, dict) or not isinstance(block.get("id"), str):
                        raise ValueError("Malformed Notion block ID.")
                    if block["id"] in seen_ids:
                        raise ValueError("Repeated Notion block ID.")
                    seen_ids.add(block["id"])
                    item = canonical_block(block)
                    has_children = block.get("has_children")
                    if not isinstance(has_children, bool):
                        raise ValueError("Malformed Notion has_children value.")
                    if has_children:
                        item["children"] = await children(block["id"], depth + 1)
                    collected.append(item)
                if batch.get("has_more") is False:
                    return collected
                if batch.get("has_more") is not True:
                    raise ValueError("Notion block pagination flag unavailable.")
                nxt = batch.get("next_cursor")
                if not isinstance(nxt, str) or not nxt or nxt in seen_cursors:
                    raise ValueError("Notion block pagination cursor invalid.")
                seen_cursors.add(nxt)
                cursor = nxt
            raise ValueError("Notion block pagination exceeds supported limit.")

        before = await page_version()
        blocks = await children(page_id, 0)
        after = await page_version()
        if before != after:
            raise ValueError("Notion page changed during verification; retry.")
    return canonical_bytes(blocks), after
