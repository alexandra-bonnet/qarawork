"""Read-only, exact-commit GitHub Actions JUnit test evidence.

Workflow conclusions alone are not function-level evidence. Missing, ambiguous,
or mismatched artifacts result in Unknown rather than inferred success.
"""
from __future__ import annotations

import io
import os
import re
import zipfile
import xml.etree.ElementTree as ET

import httpx

from .github import REPO

ARTIFACT_NAME = "samd-pytest-junit"
MAX_ZIP_BYTES = 8_000_000
MAX_XML_BYTES = 3_000_000
BRANCH = re.compile(r"^[A-Za-z0-9_./-]{1,150}$")
ALLOWED_STATES = {"Passed", "Failed", "Skipped"}


def parse_junit_xml(payload: bytes) -> dict[tuple[str, str], str]:
    """Index pytest JUnit results by exact (Python test file, function name).

    A parameterized test is aggregated only when every case is accounted for.
    Failure/error dominates, then skipped, then passed.
    """
    if len(payload) > MAX_XML_BYTES:
        raise ValueError("JUnit XML exceeds size limit")
    root = ET.fromstring(payload)
    if root.tag not in {"testsuite", "testsuites"}:
        raise ValueError("Unexpected JUnit XML root")
    cases: dict[tuple[str, str], list[str]] = {}
    for element in root.iter("testcase"):
        classname = element.attrib.get("classname", "")
        name = element.attrib.get("name", "")
        if not classname or not re.fullmatch(r"test_[A-Za-z0-9_]+(?:\[[^\]]+\])?", name):
            continue
        # Standard pytest junit_family=xunit2 classname derives from module path.
        if not re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*", classname):
            continue
        path = classname.replace(".", "/") + ".py"
        base_name = name.split("[", 1)[0]
        state = "Failed" if element.find("failure") is not None or element.find("error") is not None else (
            "Skipped" if element.find("skipped") is not None else "Passed"
        )
        cases.setdefault((path, base_name), []).append(state)
    result = {}
    for key, states in cases.items():
        result[key] = "Failed" if "Failed" in states else (
            "Skipped" if "Skipped" in states else "Passed"
        )
    return result


def extract_junit_zip(content: bytes) -> dict[tuple[str, str], str]:
    if len(content) > MAX_ZIP_BYTES:
        raise ValueError("Artifact download exceeds ZIP size limit")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = [item for item in archive.infolist() if item.filename == "pytest-results.xml"]
        if len(names) != 1 or names[0].file_size > MAX_XML_BYTES:
            raise ValueError("Expected exactly one bounded pytest-results.xml")
        return parse_junit_xml(archive.read(names[0]))


def enrich_matrix_with_ci(matrix: dict, evidence: dict) -> dict:
    """Return an updated matrix, without modifying its source argument."""
    import csv

    updated = {**matrix, "rows": [dict(row) for row in matrix["rows"]]}
    cases = evidence.get("cases", {})
    run_url = evidence.get("run_url", "")
    sha = evidence.get("sha", "")
    for row in updated["rows"]:
        name, path = row.get("Test Case", ""), row.get("GitHub Test File", "")
        if row.get("Link Status") == "Linked" and name and path:
            status = cases.get((path, name), "Unknown")
            if status not in ALLOWED_STATES:
                status = "Unknown"
            row["Execution Status"] = status
            if status != "Unknown":
                row["CI Run URL"] = run_url
                row["CI Commit SHA"] = sha
                row["Evidence Level"] = "Explicit marker plus same-commit JUnit outcome"
    updated["columns"] = list(matrix["columns"])
    for field in ("CI Run URL", "CI Commit SHA"):
        if field not in updated["columns"]:
            updated["columns"].append(field)
    for row in updated["rows"]:
        row.setdefault("CI Run URL", "")
        row.setdefault("CI Commit SHA", "")
    buff = io.StringIO(newline="")
    writer = csv.DictWriter(buff, fieldnames=updated["columns"], lineterminator="\\n")
    writer.writeheader()
    from .matrix import _safe_cell
    for row in updated["rows"]:
        writer.writerow({key: _safe_cell(row.get(key, "")) for key in updated["columns"]})
    updated["csv"] = buff.getvalue()
    updated["ci_evidence"] = {
        "status": evidence.get("status", "Unavailable"),
        "reason": evidence.get("reason", ""),
        "run_url": run_url,
        "sha": sha,
        "matched_test_cases": sum(row["Execution Status"] != "Unknown" for row in updated["rows"]),
    }
    updated["execution_status_policy"] = "Only exact-commit JUnit per-test results; others Unknown"
    return updated


