"""Read real GitHub PR activity through the official REST API (read-only).

The issue timeline and PR review APIs expose GitHub-reported observations.
They are not an independently retained, append-only audit trail.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
import httpx

OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
REPO_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
MAX_PAGES = 5
SUPPORTED_EVENTS = frozenset({
    "assigned", "unassigned", "labeled", "unlabeled", "closed", "reopened",
    "merged", "renamed", "review_requested", "review_request_removed",
    "ready_for_review", "convert_to_draft", "committed", "head_ref_force_pushed",
    "base_ref_changed", "head_ref_deleted", "head_ref_restored",
})


def _timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("GitHub event missing timestamp.")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("GitHub event timestamp malformed.") from exc
    if dt.tzinfo is None:
        raise ValueError("GitHub event timestamp missing timezone.")
    return value


def _optional_timeline_timestamp(value: object) -> str | None:
    """A timeline observation may not provide created_at.

    Preserve it as undated, but reject a malformed date if one is provided.
    """
    if value is None:
        return None
    return _timestamp(value)


def _actor(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    login = value.get("login")
    return login if isinstance(login, str) and login else None


def _timeline_event(item: dict) -> dict:
    if not isinstance(item, dict) or not isinstance(item.get("event"), str):
        raise ValueError("Malformed GitHub timeline event.")
    event = item["event"]
    event_id = item.get("id")
    if event_id is None:
        # Some event variants have opaque node_id only.
        event_id = item.get("node_id")
    return {
        "source": "github_issue_timeline",
        "event_id": str(event_id) if event_id is not None else None,
        "event_type": event,
        "occurred_at": _optional_timeline_timestamp(item.get("created_at")),
        "actor_login": _actor(item.get("actor")),
        "github_url": item.get("html_url") if isinstance(item.get("html_url"), str) else None,
        "commit_sha": item.get("sha") if isinstance(item.get("sha"), str) else (
            item.get("commit_id") if isinstance(item.get("commit_id"), str) else None
        ),
        "supported_event_type": event in SUPPORTED_EVENTS,
    }


def _review_event(item: dict) -> dict:
    if not isinstance(item, dict) or not isinstance(item.get("state"), str):
        raise ValueError("Malformed GitHub pull-request review.")
    return {
        "source": "github_pull_review",
        "event_id": str(item["id"]) if item.get("id") is not None else None,
        "event_type": "review:" + item["state"].lower(),
        "occurred_at": _timestamp(item.get("submitted_at")),
        "actor_login": _actor(item.get("user")),
        "github_url": item.get("html_url") if isinstance(item.get("html_url"), str) else None,
        "commit_sha": item.get("commit_id") if isinstance(item.get("commit_id"), str) else None,
        "supported_event_type": True,
    }


async def inspect_github_pr_history(
    repository: str, pr_number: int, *,
    github_token: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """Retrieve provider-reported PR, issue timeline and submitted reviews.

    Missing authentication, inaccessible endpoints, malformed responses, or
    pagination beyond bounds raise errors rather than implying 'no events'.
    """
    if not isinstance(repository, str) or repository.count("/") != 1:
        raise ValueError("repository must have owner/name form.")
    owner, name = repository.split("/")
    if not OWNER_RE.fullmatch(owner) or not REPO_RE.fullmatch(name) or name in {".", ".."}:
        raise ValueError("Invalid GitHub repository name.")
    if isinstance(pr_number, bool) or not isinstance(pr_number, int) or not 1 <= pr_number <= 100000000:
        raise ValueError("pr_number must be a positive integer.")
    token = github_token if github_token is not None else os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN required; do not return an unauthenticated partial history.")
    prefix = f"/repos/{owner}/{name}"
    async with httpx.AsyncClient(
        base_url="https://api.github.com", timeout=30, follow_redirects=False,
        transport=transport,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    ) as client:
        response = await client.get(f"{prefix}/pulls/{pr_number}")
        response.raise_for_status()
        pr = response.json()
        if not isinstance(pr, dict) or pr.get("number") != pr_number:
            raise ValueError("GitHub did not return the requested PR.")
        actual_repo = (pr.get("base") or {}).get("repo") or {}
        if not isinstance(actual_repo, dict) or actual_repo.get("full_name", "").lower() != repository.lower():
            raise ValueError("GitHub PR repository identity mismatch.")

        async def pages(path: str) -> list[dict]:
            items: list[dict] = []
            for page in range(1, MAX_PAGES + 1):
                res = await client.get(path, params={"per_page": 100, "page": page})
                res.raise_for_status()
                batch = res.json()
                if not isinstance(batch, list) or any(not isinstance(x, dict) for x in batch):
                    raise ValueError("Malformed GitHub event-page response.")
                items.extend(batch)
                if len(batch) < 100:
                    return items
            raise ValueError("GitHub history exceeds supported page limit; refusing partial report.")

        timeline = await pages(f"{prefix}/issues/{pr_number}/timeline")
        reviews = await pages(f"{prefix}/pulls/{pr_number}/reviews")

        observations = [_timeline_event(x) for x in timeline]
    # PENDING reviews have no submitted_at; not an auditable submitted review.
        for review in reviews:
            if review.get("submitted_at") is not None:
                observations.append(_review_event(review))
        from .github_commits import enrich_commit_observations
        commits_unavailable = await enrich_commit_observations(client, prefix, observations)
    # A missing timestamp is not the same as a missing event. Keep those
    # observations, clearly separated after the dated chronological subset.
    observations.sort(key=lambda x: (
        x["occurred_at"] is None, x["occurred_at"] or "",
        x["source"], str(x["event_id"]),
    ))
    undated = sum(x["occurred_at"] is None for x in observations)
    unsupported = sum(not x["supported_event_type"] for x in observations)
    anonymous = sum(x["actor_login"] is None for x in observations)
    return {
        "repository": repository,
        "pr_number": pr_number,
        "pr_url": pr.get("html_url"),
        "pr_title": pr.get("title"),
        "pr_state": pr.get("state"),
        "pr_merged": pr.get("merged") is True,
        "pr_created_at": _timestamp(pr.get("created_at")),
        "pr_author_login": _actor(pr.get("user")),
        "observations": observations,
        "observations_count": len(observations),
        "unknown_event_types_count": unsupported,
        "events_without_timestamp_count": undated,
        "commit_metadata_unavailable_count": commits_unavailable,
        "all_events_chronologically_orderable": undated == 0,
        "events_without_actor_count": anonymous,
        "source": "github_rest_api",
        "read_only": True,
        "provider_records_retrieved": True,
        "actor_identity_verified": False,
        "complete_audit_trail_verified": False,
        "event_provenance_independently_verified": False,
        "independent_retention_verified": False,
        "authorized_for_use": False,
        "next_action": (
            "Investigate undated observations, unknown event types and missing actor information; "
            "corroborate against independently retained records."
            if unsupported or anonymous or undated or commits_unavailable else
            "Corroborate GitHub-reported activity against independently retained records."
        ),
        "notice": (
            "These are real GitHub-reported issue timeline and submitted PR review records, "
            "not a verified complete edit history. Event coverage depends on GitHub's "
            "endpoints and permissions. Commit author/committer dates are separate "
            "metadata and do not establish timeline event time. Undated events appear after dated events and "
            "cannot be placed reliably in chronological order. Actor login is provider-reported, not an "
            "independently verified person or QARA approval. No immutable storage."
        ),
    }
