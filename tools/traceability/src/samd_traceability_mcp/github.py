"""Bounded, read-only GitHub API client."""
from __future__ import annotations
import base64
import os
import re
import httpx
from .core import Requirement, analyze, is_test_file

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_FILES = 500
MAX_FILE_BYTES = 150_000

async def fetch_python_test_files(repository: str, ref: str | None = None) -> tuple[str, dict[str, str]]:
    if not REPO.fullmatch(repository):
        raise ValueError("repository must be in owner/name format")
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN is required (fine-grained token with read-only Issues and Contents permissions)")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    async with httpx.AsyncClient(base_url="https://api.github.com", headers=headers,
                                 timeout=30.0, follow_redirects=False) as client:
        async def get(path: str, params: dict | None = None):
            response = await client.get(path, params=params)
            response.raise_for_status()
            return response.json()
        metadata = await get(f"/repos/{repository}")
        branch = ref or metadata["default_branch"]
        if not re.fullmatch(r"[A-Za-z0-9_./-]{1,150}", branch):
            raise ValueError("Invalid ref")
        # GitHub tree endpoint is read-only; reject truncated results.
        tree = await get(f"/repos/{repository}/git/trees/{branch}", {"recursive": "1"})
        if tree.get("truncated"):
            raise ValueError("GitHub tree is truncated; incomplete scan refused")
        paths = [e for e in tree.get("tree", []) if e.get("type") == "blob"
                 and is_test_file(e.get("path", ""))]
        if len(paths) > MAX_FILES:
            raise ValueError(f"Too many Python test files ({len(paths)}); maximum {MAX_FILES}")
        files = {}
        for entry in paths:
            if entry.get("size", 0) > MAX_FILE_BYTES:
                raise ValueError(f"Test file too large: {entry['path']}")
            blob = await get(f"/repos/{repository}/git/blobs/{entry['sha']}")
            if blob.get("encoding") != "base64":
                raise ValueError(f"Unsupported blob encoding: {entry['path']}")
            files[entry["path"]] = base64.b64decode(blob["content"]).decode("utf-8", errors="replace")
        return branch, files

async def inspect_repository(repository: str, ref: str | None = None) -> dict:
    branch, files = await fetch_python_test_files(repository, ref)
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN is required")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    requirements = []
    async with httpx.AsyncClient(base_url="https://api.github.com", headers=headers,
                                 timeout=30.0, follow_redirects=False) as client:
        page = 1
        while True:
            if page > 20:
                raise ValueError("Issue pagination limit exceeded; incomplete scan refused")
            response = await client.get(f"/repos/{repository}/issues",
                                        params={"state": "all", "labels": "requirement",
                                                "per_page": 100, "page": page})
            response.raise_for_status()
            issues = response.json()
            for issue in issues:
                if "pull_request" not in issue:
                    requirements.append(Requirement(issue["number"], issue["title"], issue["html_url"]))
            if len(issues) < 100:
                break
            page += 1
    result = analyze(requirements, files, repository=repository)
    result["ref"] = branch
    return result
