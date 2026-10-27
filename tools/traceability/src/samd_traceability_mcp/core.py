"""Deterministic requirements-to-test link checker without LLM inference."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Iterable

REF = re.compile(r"\bRequirement\s*:\s*#(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Requirement:
    number: int
    title: str
    url: str


def is_test_file(path: str) -> bool:
    parts = path.split("/")
    # Example programs are documentation, not test evidence.
    if "examples" in parts[:-1]:
        return False
    return path.endswith(".py") and ("tests" in parts or parts[-1].startswith("test_"))


def extract_test_references(source: str) -> set[int]:
    """Only read markers from docstrings of pytest-style test functions.

    This intentionally does not match strings in test fixtures, comments,
    module-level examples, or arbitrary strings in the source code.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        raise ValueError("Invalid Python test source; scan cannot be trusted") from None

    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        docstring = ast.get_docstring(node, clean=False)
        if docstring:
            found.update(int(n) for n in REF.findall(docstring))
    return found


def analyze(requirements: Iterable[Requirement], files: dict[str, str], *, repository: str) -> dict:
    requirements = list(requirements)
    if len({r.number for r in requirements}) != len(requirements):
        raise ValueError("Duplicate requirement issue numbers")

    references: dict[int, list[str]] = {}
    scanned = 0
    for path, content in sorted(files.items()):
        if not is_test_file(path):
            continue
        scanned += 1
        try:
            matched = extract_test_references(content)
        except ValueError as exc:
            raise ValueError(f"Cannot scan {path}: {exc}") from exc
        for number in matched:
            references.setdefault(number, []).append(path)

    rows = []
    for req in sorted(requirements, key=lambda r: r.number):
        paths = sorted(references.get(req.number, []))
        rows.append({
            "issue": req.number, "title": req.title, "url": req.url,
            "status": "linked" if paths else "unlinked", "test_files": paths,
        })
    known = {r.number for r in requirements}
    dangling = [
        {"issue": number, "test_files": sorted(paths)}
        for number, paths in sorted(references.items())
        if number not in known
    ]
    return {
        "repository": repository, "convention": "Requirement: #<github-issue-number> in test function docstring",
        "scanned_test_files": scanned, "requirements_count": len(rows),
        "linked_count": sum(r["status"] == "linked" for r in rows),
        "unlinked_count": sum(r["status"] == "unlinked" for r in rows),
        "requirements": rows, "references_to_non_requirement_issues": dangling,
        "limitations": [
            "A link is not proof of adequate verification or a passing test.",
            "Only pytest-style Python test function docstrings containing Requirement: #123 are checked.",
            "Only accessible files and labeled issues in the selected repository are analyzed.",
        ],
    }
