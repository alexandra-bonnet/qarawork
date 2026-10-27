"""Fail-closed QARA approval gate for a pull request.

Read-only Notion API. Only an explicitly approved change request, covering the
exact current requirement revision, can authorize work to enter the protected
branch. This is a development gate, not a regulatory approval engine.
"""
from __future__ import annotations

import hashlib
import json
import re

import httpx

from .notion import NOTION_API_VERSION, NOTION_ID, text_property

CR_ID = re.compile(r"(?<![A-Za-z0-9])CR-(\d+)(?![A-Za-z0-9])", re.I)
REQ_ID = re.compile(r"(?<![A-Za-z0-9])REQ-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+(?![A-Za-z0-9])", re.I)
MAX_RECORDS = 2000


def requirement_hash(requirement: dict) -> str:
    """Digest controlled semantic requirement fields with stable serialization."""
    fields = {name: requirement[name] for name in
              ("Requirement ID", "Name", "Description", "Release")}
    payload = json.dumps(fields, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _option(page: dict, name: str) -> str:
    prop = page.get("properties", {}).get(name, {})
    if not isinstance(prop, dict):
        return ""
    return (prop.get("select") or prop.get("status") or {}).get("name", "")


def requirement_fields(page: dict) -> dict:
    props = page.get("properties", {})
    return {
        "Requirement ID": text_property(props, "Requirement ID").upper(),
        "Name": text_property(props, "Name"),
        "Description": text_property(props, "Description"),
        "Release": _option(page, "Release"),
    }


def _related_ids(page: dict) -> set[str]:
    relation = page.get("properties", {}).get("Affected Requirements", {}).get("relation", [])
    return {str(item.get("id", "")).replace("-", "").lower() for item in relation
            if item.get("id")}


def assess_development_gate(pr_body: str, changes: list[dict],
                            requirements: list[dict]) -> dict:
    """Evaluate approval records, revision hashes and exact PR references.

    All rejection reasons are explicit. Never treat a green CI test or a
    requirement's Approved status as authorization to bypass QARA.
    """
    change_refs = set(CR_ID.findall(pr_body or ""))
    req_refs = {v.upper() for v in REQ_ID.findall(pr_body or "")}
    reasons = []
    if len(change_refs) != 1:
        reasons.append("PR body must reference exactly one CR-<number> change request.")
    if not req_refs:
        reasons.append("PR body must reference at least one REQ-... requirement ID.")
    if reasons:
        return {"allowed": False, "reasons": reasons}
    change_num = int(next(iter(change_refs)))
    matched = [p for p in changes
               if (p.get("properties", {}).get("Change ID", {}).get("unique_id") or {}).get("number") == change_num]
    if len(matched) != 1:
        return {"allowed": False, "reasons": [f"Exactly one Notion CR-{change_num} record is required."]}
    change = matched[0]
    props = change.get("properties", {})
    if _option(change, "Decision Status") != "Approved":
        reasons.append("QARA change record must have Decision Status = Approved.")
    if _option(change, "Development Authorization") != "Authorized":
        reasons.append("Development Authorization must be Authorized.")
    if _option(change, "Regulatory Classification") not in ("Substantial", "Non-substantial", "Not applicable"):
        reasons.append("QARA regulatory change classification must be completed.")
    if _option(change, "Review Outcome") in ("", "Pending"):
        reasons.append("Impact assessment outcome is missing.")
    if not text_property(props, "Decision Rationale").strip():
        reasons.append("QARA approval rationale is missing.")
    if not (props.get("Approver", {}).get("people") or []):
        reasons.append("Human QARA approver must be assigned.")
    if not (props.get("Approved At", {}).get("date") or {}).get("start"):
        reasons.append("Approval date is missing.")
    approved_hashes = text_property(props, "Approved Requirement Hash").strip()
    # One change may cover several requirements: one REQ-ID:sha256 per line.
    hashes: dict[str, str] = {}
    for line in approved_hashes.splitlines():
        match = re.fullmatch(r"(REQ-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+):([0-9a-f]{64})",
                             line.strip(), flags=re.I)
        if match is None or match.group(1).upper() in hashes:
            reasons.append("Approved Requirement Hash must contain unique REQ-ID:sha256 entries.")
            break
        hashes[match.group(1).upper()] = match.group(2).lower()
    by_id = {}
    for p in requirements:
        fields = requirement_fields(p)
        if fields["Requirement ID"] in by_id:
            reasons.append(f"Duplicate Notion requirement ID {fields['Requirement ID']}.")
        by_id[fields["Requirement ID"]] = p
    related = _related_ids(change)
    if not related:
        reasons.append("Change request must be linked to affected Notion requirements.")
    linked_requirements = [p for p in requirements
                           if str(p.get("id", "")).replace("-", "").lower() in related]
    related_ids = {requirement_fields(p)["Requirement ID"] for p in linked_requirements}
    if related_ids != req_refs:
        reasons.append(f"PR requirement IDs {sorted(req_refs)} must exactly match change scope {sorted(related_ids)}.")
    if set(hashes) != related_ids:
        reasons.append("Approved hashes must cover exactly all affected requirements.")
    for req_id in sorted(related_ids):
        page = by_id.get(req_id)
        if page is None:
            reasons.append(f"Requirement {req_id} was not found.")
            continue
        fields = requirement_fields(page)
        if _option(page, "Status") != "Approved":
            reasons.append(f"{req_id}: requirement lifecycle status is not Approved.")
        if not all(fields.values()):
            reasons.append(f"{req_id}: controlled fields are incomplete.")
        if hashes.get(req_id) != requirement_hash(fields):
            reasons.append(f"{req_id}: current revision differs from QARA-approved digest.")
    return {"allowed": not reasons, "change_id": f"CR-{change_num}",
            "requirements": sorted(req_refs), "reasons": reasons}


async def read_data_source(client: httpx.AsyncClient, data_source_id: str) -> list[dict]:
    """Read complete bounded data source or fail closed."""
    if not NOTION_ID.fullmatch(data_source_id):
        raise ValueError("Notion data source ID must be a UUID")
    rows: list[dict] = []
    cursor = None
    for _ in range(21):
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        response = await client.post(f"/v1/data_sources/{data_source_id}/query", json=body)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data.get("results"), list):
            raise ValueError("Invalid Notion data source response")
        rows.extend(data["results"])
        if len(rows) > MAX_RECORDS:
            raise ValueError("Too many Notion rows, refusing incomplete review")
        if not data.get("has_more"):
            return rows
        next_cursor = data.get("next_cursor")
        if not next_cursor or next_cursor == cursor:
            raise ValueError("Notion pagination ended unexpectedly")
        cursor = next_cursor
    raise ValueError("Notion pagination exceeded configured limit")


async def check_notion_gate(pr_body: str, requirements_source_id: str,
                            changes_source_id: str, notion_token: str) -> dict:
    if not notion_token:
        raise ValueError("NOTION_TOKEN is missing; development gate is closed.")
    headers = {"Authorization": f"Bearer {notion_token}",
               "Notion-Version": NOTION_API_VERSION, "Content-Type": "application/json"}
    async with httpx.AsyncClient(base_url="https://api.notion.com", headers=headers,
                                 follow_redirects=False, timeout=30.0) as client:
        changes = await read_data_source(client, changes_source_id)
        requirements = await read_data_source(client, requirements_source_id)
    return assess_development_gate(pr_body, changes, requirements)
