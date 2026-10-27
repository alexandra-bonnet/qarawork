"""Explicit local evidence capture and offline integrity verification.

Captures actual GitHub REST JSON responses. SHA-256 verifies against the local
manifest, but an attacker who can replace both manifest and files can forge
a self-consistent bundle. Independent retention / anchoring is OUT of scope.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from datetime import datetime, timezone
from uuid import uuid4

import httpx

from .github_activity import OWNER_RE, REPO_RE, MAX_PAGES, _timeline_event, _review_event

SCHEMA = "qarawork-audit-evidence-v1"
SHA = re.compile(r"[a-f0-9]{64}\Z")
COMMIT_SHA = re.compile(r"[a-fA-F0-9]{40}\Z")
MAX_COMMITS = 50
MAX_BYTES = 8_000_000


def _json_bytes(obj: object) -> bytes:
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_target(repository: str, pr_number: int) -> tuple[str, str]:
    if not isinstance(repository, str) or repository.count("/") != 1:
        raise ValueError("Expected repository owner/name.")
    owner, name = repository.split("/")
    if not OWNER_RE.fullmatch(owner) or not REPO_RE.fullmatch(name):
        raise ValueError("Invalid GitHub repository.")
    if isinstance(pr_number, bool) or not isinstance(pr_number, int) or pr_number <= 0:
        raise ValueError("Invalid PR number.")
    return owner, name


def _report(repository: str, pr_number: int, pr: dict, timeline: list, reviews: list,
            commit_count: int, commit_unavailable: int, collected_at: str) -> str:
    events = [_timeline_event(x) for x in timeline]
    submitted = [x for x in reviews if x.get("submitted_at")]
    events.extend(_review_event(x) for x in submitted)
    dated = sorted((x for x in events if x["occurred_at"]), key=lambda x: x["occurred_at"])
    undated = [x for x in events if x["occurred_at"] is None]
    unknown = [x for x in events if not x["supported_event_type"]]
    no_actor = [x for x in events if not x["actor_login"]]
    lines = [
        "# QARA review | GitHub pull request activity",
        "",
        f"**Repository:** \`{repository}\`  ",
        f"**Pull request:** #{pr_number}  ",
        f"**Title:** {str(pr.get('title') or '(not provided)').replace(chr(10), ' ')}  ",
        f"**Collected (UTC):** {collected_at}  ",
        f"**PR status reported by GitHub:** {pr.get('state')}; merged={pr.get('merged') is True}",
        "",
        "## Conclusion for QARA",
        "",
        f"GitHub supplied **{len(events)} activity observations**, including **{len(submitted)} submitted reviews**.",
        f"**{len(undated)} events lack a timeline timestamp** and **{len(no_actor)} lack a timeline actor login**.",
        f"**{len(unknown)} event types are not explicitly recognized** by this prototype.",
        f"Commit metadata: **{commit_count} commit records captured**, **{commit_unavailable} unavailable**.",
        "",
        "**Assessment:** Evidence captured for investigation only. This report does not confirm QARA approval,",
        "an authenticated human identity, a complete history, or an immutable/independently retained audit trail.",
        "",
        "## Dated observations (GitHub timeline or submitted review)",
        "",
        "| GitHub time (UTC) | Observation | Reported login | Source |",
        "| --- | --- | --- | --- |",
    ]
    for e in dated:
        lines.append(f"| {e['occurred_at']} | {e['event_type']} | {e['actor_login'] or 'Not reported'} | {e['source']} |")
    if not dated:
        lines.append("| No dated events returned | | | |")
    lines += ["", "## Undated observations", ""]
    for e in undated:
        lines.append(f"- **{e['event_type']}**; source \`{e['source']}\`; SHA \`{e['commit_sha'] or 'not reported'}\`; timeline actor: {e['actor_login'] or 'not reported'}.")
    if not undated:
        lines.append("No undated observations returned.")
    lines += [
        "",
        "## Required QARA follow-up",
        "",
        "1. Investigate missing event dates/actors and unrecognized event types.",
        "2. Verify whether the required formal QARA review exists in an approved external process;",
        "   a GitHub merge or GitHub review is not itself proof of regulatory approval.",
        "3. Preserve the manifest digest separately in a suitably controlled system and",
        "   apply retention/access controls before relying on long-term evidence.",
        "4. Confirm source API scope, pagination and completeness requirements for the intended use.",
        "",
        "## What is actually preserved",
        "",
        "Raw JSON returned by GitHub's PR, timeline, submitted reviews and available commit APIs.",
        "The manifest records SHA-256 for each JSON artifact and this report.",
        "The capture mechanism performs GET requests only; the capture command explicitly writes local files.",
        "Verification checks byte integrity against the adjacent manifest, **not manifest authenticity**.",
        "Dates recorded for commits (inside commit JSON) must not be confused with timeline event dates.",
        "",
        "**Human approval verified:** No  ",
        "**Independent immutable retention verified:** No  ",
        "**Authorized for regulated use:** No",
        "",
    ]
    return "\n".join(lines)


async def fetch_github_evidence(repository: str, pr_number: int, *,
                                token: str | None = None,
                                transport: httpx.AsyncBaseTransport | None = None) -> dict[str, object]:
    owner, repo = _validate_target(repository, pr_number)
    credential = token if token is not None else os.getenv("GITHUB_TOKEN")
    if not credential:
        raise ValueError("GITHUB_TOKEN is required for evidence capture.")
    prefix = f"/repos/{owner}/{repo}"
    async with httpx.AsyncClient(
        base_url="https://api.github.com", transport=transport, follow_redirects=False,
        timeout=30.0, headers={"Authorization": f"Bearer {credential}",
                               "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28"},
    ) as client:
        async def get_json(path: str, params: dict | None = None) -> object:
            response = await client.get(path, params=params)
            response.raise_for_status()
            payload = response.json()
            if len(_json_bytes(payload)) > MAX_BYTES:
                raise ValueError("GitHub evidence response exceeds per-file limit.")
            return payload

        async def pages(path: str) -> list[dict]:
            records: list[dict] = []
            for page in range(1, MAX_PAGES + 1):
                result = await get_json(path, {"per_page": 100, "page": page})
                if not isinstance(result, list) or any(not isinstance(x, dict) for x in result):
                    raise ValueError("Malformed GitHub paginated evidence.")
                records.extend(result)
                if len(result) < 100:
                    return records
            raise ValueError("GitHub pagination exceeds limit; no capture written.")

        pr = await get_json(f"{prefix}/pulls/{pr_number}")
        if not isinstance(pr, dict) or pr.get("number") != pr_number:
            raise ValueError("GitHub PR identity mismatch.")
        actual = ((pr.get("base") or {}).get("repo") or {}).get("full_name", "")
        if not isinstance(actual, str) or actual.lower() != repository.lower():
            raise ValueError("GitHub repository identity mismatch.")
        timeline = await pages(f"{prefix}/issues/{pr_number}/timeline")
        reviews = await pages(f"{prefix}/pulls/{pr_number}/reviews")
        # Fail on malformed event structures rather than preserving an unreviewable report.
        for x in timeline:
            _timeline_event(x)
        for x in reviews:
            if x.get("submitted_at") is not None:
                _review_event(x)
        shas = {x.get("sha") or x.get("commit_id") for x in timeline if x.get("event") == "committed"}
        if len(shas) > MAX_COMMITS:
            raise ValueError("Too many GitHub commits for capture.")
        artifacts = {"pull_request.json": pr, "timeline.json": timeline, "reviews.json": reviews}
        unavailable = []
        for sha in sorted(shas):
            if not isinstance(sha, str) or not COMMIT_SHA.fullmatch(sha):
                unavailable.append(str(sha))
                continue
            try:
                commit = await get_json(f"{prefix}/commits/{sha}")
                if not isinstance(commit, dict) or str(commit.get("sha", "")).lower() != sha.lower():
                    raise ValueError("GitHub returned mismatched commit metadata.")
                artifacts[f"commits/{sha.lower()}.json"] = commit
            except (httpx.HTTPError, ValueError, TypeError):
                unavailable.append(sha.lower())
    return {"artifacts": artifacts, "unavailable_commits": unavailable}


def _check_root(root: str | Path) -> Path:
    folder = Path(root).expanduser()
    if not folder.is_absolute():
        raise ValueError("Capture root must be an absolute directory.")
    if folder.is_symlink():
        raise ValueError("Capture root must not be a symlink.")
    return folder.resolve(strict=True)


def capture_evidence(root: str | Path, repository: str, pr_number: int,
                     evidence: dict, *, collected_at: str | None = None) -> Path:
    """Explicit local write; never automatically overwrite a captured bundle."""
    folder = _check_root(root)
    if not folder.is_dir():
        raise ValueError("Capture root must be a directory.")
    _validate_target(repository, pr_number)
    artifacts = evidence["artifacts"]
    if not isinstance(artifacts, dict) or not isinstance(evidence.get("unavailable_commits"), list):
        raise ValueError("Malformed evidence collection.")
    when = collected_at or datetime.now(timezone.utc).isoformat()
    capture_name = f"pr-{pr_number}-{uuid4().hex}"
    target = folder / capture_name
    target.mkdir(mode=0o700)
    try:
        manifest_files = {}
        for name, data in artifacts.items():
            if not (name in {"pull_request.json", "timeline.json", "reviews.json"} or
                    re.fullmatch(r"commits/[0-9a-f]{40}\.json", name)):
                raise ValueError("Unsafe artifact name.")
            path = target / name
            path.parent.mkdir(mode=0o700, exist_ok=True)
            raw = _json_bytes(data)
            if len(raw) > MAX_BYTES:
                raise ValueError("Capture artifact too large.")
            with path.open("xb") as out:
                out.write(raw)
            manifest_files[name] = _sha(raw)
        pr = artifacts["pull_request.json"]
        timeline = artifacts["timeline.json"]
        reviews = artifacts["reviews.json"]
        text = _report(repository, pr_number, pr, timeline, reviews,
                       sum(name.startswith("commits/") for name in artifacts),
                       len(evidence["unavailable_commits"]), when)
        report_bytes = text.encode("utf-8")
        with (target / "QARA-REVIEW.md").open("xb") as out:
            out.write(report_bytes)
        manifest_files["QARA-REVIEW.md"] = _sha(report_bytes)
        manifest = {
            "schema": SCHEMA, "repository": repository, "pr_number": pr_number,
            "collected_at": when, "files_sha256": manifest_files,
            "unavailable_commits": evidence["unavailable_commits"],
            "human_approval_verified": False,
            "independent_immutable_retention_verified": False,
        }
        with (target / "manifest.json").open("xb") as out:
            out.write(_json_bytes(manifest))
    except Exception:
        # Keep any incomplete write visible for manual investigation; do not
        # silently hide a partial capture or present it as verified.
        raise
    return target


def verify_evidence(root: str | Path, capture_id: str) -> dict:
    """Offline, read-only comparison with the *local* manifest.

    The caller must independently protect/anchor the manifest. Neither SHA-256
    nor a successful local check prevents an attacker replacing the whole bundle.
    """
    folder = _check_root(root)
    if not re.fullmatch(r"pr-[1-9][0-9]*-[0-9a-f]{32}", capture_id):
        raise ValueError("Invalid capture ID.")
    target = folder / capture_id
    if target.is_symlink() or not target.is_dir():
        raise ValueError("Capture directory missing or unsafe.")
    manifest_path = target / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Manifest missing or unsafe.")
    manifest = json.loads(manifest_path.read_bytes())
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise ValueError("Malformed evidence manifest.")
    entries = manifest.get("files_sha256")
    if not isinstance(entries, dict) or not entries or len(entries) > MAX_COMMITS + 4:
        raise ValueError("Invalid evidence file list.")
    expected = {"pull_request.json", "timeline.json", "reviews.json", "QARA-REVIEW.md"}
    actual_names = set(entries)
    if not expected.issubset(actual_names):
        raise ValueError("Required evidence artifacts are missing from manifest.")
    findings = []
    for name, digest in sorted(entries.items()):
        if not isinstance(name, str) or not (
            name in expected or re.fullmatch(r"commits/[0-9a-f]{40}\.json", name)
        ) or not isinstance(digest, str) or not SHA.fullmatch(digest):
            raise ValueError("Unsafe evidence manifest entry.")
        path = target / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            findings.append({"file": name, "status": "missing_or_unsafe"})
            continue
        actual_digest = _sha(path.read_bytes())
        if actual_digest != digest:
            findings.append({"file": name, "status": "digest_mismatch"})
    # Detect unlisted files, rather than treating inserted files as verified.
    for path in target.rglob("*"):
        if path.is_file() or path.is_symlink():
            name = path.relative_to(target).as_posix()
            if name != "manifest.json" and name not in entries:
                findings.append({"file": name, "status": "unexpected_file"})
    return {
        "capture_id": capture_id,
        "repository": manifest.get("repository"),
        "pr_number": manifest.get("pr_number"),
        "collected_at": manifest.get("collected_at"),
        "status": "Matches local manifest" if not findings else "Evidence integrity issue",
        "all_listed_files_match": not findings,
        "findings": findings,
        "checked_files_count": len(entries),
        "manifest_sha256": _sha(manifest_path.read_bytes()),
        "human_approval_verified": False,
        "manifest_authenticity_verified": False,
        "independent_immutable_retention_verified": False,
        "authorized_for_use": False,
        "qara_summary": (
            "All captured artifact bytes match this bundle's local manifest. "
            "This does not establish that the manifest is authentic, independently protected, "
            "complete or regulatorily approved."
            if not findings else
            "Captured evidence no longer matches the local manifest, or files are missing/unexpected. "
            "Investigate before relying on the capture."
        ),
        "next_action": (
            "Investigate evidence alteration or missing files; restore from protected reference."
            if findings else
            "Preserve/verify the manifest digest independently; obtain procedural QARA review."
        ),
    }
