import csv
import io

from samd_traceability_mcp.matrix import build_traceability_matrix


def report():
    return {
        "repository": "example-org/example-repo",
        "ref": "test/notion-e2e-demo-fixtures",
        "notion_data_source_id": "00000000-0000-4000-8000-000000000001",
        "requirements_count": 2,
        "linked_count": 1,
        "unlinked_count": 1,
        "requirements": [
            {
                "id": "REQ-DEM-001", "title": "Display sample measurement",
                "url": "https://www.notion.so/example", "test_files": [
                    "tests/test_sample.py", "tests/test_clinician.py",
                ],
            },
            {
                "id": "REQ-DEM-002", "title": "Missing link",
                "url": "https://www.notion.so/missing", "test_files": [],
            },
        ],
        "references_to_unknown_requirement_ids": [
            {"id": "REQ-OLD-099", "test_files": ["tests/test_retired.py"]}
        ],
        "limitations": ["Only explicit links are checked."],
    }


def test_bidirectional_csv_has_linked_unlinked_and_unknown_rows():
    result = build_traceability_matrix(report())
    assert result["requirements_count"] == 2
    assert result["row_count"] == 4
    assert result["unknown_reference_count"] == 1
    rows = list(csv.DictReader(io.StringIO(result["csv"])))
    assert len(rows) == 4
    assert [r["Link Status"] for r in rows] == [
        "Linked", "Linked", "Unlinked", "Unknown requirement ID",
    ]
    assert [r["Execution Status"] for r in rows] == ["Unknown"] * 4
    assert rows[2]["GitHub Test URL"] == ""
    assert {rows[0]["GitHub Test File"], rows[1]["GitHub Test File"]} == {
        "tests/test_sample.py", "tests/test_clinician.py"
    }
    assert rows[0]["GitHub Test URL"] == (
        "https://github.com/example-org/example-repo/"
        "blob/test/notion-e2e-demo-fixtures/tests/test_sample.py"
    )


def test_csv_escaping_and_formula_sanitization():
    data = report()
    data["requirements"][0]["title"] = '=HYPERLINK("https://bad.example","click"), "text"'
    result = build_traceability_matrix(data)
    rows = list(csv.DictReader(io.StringIO(result["csv"])))
    assert rows[0]["Requirement Title"].startswith("'=HYPERLINK")
    assert rows[0]["Requirement Title"] == "'" + data["requirements"][0]["title"]
    assert len(rows) == 4


def test_no_dangling_marker_rows_if_none():
    data = report()
    data["references_to_unknown_requirement_ids"] = []
    result = build_traceability_matrix(data)
    assert result["unknown_reference_count"] == 0
    assert result["row_count"] == 3
