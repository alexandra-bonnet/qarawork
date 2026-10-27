"""Deterministic, bidirectional traceability matrix export for Notion requirements."""
from __future__ import annotations

import csv
import io
from urllib.parse import quote

COLUMNS = [
    "Record Type", "Requirement ID", "Requirement Title", "Notion URL",
    "Requirement Status", "Release", "Priority", "Description",
    "GitHub Test File", "Test Case", "GitHub Test URL", "Link Status",
    "Execution Status", "Evidence Level",
]


def _safe_cell(value: object) -> str:
    """Avoid spreadsheet formula interpretation when CSV is opened in Excel."""
    value = str(value if value is not None else "")
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def build_traceability_matrix(report: dict) -> dict:
    """Build a CSV matrix from an analyzed, read-only Notion/GitHub report.

    Each explicit link produces one row, unlinked requirements one row each,
    and references to unknown IDs one row per test file. No execution status
    is inferred from link presence or placeholder pytest fixtures.
    """
    repository = report["repository"]
    ref = report["ref"]
    records = []
    def test_url(path: str, name: str = "") -> str:
        if not path:
            return ""
        uri = (
            "https://github.com/" + repository + "/blob/"
            + quote(ref, safe="/") + "/" + quote(path, safe="/")
        )
        # GitHub anchors target the function definition line when available.
        return uri

    for requirement in report["requirements"]:
        cases = requirement.get("test_cases")
        if cases is None:
            # Backwards compatibility for reports generated before v0.4.
            cases = [{"test_file": path, "test_name": ""} for path in requirement["test_files"]]
        for case in cases or [{"test_file": "", "test_name": ""}]:
            path = case["test_file"]
            name = case.get("test_name", "")
            url = test_url(path, name)
            if url and isinstance(case.get("line"), int):
                url += "#L" + str(case["line"])
            records.append({
                "Record Type": "Requirement",
                "Requirement ID": requirement["id"],
                "Requirement Title": requirement["title"],
                "Notion URL": requirement["url"],
                "Requirement Status": requirement.get("requirement_status", ""),
                "Release": requirement.get("release", ""),
                "Priority": requirement.get("priority", ""),
                "Description": requirement.get("description", ""),
                "GitHub Test File": path,
                "Test Case": name,
                "GitHub Test URL": url,
                "Link Status": "Linked" if path else "Unlinked",
                "Execution Status": "Unknown",
                "Evidence Level": "Explicit marker only" if path else "No explicit marker found",
            })
    for unknown in sorted(report.get("references_to_unknown_requirement_ids", []), key=lambda i: i["id"]):
        cases = unknown.get("test_cases")
        if cases is None:
            cases = [{"test_file": path, "test_name": ""} for path in unknown["test_files"]]
        for case in cases:
            path = case["test_file"]
            url = test_url(path, case.get("test_name", ""))
            if url and isinstance(case.get("line"), int):
                url += "#L" + str(case["line"])
            records.append({
                "Record Type": "Unknown requirement reference",
                "Requirement ID": unknown["id"],
                "Requirement Title": "",
                "Notion URL": "",
                "Requirement Status": "",
                "Release": "",
                "Priority": "",
                "Description": "",
                "GitHub Test File": path,
                "Test Case": case.get("test_name", ""),
                "GitHub Test URL": url,
                "Link Status": "Unknown requirement ID",
                "Execution Status": "Unknown",
                "Evidence Level": "Explicit marker only",
            })
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow({key: _safe_cell(record[key]) for key in COLUMNS})
    return {
        "source": "Notion and GitHub",
        "repository": repository,
        "ref": ref,
        "notion_data_source_id": report["notion_data_source_id"],
        "requirements_count": report["requirements_count"],
        "linked_count": report["linked_count"],
        "unlinked_count": report["unlinked_count"],
        "unknown_reference_count": len(report.get("references_to_unknown_requirement_ids", [])),
        "row_count": len(records),
        "columns": COLUMNS,
        "rows": records,
        "csv": out.getvalue(),
        "file_name_suggestion": "requirements_traceability_matrix.csv",
        "execution_status_policy": "Unknown for every row; no CI execution evidence collected",
        "limitations": report.get("limitations", []),
    }
