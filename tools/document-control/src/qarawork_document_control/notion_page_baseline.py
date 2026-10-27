"""Separately provisioned local Notion PAGE-content reference, never auto-refreshed.

The reference is a demo baseline to compare a live page. Its local storage is
not immutable, its creation is not human approval, and it is not the signed
SOP-002 binary fixture.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .notion_content import SHA256_HEX

SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
SAFE_REV = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


def filename_for(document_id: str, revision: str) -> str:
    if not isinstance(document_id, str) or not SAFE_ID.fullmatch(document_id):
        raise ValueError("Invalid document ID for the Notion baseline.")
    if not isinstance(revision, str) or not SAFE_REV.fullmatch(revision) or revision in (".", ".."):
        raise ValueError("Invalid revision for the Notion baseline.")
    return f"{document_id}--{revision}.notion-page-baseline.json"


def baseline_path(root: str | None, document_id: str, revision: str) -> Path:
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise ValueError("QARAWORK_DC_NOTION_BASELINE_ROOT must be an absolute directory.")
    directory = Path(root)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Configured Notion baseline directory is invalid or symlinked.")
    return directory / filename_for(document_id, revision)


def validate_baseline(data: object, *, document_id: str, revision: str,
                      page_id: str, data_source_id: str) -> str:
    if not isinstance(data, dict) or set(data) != {
        "schema", "document_id", "revision", "notion_page_id",
        "notion_data_source_id", "content_sha256",
    }:
        raise ValueError("Notion page baseline has an unsupported schema.")
    expected = {
        "schema": "qarawork-notion-page-baseline-v1",
        "document_id": document_id, "revision": revision,
        "notion_page_id": page_id, "notion_data_source_id": data_source_id,
    }
    for name, value in expected.items():
        if data.get(name) != value:
            raise ValueError("Notion page baseline identifies a different document or source.")
    digest = data.get("content_sha256")
    if not isinstance(digest, str) or not SHA256_HEX.fullmatch(digest):
        raise ValueError("Notion page baseline content fingerprint is invalid.")
    return digest


def read_page_baseline(root: str | None, document_id: str, revision: str,
                       page_id: str, data_source_id: str) -> str | None:
    """Read reference from a separately configured directory, never Notion metadata."""
    path = baseline_path(root, document_id, revision)
    if path.is_symlink():
        raise ValueError("Notion page baseline must not be a symbolic link.")
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("Notion page baseline is not a regular small file.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Notion page baseline is unreadable or malformed.") from exc
    return validate_baseline(
        data, document_id=document_id, revision=revision,
        page_id=page_id, data_source_id=data_source_id,
    )
