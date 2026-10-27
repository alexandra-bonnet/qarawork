"""Read-only Notion data-source requirements to GitHub Python tests checker."""
from __future__ import annotations

import os
import re

import httpx

from .core import REF, extract_test_references, is_test_file
from .github import fetch_python_test_files

NOTION_API_VERSION = "2025-09-03"
NOTION_ID = re.compile(r"^[0-9a-fA-F]{32}$|^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
EXTERNAL_REF = re.compile(r"\bRequirement\s*:\s*(REQ-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+)\b", re.IGNORECASE)
MAX_NOTION_ROWS = 2000


def text_property(properties: dict, key: str) -> str:
    prop = properties.get(key, {})
    if not isinstance(prop, dict):
        return ""
    if prop.get("type") == "title":
        chunks = prop.get("title", [])
    elif prop.get("type") == "rich_text":
        chunks = prop.get("rich_text", [])
    else:
        return ""
    return "".join(chunk.get("plain_text", "") for chunk in chunks).strip()


def parse_notion_requirements(pages: list[dict]) -> list[dict]:
    rows = []
    seen = set()
    for page in pages:
        properties = page.get("properties", {})
        identifier = text_property(properties, "Requirement ID")
        title = text_property(properties, "Name")
        if not identifier or not re.fullmatch(r"REQ-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+", identifier, re.IGNORECASE):
            raise ValueError("Notion row has a missing or invalid Requirement ID")
        identifier = identifier.upper()
        if identifier in seen:
            raise ValueError(f"Duplicate Notion requirement ID: {identifier}")
        seen.add(identifier)
        if not title:
            raise ValueError(f"Notion requirement {identifier} has no Name")
        def option(name: str) -> str:
            return (properties.get(name, {}).get("select") or {}).get("name", "")

        rows.append({
            "id": identifier, "title": title, "url": page["url"],
            "description": text_property(properties, "Description"),
            "priority": option("Priority"), "requirement_status": option("Status"),
            "release": option("Release"),
        })
    return rows


async def read_notion_requirements(data_source_id: str) -> list[dict]:
    if not NOTION_ID.fullmatch(data_source_id):
        raise ValueError("notion_data_source_id must be a UUID, not a database URL")
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError("NOTION_TOKEN is required. Use a Notion internal integration with read-only content access.")
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }
    pages = []
    cursor = None
    async with httpx.AsyncClient(base_url="https://api.notion.com", headers=headers,
                                 timeout=30.0, follow_redirects=False) as client:
        while True:
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            response = await client.post(f"/v1/data_sources/{data_source_id}/query", json=body)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload.get("results"), list):
                raise ValueError("Invalid Notion API response")
            pages.extend(payload["results"])
            if len(pages) > MAX_NOTION_ROWS:
                raise ValueError("Notion pagination limit exceeded; incomplete scan refused")
            if not payload.get("has_more"):
                break
            new_cursor = payload.get("next_cursor")
            if not new_cursor or new_cursor == cursor:
                raise ValueError("Notion pagination cursor invalid; incomplete scan refused")
            cursor = new_cursor
    return parse_notion_requirements(pages)


def analyze_notion_links(requirements: list[dict], files: dict[str, str], repository: str) -> dict:
    """Find explicit requirement references at individual pytest function granularity."""
    import ast

    references: dict[str, list[dict[str, str]]] = {}
    scanned = 0
    for path, content in sorted(files.items()):
        if not is_test_file(path):
            continue
        scanned += 1
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            raise ValueError(f"Cannot parse test file {path}: {exc}") from exc

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            docstring = ast.get_docstring(node, clean=False)
            if not docstring:
                continue
            for identifier in set(value.upper() for value in EXTERNAL_REF.findall(docstring)):
                location = {"test_file": path, "test_name": node.name, "line": node.lineno}
                # Deduplicate exact test references while keeping multiple distinct tests.
                matches = references.setdefault(identifier, [])
                if location not in matches:
                    matches.append(location)

    result_rows = []
    for item in sorted(requirements, key=lambda r: r["id"]):
        matches = sorted(references.get(item["id"], []),
                         key=lambda r: (r["test_file"], r["test_name"], r["line"]))
        paths = sorted(set(match["test_file"] for match in matches))
        result_rows.append({
            **item, "status": "linked" if matches else "unlinked",
            "test_files": paths, "test_cases": matches,
        })
    known = {item["id"] for item in requirements}
    dangling = []
    for identifier in sorted(set(references) - known):
        matches = sorted(references[identifier],
                         key=lambda r: (r["test_file"], r["test_name"], r["line"]))
        dangling.append({
            "id": identifier,
            "test_files": sorted(set(match["test_file"] for match in matches)),
            "test_cases": matches,
        })
    return {
        "source": "notion", "repository": repository,
        "convention": "Requirement: REQ-... in pytest function docstring",
        "scanned_test_files": scanned, "requirements_count": len(result_rows),
        "linked_count": sum(row["status"] == "linked" for row in result_rows),
        "unlinked_count": sum(row["status"] == "unlinked" for row in result_rows),
        "requirements": result_rows,
        "references_to_unknown_requirement_ids": dangling,
        "limitations": [
            "A linked marker does not prove that a test passes, verifies the requirement, or establishes regulatory compliance.",
            "Only pytest-style function docstrings in Python test files are checked.",
            "Notion rows must have Name (title) and Requirement ID (rich text) properties.",
            "Only accessible data source rows and GitHub files are analyzed.",
        ],
    }


async def inspect_notion_traceability(repository: str, notion_data_source_id: str,
                                      ref: str | None = None) -> dict:
    requirements = await read_notion_requirements(notion_data_source_id)
    branch, files = await fetch_python_test_files(repository, ref)
    result = analyze_notion_links(requirements, files, repository)
    result["ref"] = branch
    result["notion_data_source_id"] = notion_data_source_id
    return result
