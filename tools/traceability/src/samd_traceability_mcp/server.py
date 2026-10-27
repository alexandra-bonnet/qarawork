"""MCP stdio entrypoint."""
from __future__ import annotations
from mcp.server.fastmcp import FastMCP
from .github import inspect_repository
from .notion import inspect_notion_traceability
from .matrix import build_traceability_matrix
from .excel import make_xlsx_response
from .ci import fetch_ci_evidence, enrich_matrix_with_ci
from .ai_change import read_change_context, save_ai_draft

mcp = FastMCP("SaMD Traceability MCP")

@mcp.tool()
async def find_uncovered_requirements(repository: str, ref: str | None = None) -> dict:
    """Read requirements labeled 'requirement' and Python tests in a GitHub repository.

    Report explicit Requirement: #123 links, missing links and dangling references.
    Read-only. Does not establish test adequacy, execution, or regulatory compliance.

    Args:
        repository: GitHub repository in owner/name form.
        ref: Optional branch name; defaults to repository default branch.
    """
    return await inspect_repository(repository, ref)

@mcp.tool()
async def find_uncovered_notion_requirements(
    repository: str, notion_data_source_id: str, ref: str | None = None
) -> dict:
    """Read Notion requirement rows and link them to GitHub Python test docstrings.

    Requires NOTION_TOKEN and GITHUB_TOKEN in the local MCP server process.
    Both integrations need read access only. This tool never changes source data.

    Args:
        repository: GitHub owner/name repository to scan for Python test files.
        notion_data_source_id: Notion data source UUID, not the parent database UUID.
        ref: Optional GitHub branch name, defaults to the default branch.
    """
    return await inspect_notion_traceability(repository, notion_data_source_id, ref)


@mcp.tool()
async def export_notion_traceability_matrix(
    repository: str, notion_data_source_id: str, ref: str | None = None
) -> dict:
    """Return an English bidirectional Notion/GitHub traceability matrix and CSV.

    The returned CSV text can be saved locally by the user or their MCP client.
    This tool never writes files, edits requirements, or infers test execution.
    Requirements without links and unknown requirement references are both
    reported. Execution status remains Unknown until reliable CI evidence exists.

    Args:
        repository: GitHub owner/name repository containing Python tests.
        notion_data_source_id: Notion data source UUID.
        ref: GitHub branch to scan (defaults to repository default branch).
    """
    report = await inspect_notion_traceability(repository, notion_data_source_id, ref)
    return build_traceability_matrix(report)


@mcp.tool()
async def export_notion_traceability_excel(
    repository: str, notion_data_source_id: str, ref: str | None = None,
    include_ci: bool = False
) -> dict:
    """Return a formatted, filterable Excel workbook as base64 encoded XLSX bytes.

    Includes exact Python test function names, requirements metadata, source
    hyperlinks and an overview sheet. Requires a client to save the returned
    bytes locally. Notion/GitHub read-only, execution status always Unknown.
    """
    report = await inspect_notion_traceability(repository, notion_data_source_id, ref)
    matrix = build_traceability_matrix(report)
    if include_ci:
        evidence = await fetch_ci_evidence(repository, report["ref"])
        matrix = enrich_matrix_with_ci(matrix, evidence)
    return make_xlsx_response(matrix)



@mcp.tool()
async def prepare_ai_change_control(change_id: int) -> dict:
    """Retrieve exact, bounded Notion evidence to let the MCP host AI propose
    a structured impact-analysis DRAFT. Never decides substantiality, approves
    QARA review, changes statuses, or authorizes development.

    Args:
        change_id: Numeric change identifier in the configured source.
    """
    return await read_change_context(change_id)


@mcp.tool()
async def save_ai_change_control_draft(
    change_id: int, source_fingerprint: str,
    summary: str, regulatory_questions: str, risk_impact: str,
    verification_impact: str, source_links: str, missing_evidence: str,
    confirm_write: bool = False,
) -> dict:
    """Save ONLY AI Draft fields to an undecided change record.

    Requires a fresh fingerprint from prepare_ai_change_control and explicit
    confirm_write=True. NOTION_TOKEN needs write access; approval and QARA
    authorization fields are NEVER changed. An AI draft is not an approval.
    """
    draft = {
        "summary": summary,
        "regulatory_questions": regulatory_questions,
        "risk_impact": risk_impact,
        "verification_impact": verification_impact,
        "source_links": source_links,
        "missing_evidence": missing_evidence,
    }
    return await save_ai_draft(change_id, source_fingerprint, draft, confirm_write)


def main() -> None:
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
