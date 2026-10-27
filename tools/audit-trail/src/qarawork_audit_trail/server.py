"""QARAWORK Audit Trail: read-only observations and honest evidence-gap checks."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .notion_activity import read_notion_page_activity
from .events import review_event_sequence as assess_sequence
from .github_activity import inspect_github_pr_history as read_github_pr_history
from .evidence_capture import verify_evidence
import os

mcp = FastMCP("QARAWORK Audit Trail")


@mcp.tool()
async def inspect_notion_page_activity(page_id: str) -> dict:
    """Read Notion's creation and latest-edit metadata for one page.

    Does NOT retrieve a complete edit history or authenticate the user behind
    Notion's reported user identifier. Read-only Notion API access.
    """
    return await read_notion_page_activity(page_id)


@mcp.tool()
def review_event_sequence(events: list[dict], expected_object_id: str) -> dict:
    """Check caller-supplied event sequence for gaps and inconsistencies.

    These are not verified provider audit events. No event list can independently
    demonstrate completeness, actual identity or immutable preservation.
    """
    return assess_sequence(events, expected_object_id=expected_object_id)



@mcp.tool()
async def inspect_github_pr_history(repository: str, pr_number: int) -> dict:
    """Retrieve real GitHub issue-timeline and PR-review observations.

    Provider-reported actors and events are not independent identity proof,
    an exhaustive audit log, or regulatory approval. Read-only.
    """
    return await read_github_pr_history(repository, pr_number)


@mcp.tool()
def verify_audit_evidence_capture(capture_id: str) -> dict:
    """Verify saved GitHub evidence bytes against a local SHA-256 manifest.

    Offline and read-only. Requires QARAWORK_AUDIT_CAPTURE_ROOT. This cannot
    authenticate the local manifest, guarantee immutable retention, or approve.
    """
    root = os.getenv("QARAWORK_AUDIT_CAPTURE_ROOT")
    if not root:
        raise ValueError("QARAWORK_AUDIT_CAPTURE_ROOT is required.")
    return verify_evidence(root, capture_id)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
