"""Read-only enrichment of GitHub commit observations.

Git author/committer timestamps describe commit metadata, NOT the time of
the corresponding issue-timeline event. Never fill occurred_at with them.
"""
from __future__ import annotations

import re
import httpx

SHA = re.compile(r"[0-9a-fA-F]{40}\Z")
MAX_COMMITS = 50


def _metadata(payload: object, expected_sha: str) -> dict:
    if not isinstance(payload, dict) or payload.get("sha", "").lower() != expected_sha.lower():
        raise ValueError("GitHub commit SHA does not match requested SHA.")
    commit = payload.get("commit")
    if not isinstance(commit, dict):
        raise ValueError("GitHub commit metadata is malformed.")
    from .github_activity import _timestamp, _actor
    author = commit.get("author")
    committer = commit.get("committer")
    if not isinstance(author, dict) or not isinstance(committer, dict):
        raise ValueError("GitHub commit author/committer metadata is malformed.")
    return {
        "status": "available",
        "commit_sha": expected_sha,
        "author_date": _timestamp(author.get("date")),
        "committer_date": _timestamp(committer.get("date")),
        "git_author_name": author.get("name") if isinstance(author.get("name"), str) else None,
        "git_committer_name": committer.get("name") if isinstance(committer.get("name"), str) else None,
        "github_author_login": _actor(payload.get("author")),
        "github_committer_login": _actor(payload.get("committer")),
        "date_scope": "commit_metadata_not_timeline_event",
        "actor_identity_verified": False,
    }


async def enrich_commit_observations(client: httpx.AsyncClient, prefix: str, observations: list[dict]) -> int:
    """Enrich unique committed-event SHAs, preserving provider timeline fields.

    Inaccessible commit metadata is clearly reported per observation; it does
    not make the previously retrieved timeline disappear or create a timestamp.
    """
    unique = {
        e["commit_sha"] for e in observations
        if e.get("event_type") == "committed" and isinstance(e.get("commit_sha"), str)
    }
    if len(unique) > MAX_COMMITS:
        raise ValueError("Too many distinct commits to enrich safely.")
    records = {}
    for sha in sorted(unique):
        if not SHA.fullmatch(sha):
            records[sha] = {"status": "invalid_sha", "commit_sha": sha}
            continue
        try:
            response = await client.get(f"{prefix}/commits/{sha}")
            response.raise_for_status()
            records[sha] = _metadata(response.json(), sha)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            # Do not leak authorization headers or response content.
            records[sha] = {"status": "unavailable", "commit_sha": sha,
                            "reason": type(exc).__name__}
    for event in observations:
        if event.get("event_type") == "committed":
            sha = event.get("commit_sha")
            event["commit_metadata"] = records.get(sha, {
                "status": "missing_sha", "commit_sha": sha,
            })
    return sum(
        1 for event in observations
        if event.get("event_type") == "committed"
        and event["commit_metadata"]["status"] != "available"
    )
