"""AI change drafts remain unapproved and revision-bound."""
import asyncio
import pytest
from samd_traceability_mcp.ai_change import prepare_change_context, validate_ai_draft, save_ai_draft

def text(value):
    return {"type":"rich_text","rich_text":[{"plain_text":value}]}

def fixtures():
    requirement={"id":"a"*32,"url":"https://notion.so/"+"a"*32,"properties":{
        "Requirement ID":text("REQ-DEM-001"),
        "Name":{"type":"title","title":[{"plain_text":"Freshness indicator"}]},
        "Description":text("Display stale measurement"),
        "Release":{"select":{"name":"R1"}},
        "Status":{"select":{"name":"Approved"}}}}
    change={"id":"b"*32,"url":"https://notion.so/"+"b"*32,"properties":{
        "Change ID":{"unique_id":{"number":1}},
        "Decision Status":{"status":{"name":"Proposed"}},
        "Change Description":text("Change freshness threshold"),
        "Reason / Justification":text("PO proposal"),
        "Affected Requirements":{"relation":[{"id":"a"*32}]}}}
    return change,requirement

def draft():
    return {"summary":"Potential freshness display change",
        "regulatory_questions":"QARA to assess substantiality for applicable regulatory framework",
        "risk_impact":"Possible hazard: clinician interprets stale measurement",
        "verification_impact":"Review boundary-value and error-state test coverage",
        "source_links":"https://notion.so/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "missing_evidence":"Risk file and actual verification suite not provided"}

def test_preparation_produces_versioned_sources():
    c,r=fixtures()
    result=prepare_change_context(1,[c],[r])
    assert result["requirements"][0]["Requirement ID"]=="REQ-DEM-001"
    assert len(result["source_fingerprint"])==64
    r["properties"]["Description"]["rich_text"][0]["plain_text"]="Changed without approval"
    assert prepare_change_context(1,[c],[r])["source_fingerprint"]!=result["source_fingerprint"]

def test_po_description_change_invalidates_draft():
    c,r=fixtures()
    before=prepare_change_context(1,[c],[r])["source_fingerprint"]
    c["properties"]["Change Description"]["rich_text"][0]["plain_text"]="New change"
    assert prepare_change_context(1,[c],[r])["source_fingerprint"]!=before

def test_no_editing_after_approval():
    c,r=fixtures()
    c["properties"]["Decision Status"]["status"]["name"]="Approved"
    with pytest.raises(ValueError):
        prepare_change_context(1,[c],[r])

def test_missing_or_inaccessible_requirements_rejected():
    c,r=fixtures()
    with pytest.raises(ValueError):
        prepare_change_context(1,[c],[])

def test_draft_cannot_include_qara_authorization():
    val=draft()
    val["Development Authorization"]="Authorized"
    with pytest.raises(ValueError):
        validate_ai_draft(val)
    val=draft()
    val["summary"]=""
    with pytest.raises(ValueError):
        validate_ai_draft(val)

def test_draft_write_requires_explicit_confirmation():
    result=asyncio.run(save_ai_draft(1,"a"*64,draft(),False))
    assert result["saved"] is False
