import pytest

from samd_traceability_mcp.notion import (
    analyze_notion_links,
    parse_notion_requirements,
    text_property,
)


def notion_row(identifier, name="Example requirement"):
    return {
        "url": "https://www.notion.so/example",
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": name}]},
            "Requirement ID": {
                "type": "rich_text", "rich_text": [{"plain_text": identifier}]
            },
        },
    }


def test_parse_notion_rows():
    rows = parse_notion_requirements([notion_row("REQ-AUTH-001")])
    assert len(rows) == 1
    assert rows[0]["id"] == "REQ-AUTH-001"
    assert rows[0]["title"] == "Example requirement"
    assert rows[0]["url"] == "https://www.notion.so/example"
    assert rows[0]["requirement_status"] == ""


def test_reject_duplicate_requirement_id():
    with pytest.raises(ValueError, match="Duplicate"):
        parse_notion_requirements([
            notion_row("REQ-AUTH-001"),
            notion_row("req-auth-001"),
        ])


def test_reject_invalid_id():
    with pytest.raises(ValueError, match="invalid Requirement ID"):
        parse_notion_requirements([notion_row("#12")])


def test_notion_matches_only_function_docstrings():
    reqs = parse_notion_requirements([
        notion_row("REQ-AUTH-001"),
        notion_row("REQ-AUTH-002"),
    ])
    source = '''
def test_login():
    """Requirement: REQ-AUTH-001"""
    sample = "Requirement: REQ-AUTH-002"
    assert True
'''
    result = analyze_notion_links(
        reqs,
        {"tests/test_login.py": source,
         "examples/test_example.py": 'def test_login():\n    """Requirement: REQ-AUTH-002"""\n    pass\n'},
        "example/app",
    )
    assert result["scanned_test_files"] == 1
    assert result["linked_count"] == 1
    assert result["unlinked_count"] == 1
    assert result["requirements"][0]["test_files"] == ["tests/test_login.py"]
    assert result["requirements"][1]["test_files"] == []


def test_notion_dangling_marker():
    reqs = parse_notion_requirements([notion_row("REQ-AUTH-001")])
    source = 'def test_other():\n    """Requirement: REQ-SEC-900"""\n    pass\n'
    result = analyze_notion_links(reqs, {"tests/test_other.py": source}, "example/app")
    assert result["references_to_unknown_requirement_ids"] == [
        {"id": "REQ-SEC-900", "test_files": ["tests/test_other.py"],
         "test_cases": [{"test_file": "tests/test_other.py",
                         "test_name": "test_other", "line": 1}]}
    ]


def test_notion_fails_closed_on_bad_python():
    with pytest.raises(ValueError, match="Cannot parse test file"):
        analyze_notion_links([], {"tests/test_bad.py": "def test_oops("}, "example/app")


def test_missing_property_stays_missing():
    assert text_property({}, "Requirement ID") == ""