def validated_artifact_redirect(response: httpx.Response) -> str:
    """Return expected GitHub storage location without leaking the API token."""
    if response.status_code not in (301, 302, 303, 307, 308):
        response.raise_for_status()
        raise ValueError("Expected GitHub artifact download redirect")
    redirected = response.headers.get("location", "")
    uri = httpx.URL(redirected)
    if (uri.scheme != "https" or not uri.host or uri.username or uri.password
            or not (uri.host == "objects.githubusercontent.com"
                    or uri.host.endswith(".actions.githubusercontent.com")
                    or uri.host.endswith(".blob.core.windows.net"))):
        raise ValueError("Invalid GitHub artifact redirect")
    return redirected


async def fetch_ci_evidence(repository: str, ref: str) -> dict:
    """Find a completed Actions run with a named JUnit artifact for the exact ref SHA."""
    if not REPO.fullmatch(repository) or not BRANCH.fullmatch(ref) or ".." in ref:
        raise ValueError("Invalid GitHub repository or ref")
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN is required")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(base_url="https://api.github.com", headers=headers,
                                 timeout=30.0, follow_redirects=False) as client:
        async def get_json(path, params=None):
            response = await client.get(path, params=params)
            response.raise_for_status()
            return response.json()
        branch = await get_json(f"/repos/{repository}/branches/{ref}")
        sha = branch["commit"]["sha"]
        runs = await get_json(f"/repos/{repository}/actions/runs",
                              {"branch": ref, "per_page": 50})
        # The API may return older branch runs; only exact SHA plus completed run qualify.
        matches = [run for run in runs.get("workflow_runs", [])
                   if run.get("head_sha") == sha and run.get("status") == "completed"
                   and run.get("event") in {"push", "workflow_dispatch"}]
        matches.sort(key=lambda run: (run.get("run_started_at", ""), run.get("id", 0)), reverse=True)
        for run in matches:
            artifacts = await get_json(
                f"/repos/{repository}/actions/runs/{run['id']}/artifacts",
                {"per_page": 100}
            )
            matching = [a for a in artifacts.get("artifacts", [])
                        if a.get("name") == ARTIFACT_NAME and not a.get("expired")]
            if len(matching) != 1:
                continue
            archive_response = await client.get(
                f"/repos/{repository}/actions/artifacts/{matching[0]['id']}/zip"
            )
            redirected = validated_artifact_redirect(archive_response)
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as download:
                async with download.stream("GET", redirected) as response:
                    response.raise_for_status()
                    if response.is_redirect:
                        raise ValueError("Unexpected artifact host redirect")
                    chunks = []
                    total = 0
                    async for part in response.aiter_bytes():
                        total += len(part)
                        if total > MAX_ZIP_BYTES:
                            raise ValueError("Artifact download exceeds size limit")
                        chunks.append(part)
            return {
                "status": "Available",
                "sha": sha,
                "run_url": run.get("html_url", ""),
                "cases": extract_junit_zip(b"".join(chunks)),
            }
    return {
        "status": "Unavailable",
        "reason": "No completed push/dispatch run with JUnit artifact for the exact branch SHA",
        "sha": sha,
        "cases": {},
    }
