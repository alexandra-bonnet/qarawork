"""Synthetic QARA evidence capture and offline tamper-detection tests."""
import json
import httpx
import pytest

from qarawork_audit_trail.evidence_capture import (
    fetch_github_evidence, capture_evidence, verify_evidence,
)
from qarawork_audit_trail.server import mcp

REPO = "example-org/example-repo"
SHA = "c" * 40


def source_transport(*, deny_commit=False, malformed=False):
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        assert request.method == "GET"
        path = request.url.path
        if path.endswith("/pulls/39"):
            return httpx.Response(200, json={
                "number": 39, "title": "Synthetic audit scenario", "state": "closed",
                "merged": True,
                "base": {"repo": {"full_name": REPO}},
            })
        if path.endswith("/issues/39/timeline"):
            return httpx.Response(200, json=[
                {"event": "committed", "id": 1, "sha": SHA,
                 "actor": None},  # No timeline timestamp: preserve without fabrication.
                {"event": "merged", "id": 2, "created_at": "2026-10-26T16:43:08Z",
                 "actor": {"login": "demo-user"}, "commit_id": "a" * 40},
            ])
        if path.endswith("/pulls/39/reviews"):
            return httpx.Response(200, json=[] if not malformed else {"oops": 1})
        if path.endswith("/commits/" + SHA):
            if deny_commit:
                return httpx.Response(403, json={"message": "Forbidden"})
            return httpx.Response(200, json={
                "sha": SHA, "commit": {
                    "author": {"name": "Demo", "date": "2026-10-26T16:40:00Z"},
                    "committer": {"name": "Demo", "date": "2026-10-26T16:41:00Z"},
                },
            })
        raise AssertionError(path)
    return httpx.MockTransport(handler), calls


@pytest.mark.asyncio
async def test_capture_read_only_qara_report_and_manifest_verification(tmp_path):
    transport, calls = source_transport()
    fetched = await fetch_github_evidence(
        REPO, 39, token="synthetic", transport=transport,
    )
    assert len(calls) == 4
    assert all(method == "GET" for method, _ in calls)
    target = capture_evidence(tmp_path, REPO, 39, fetched,
                              collected_at="2026-10-27T09:00:00Z")
    text = (target / "QARA-REVIEW.md").read_text()
    assert "Conclusion for QARA" in text
    assert "1 events lack a timeline timestamp" in text
    assert "0 submitted reviews" in text
    assert "QARA approval" in text
    assert "independently retained" in text
    assert (target / "commits" / (SHA + ".json")).is_file()
    integrity = verify_evidence(tmp_path, target.name)
    assert integrity["status"] == "Matches local manifest"
    assert integrity["all_listed_files_match"]
    assert integrity["manifest_authenticity_verified"] is False
    assert integrity["authorized_for_use"] is False
    assert len(integrity["manifest_sha256"]) == 64


@pytest.mark.asyncio
async def test_one_byte_change_detected_then_restoration_returns_to_match(tmp_path):
    fetched = await fetch_github_evidence(
        REPO, 39, token="synthetic", transport=source_transport()[0],
    )
    target = capture_evidence(tmp_path, REPO, 39, fetched)
    p = target / "timeline.json"
    original = p.read_bytes()
    p.write_bytes(original + b" ")
    result = verify_evidence(tmp_path, target.name)
    assert result["status"] == "Evidence integrity issue"
    assert {"file": "timeline.json", "status": "digest_mismatch"} in result["findings"]
    p.write_bytes(original)
    assert verify_evidence(tmp_path, target.name)["all_listed_files_match"]


@pytest.mark.asyncio
async def test_missing_and_extra_files_are_reported(tmp_path):
    fetched = await fetch_github_evidence(
        REPO, 39, token="synthetic", transport=source_transport()[0],
    )
    target = capture_evidence(tmp_path, REPO, 39, fetched)
    (target / "reviews.json").unlink()
    (target / "extra.txt").write_text("unlisted")
    result = verify_evidence(tmp_path, target.name)
    assert {"file": "reviews.json", "status": "missing_or_unsafe"} in result["findings"]
    assert {"file": "extra.txt", "status": "unexpected_file"} in result["findings"]


@pytest.mark.asyncio
async def test_denied_commit_read_keeps_explicit_evidence_gap(tmp_path):
    fetched = await fetch_github_evidence(
        REPO, 39, token="synthetic", transport=source_transport(deny_commit=True)[0],
    )
    assert fetched["unavailable_commits"] == [SHA]
    target = capture_evidence(tmp_path, REPO, 39, fetched)
    assert "1 unavailable" in (target / "QARA-REVIEW.md").read_text()
    assert verify_evidence(tmp_path, target.name)["all_listed_files_match"]


@pytest.mark.asyncio
async def test_malformed_mandatory_source_fails_before_capture(tmp_path):
    with pytest.raises(ValueError, match="paginated"):
        await fetch_github_evidence(
            REPO, 39, token="synthetic", transport=source_transport(malformed=True)[0],
        )
    assert not list(tmp_path.iterdir())


def test_verifier_rejects_unsafe_capture_id(tmp_path):
    with pytest.raises(ValueError, match="capture ID"):
        verify_evidence(tmp_path, "../outside")


def test_bundle_without_manifest_cannot_be_treated_as_verified(tmp_path):
    path = tmp_path / ("pr-39-" + "a" * 32)
    path.mkdir()
    with pytest.raises(ValueError, match="Manifest"):
        verify_evidence(tmp_path, path.name)


def test_four_tools_are_exposed():
    assert set(mcp._tool_manager._tools) == {
        "inspect_notion_page_activity", "review_event_sequence",
        "inspect_github_pr_history", "verify_audit_evidence_capture",
    }
