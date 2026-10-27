"""Synthetic GitHub REST adapter tests: provider records, pagination, fail-closed."""
import httpx
import pytest

from qarawork_audit_trail.github_activity import inspect_github_pr_history

REPO = "example-org/example-repo"
PR = 39


def pull():
    return {
        "number": PR, "title": "Audit Trail", "state": "closed",
        "merged": True, "html_url": "https://github.com/example-org/example-repo/pull/123",
        "created_at": "2026-10-26T13:00:00Z",
        "user": {"login": "example-user"},
        "base": {"repo": {"full_name": REPO}},
    }


def timeline():
    return [{
        "event": "merged", "id": 510, "created_at": "2026-10-26T13:30:00Z",
        "actor": {"login": "example-user"}, "commit_id": "a" * 40,
    }, {
        "event": "review_requested", "id": 507,
        "created_at": "2026-10-26T13:05:00Z",
        "actor": {"login": "alice"},
    }]


def reviews():
    return [{
        "id": 44, "state": "APPROVED", "submitted_at": "2026-10-26T13:20:00Z",
        "user": {"login": "bob"}, "commit_id": "b" * 40,
    }]


def mocked(timeline_data=None, reviews_data=None, fail_path=None):
    calls = []
    def handler(req):
        calls.append((req.method, req.url.path, dict(req.url.params)))
        assert req.method == "GET"
        assert req.headers["authorization"] == "Bearer synthetic"
        assert req.headers["accept"] == "application/vnd.github+json"
        path = req.url.path
        if fail_path and path.endswith(fail_path):
            return httpx.Response(403)
        if path.endswith("/pulls/39"):
            return httpx.Response(200, json=pull())
        if path.endswith("/issues/39/timeline"):
            return httpx.Response(200, json=timeline() if timeline_data is None else timeline_data)
        if path.endswith("/pulls/39/reviews"):
            return httpx.Response(200, json=reviews() if reviews_data is None else reviews_data)
        if "/commits/" in path:
            sha = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={
                "sha": sha,
                "commit": {
                    "author": {"name": "Demo author", "date": "2026-10-26T12:10:00Z"},
                    "committer": {"name": "Demo committer", "date": "2026-10-26T12:11:00Z"},
                },
                "author": {"login": "demo-author"},
                "committer": {"login": "demo-committer"},
            })
        raise AssertionError(path)
    return httpx.MockTransport(handler), calls


@pytest.mark.asyncio
async def test_real_provider_shape_and_chronology_not_faked_completeness():
    transport, calls = mocked()
    r = await inspect_github_pr_history(REPO, PR, github_token="synthetic", transport=transport)
    assert len(calls) == 3
    assert r["pr_merged"] is True
    assert r["observations_count"] == 3
    assert [x["event_type"] for x in r["observations"]] == [
        "review_requested", "review:approved", "merged"
    ]
    assert r["observations"][1]["actor_login"] == "bob"
    assert r["observations"][1]["source"] == "github_pull_review"
    assert r["actor_identity_verified"] is False
    assert r["complete_audit_trail_verified"] is False
    assert r["independent_retention_verified"] is False
    assert r["authorized_for_use"] is False


@pytest.mark.asyncio
async def test_unknown_event_and_absent_actor_are_visible():
    x = timeline()
    x[0]["event"] = "new-provider-event"
    x[0]["actor"] = None
    r = await inspect_github_pr_history(
        REPO, PR, github_token="synthetic", transport=mocked(timeline_data=x)[0],
    )
    assert r["unknown_event_types_count"] == 1
    assert r["events_without_actor_count"] == 1
    assert r["observations"][2]["supported_event_type"] is False
    assert "unknown" in r["next_action"].lower()


@pytest.mark.asyncio
async def test_no_reviews_does_not_create_fake_review_events():
    r = await inspect_github_pr_history(
        REPO, PR, github_token="synthetic", transport=mocked(reviews_data=[])[0],
    )
    assert r["observations_count"] == 2
    assert not any(x["source"] == "github_pull_review" for x in r["observations"])


@pytest.mark.asyncio
async def test_forbidden_review_endpoint_is_error_not_clean_history():
    with pytest.raises(httpx.HTTPStatusError):
        await inspect_github_pr_history(
            REPO, PR, github_token="synthetic",
            transport=mocked(fail_path="/reviews")[0],
        )


