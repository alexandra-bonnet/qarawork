"""Evidence-grounded, human-reviewed AI change-control drafts.

This module does not itself call an LLM. The MCP host
writes the proposed narrative from bounded read-only source evidence.
Only explicitly AI-prefixed fields may be updated; QARA decisions are immutable
to this tool. Every write is rejected on stale requirement revisions.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

import httpx

from .dev_gate import read_data_source, requirement_fields, requirement_hash, _related_ids, _option
from .notion import NOTION_API_VERSION, NOTION_ID, text_property

REQUIREMENTS_DS = os.getenv("QARAWORK_REQUIREMENTS_DATA_SOURCE_ID", "")
CHANGES_DS = os.getenv("QARAWORK_CHANGES_DATA_SOURCE_ID", "")
DRAFT_FIELDS = {
    "summary": "AI Draft Summary",
    "regulatory_questions": "AI Draft Regulatory Questions",
    "risk_impact": "AI Draft Risk Impact",
    "verification_impact": "AI Draft Verification Impact",
    "source_links": "AI Draft Source Links",
    "missing_evidence": "AI Draft Missing Evidence",
}
MAX_FIELD = 1600


def _record_number(page: dict) -> int | None:
    return (page.get("properties", {}).get("Change ID", {}).get("unique_id") or {}).get("number")


def prepare_change_context(change_id: int, changes: list[dict],
                           requirements: list[dict]) -> dict:
    """Provide bounded, exact source facts, explicitly not regulatory conclusions."""
    if not isinstance(change_id, int) or not 0 < change_id < 100000000:
        raise ValueError("Invalid change ID")
    matches = [page for page in changes if _record_number(page) == change_id]
    if len(matches) != 1:
        raise ValueError("Expected exactly one change record")
    change = matches[0]
    if _option(change, "Decision Status") in {"Approved", "Rejected", "Closed"}:
        raise ValueError("Change is already decided; do not generate an editable draft")
    related = _related_ids(change)
    linked = [page for page in requirements
              if str(page.get("id", "")).replace("-", "").lower() in related]
    if not related or len(linked) != len(related):
        raise ValueError("Linked requirements are missing or inaccessible")
    rows = []
    for page in sorted(linked, key=lambda p: requirement_fields(p)["Requirement ID"]):
        fields = requirement_fields(page)
        if not all(fields.values()):
            raise ValueError("One or more controlled requirement fields are incomplete")
        rows.append({
            **fields,
            "status": _option(page, "Status"),
            "url": page.get("url", ""),
            "revision_sha256": requirement_hash(fields),
        })
    props = change.get("properties", {})
    change_description = text_property(props, "Change Description")
    justification = text_property(props, "Reason / Justification")
    if not change_description.strip():
        raise ValueError("Missing PO change description")
    canonical = {"change_id": change_id, "change_description": change_description,
                 "justification": justification,
                 "requirements": [{key: row[key] for key in
                     ("Requirement ID", "Name", "Description", "Release", "revision_sha256")} for row in rows]}
    fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True,
                             ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return {
        "change_id": f"CR-{change_id}",
        "change_page_id": change["id"],
        "change_url": change.get("url", ""),
        "change_description": change_description,
        "reason": justification,
        "regulatory_classification": _option(change, "Regulatory Classification") or "Pending assessment",
        "requirements": rows,
        "source_fingerprint": fingerprint,
        "instructions": (
            "Draft ONLY, not a QARA decision. Distinguish documented facts from "
            "hypotheses. Explain substantial-change classification as questions "
            "for a human reviewer, not as a categorical decision. Evaluate "
            "possible risk management, verification, validation, usability, "
            "clinical and security impacts. Cite only available source URLs "
            "and list gaps. Never invent existing tests, risk records or "
            "regulatory approval. Output keys: summary, regulatory_questions, "
            "risk_impact, verification_impact, source_links, missing_evidence."
        ),
        "limitations": [
            "No risk-management, test or clinical records are supplied by this context tool.",
            "An AI draft cannot authorize development or qualify regulatory substantiality.",
            "A QARA reviewer must confirm all impact conclusions and evidence.",
        ],
    }


def validate_ai_draft(draft: dict) -> dict[str, str]:
    if not isinstance(draft, dict) or set(draft) != set(DRAFT_FIELDS):
        raise ValueError("Draft must contain exactly the six allowed AI draft fields")
    result = {}
    for key in DRAFT_FIELDS:
        value = draft[key]
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_FIELD:
            raise ValueError(f"Invalid or oversized AI draft field: {key}")
        result[key] = value.strip()
    if not any(token in result["regulatory_questions"].lower()
               for token in ("review", "assess", "confirm", "verify", "determine", "évalu", "revue")):
        raise ValueError("Regulatory classification must be framed for reviewer assessment")
    return result


async def _notion_client():
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError("NOTION_TOKEN is required")
    headers = {"Authorization": f"Bearer {token}",
               "Notion-Version": NOTION_API_VERSION,
               "Content-Type": "application/json"}
    return httpx.AsyncClient(base_url="https://api.notion.com", headers=headers,
                             timeout=30.0, follow_redirects=False)


async def read_change_context(change_id: int) -> dict:
    if not REQUIREMENTS_DS or not CHANGES_DS:
        raise ValueError("Configure QARAWORK_REQUIREMENTS_DATA_SOURCE_ID and QARAWORK_CHANGES_DATA_SOURCE_ID")
    async with await _notion_client() as client:
        changes = await read_data_source(client, CHANGES_DS)
        requirements = await read_data_source(client, REQUIREMENTS_DS)
    return prepare_change_context(change_id, changes, requirements)


async def save_ai_draft(change_id: int, source_fingerprint: str,
                        draft: dict, confirm_write: bool = False) -> dict:
    """Only AI Draft fields; no QARA status/approval/authorization writes."""
    clean = validate_ai_draft(draft)
    if not re.fullmatch(r"[0-9a-f]{64}", source_fingerprint):
        raise ValueError("Expected a SHA256 source fingerprint")
    if confirm_write is not True:
        return {"saved": False, "reason": "Explicit confirm_write=true required",
                "fields": clean}
    async with await _notion_client() as client:
        changes = await read_data_source(client, CHANGES_DS)
        requirements = await read_data_source(client, REQUIREMENTS_DS)
        context = prepare_change_context(change_id, changes, requirements)
        if context["source_fingerprint"] != source_fingerprint:
            raise ValueError("Source changed since the AI draft was prepared; regenerate")
        props = {
            notion_field: {"rich_text": [{"text": {"content": clean[key]}}]}
            for key, notion_field in DRAFT_FIELDS.items()
        }
        props["AI Draft Status"] = {"select": {"name": "AI Draft - pending QARA review"}}
        props["AI Draft Revision Hash"] = {
            "rich_text": [{"text": {"content": source_fingerprint}}]
        }
        response = await client.patch(
            f"/v1/pages/{context['change_page_id']}", json={"properties": props}
        )
        response.raise_for_status()
    return {"saved": True, "change_id": context["change_id"],
            "change_url": context["change_url"],
            "status": "AI Draft - pending QARA review",
            "qara_approved": False, "development_authorized": False}
