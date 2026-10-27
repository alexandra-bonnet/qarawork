"""Tests for the fail-closed QARA development gate."""
from __future__ import annotations

import copy

from samd_traceability_mcp.dev_gate import assess_development_gate, requirement_hash


def prop_text(value: str) -> dict:
    return {"type": "rich_text", "rich_text": [{"plain_text": value}]}


def requirement():
    return {"id": "a" * 32, "properties": {
        "Requirement ID": prop_text("REQ-DEM-001"),
        "Name": {"type": "title", "title": [{"plain_text": "Freshness indicator"}]},
        "Description": prop_text("Display stale readings"),
        "Release": {"type": "select", "select": {"name": "R1"}},
        "Status": {"type": "select", "select": {"name": "Approved"}},
    }}


def change(req):
    fields = {"Requirement ID": "REQ-DEM-001", "Name": "Freshness indicator",
              "Description": "Display stale readings", "Release": "R1"}
    return {"properties": {
        "Change ID": {"type": "unique_id", "unique_id": {"number": 100}},
        "Decision Status": {"type": "status", "status": {"name": "Approved"}},
        "Development Authorization": {"type": "select", "select": {"name": "Authorized"}},
        "Regulatory Classification": {"type": "select", "select": {"name": "Non-substantial"}},
        "Review Outcome": {"type": "select", "select": {"name": "Re-verification needed"}},
        "Decision Rationale": prop_text("QARA assessed risk and verification impact"),
        "Approver": {"type": "people", "people": [{"id": "qara-reviewer"}]},
        "Approved At": {"type": "date", "date": {"start": "2026-10-25"}},
        "Approved Requirement Hash": prop_text("REQ-DEM-001:" + requirement_hash(fields)),
        "Affected Requirements": {"type": "relation", "relation": [{"id": req["id"]}]},
    }}


BODY = "Change: CR-100\nRequirements: REQ-DEM-001"


def check(req=None, cr=None, body=BODY):
    req = req or requirement()
    cr = cr or change(req)
    return assess_development_gate(body, [cr], [req])


def test_approved_exact_revision_allows_development():
    assert check()["allowed"] is True


def test_draft_or_missing_human_review_fails():
    r = requirement()
    r["properties"]["Status"]["select"]["name"] = "Draft"
    assert not check(req=r)["allowed"]
    r = requirement()
    c = change(r)
    c["properties"]["Approver"]["people"] = []
    assert not check(r, c)["allowed"]


def test_any_approved_requirement_edit_invalidates_gate():
    r = requirement()
    c = change(r)
    r["properties"]["Description"]["rich_text"][0]["plain_text"] = "Changed after approval"
    result = check(r, c)
    assert not result["allowed"]
    assert "differs" in " ".join(result["reasons"])


def test_status_approved_without_authorization_still_blocks():
    r = requirement()
    c = change(r)
    c["properties"]["Development Authorization"]["select"]["name"] = "Blocked"
    assert not check(r, c)["allowed"]


def test_missing_classification_and_pending_assessment_block():
    r = requirement()
    c = change(r)
    c["properties"]["Regulatory Classification"]["select"]["name"] = "Pending assessment"
    c["properties"]["Review Outcome"]["select"]["name"] = "Pending"
    assert not check(r, c)["allowed"]


def test_missing_change_or_wrong_requirement_fails():
    assert not check(body="REQ-DEM-001")["allowed"]
    assert not check(body="CR-100 REQ-DEM-002")["allowed"]


def test_duplicate_or_missing_hashes_fail():
    r = requirement()
    c = change(r)
    c["properties"]["Approved Requirement Hash"] = prop_text("")
    assert not check(r, c)["allowed"]
    c["properties"]["Approved Requirement Hash"] = prop_text("REQ-DEM-001:" + "0" * 64)
    assert not check(r, c)["allowed"]


def test_missing_impact_rationale_or_approval_date_fail():
    r = requirement()
    c = change(r)
    c["properties"]["Decision Rationale"] = prop_text("")
    c["properties"]["Approved At"]["date"] = None
    assert not check(r, c)["allowed"]