@pytest.mark.asyncio
async def test_missing_token_and_invalid_repo_fail_before_network():
    with pytest.raises(ValueError, match="GITHUB_TOKEN"):
        await inspect_github_pr_history(REPO, PR, github_token="")
    with pytest.raises(ValueError, match="Invalid GitHub repository"):
        await inspect_github_pr_history("../evil", PR, github_token="synthetic")
    with pytest.raises(ValueError, match="pr_number"):
        await inspect_github_pr_history(REPO, True, github_token="synthetic")


@pytest.mark.asyncio
async def test_pr_identity_mismatch_fails_closed():
    t, _ = mocked()
    def handler(req):
        if req.url.path.endswith("/pulls/39"):
            p = pull()
            p["base"]["repo"]["full_name"] = "other/repo"
            return httpx.Response(200, json=p)
        raise AssertionError("must stop before timeline")
    with pytest.raises(ValueError, match="repository identity"):
        await inspect_github_pr_history(
            REPO, PR, github_token="synthetic", transport=httpx.MockTransport(handler),
        )


@pytest.mark.asyncio
async def test_page_is_retrieved_even_if_timeline_empty():
    r = await inspect_github_pr_history(
        REPO, PR, github_token="synthetic", transport=mocked(timeline_data=[], reviews_data=[])[0],
    )
    assert r["observations"] == []
    assert r["complete_audit_trail_verified"] is False


@pytest.mark.asyncio
async def test_github_timeline_event_without_created_at_remains_visible_and_undated():
    """Live regression: some timeline records have no created_at."""
    entries = timeline()
    entries.insert(0, {
        "event": "committed", "id": 506, "actor": {"login": "alice"},
        "sha": "c" * 40,
        # No created_at: do not invent one or reject all other events.
    })
    r = await inspect_github_pr_history(
        REPO, PR, github_token="synthetic",
        transport=mocked(timeline_data=entries)[0],
    )
    assert r["observations_count"] == 4
    assert r["events_without_timestamp_count"] == 1
    assert r["all_events_chronologically_orderable"] is False
    assert [x["event_type"] for x in r["observations"][:3]] == [
        "review_requested", "review:approved", "merged",
    ]
    undated = r["observations"][-1]
    assert undated["event_type"] == "committed"
    assert undated["occurred_at"] is None
    assert undated["actor_login"] == "alice"
    assert undated["commit_sha"] == "c" * 40
    assert r["complete_audit_trail_verified"] is False
    assert undated["commit_metadata"]["status"] == "available"
    assert undated["commit_metadata"]["author_date"] == "2026-10-26T12:10:00Z"
    assert undated["commit_metadata"]["committer_date"] == "2026-10-26T12:11:00Z"
    assert undated["commit_metadata"]["github_author_login"] == "demo-author"
    assert r["commit_metadata_unavailable_count"] == 0
    assert "undated" in r["next_action"].lower()


@pytest.mark.asyncio
async def test_invalid_present_timeline_timestamp_does_not_silently_pass():
    entries = timeline()
    entries[0]["created_at"] = "not-a-date"
    with pytest.raises(ValueError, match="timestamp"):
        await inspect_github_pr_history(
            REPO, PR, github_token="synthetic",
            transport=mocked(timeline_data=entries)[0],
        )


@pytest.mark.asyncio
async def test_commit_metadata_403_is_reported_without_dropping_event():
    entries = [{"event": "committed", "node_id": "commit-record",
                "sha": "c" * 40}]
    r = await inspect_github_pr_history(
        REPO, PR, github_token="synthetic",
        transport=mocked(timeline_data=entries, reviews_data=[],
                         fail_path="/commits/" + "c" * 40)[0],
    )
    assert r["observations_count"] == 1
    assert r["observations"][0]["occurred_at"] is None
    assert r["observations"][0]["commit_metadata"]["status"] == "unavailable"
    assert r["commit_metadata_unavailable_count"] == 1
    assert r["actor_identity_verified"] is False


@pytest.mark.asyncio
async def test_non_commit_timeline_event_does_not_fetch_git_commit():
    transport, calls = mocked()
    result = await inspect_github_pr_history(
        REPO, PR, github_token="synthetic", transport=transport,
    )
    assert len(calls) == 3
    assert result["commit_metadata_unavailable_count"] == 0
