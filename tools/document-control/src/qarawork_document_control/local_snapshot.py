"""Read exact document bytes and detached evidence from a server-configured local folder.

The directory is a DEMO source only: local files are not guaranteed immutable,
independently retained, or suitable for regulated production records.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

from .signed_evidence import MAX_BYTES

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SAFE_REV = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
MAX_ENVELOPE_BYTES = 32_768


def _regular_file(root: Path, filename: str, max_size: int) -> bytes:
    """Reject symlinks, directories and oversized files; never follow a final symlink."""
    path = root / filename
    if path.is_symlink():
        raise ValueError("Source artifact must not be a symbolic link.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("Source artifact must be a regular file.")
            if metadata.st_size > max_size:
                raise ValueError("Source artifact exceeds the permitted byte limit.")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(max_size + 1)
            if len(data) > max_size:
                raise ValueError("Source artifact exceeds the permitted byte limit.")
            return data
        finally:
            os.close(fd)
    except OSError as exc:
        raise ValueError("Configured source artifact is missing or cannot be safely read.") from exc


def read_local_signed_artifacts(
    root_path: str | None, document_id: str, revision: str,
) -> tuple[bytes, dict, str]:
    """Load a controlled-name pair of local files, never a caller-selected path."""
    if not isinstance(document_id, str) or not _SAFE_ID.fullmatch(document_id):
        raise ValueError("Document ID is invalid for the local snapshot filename.")
    if not isinstance(revision, str) or not _SAFE_REV.fullmatch(revision) or revision in (".", ".."):
        raise ValueError("Revision is invalid for the local snapshot filename.")
    if not isinstance(root_path, str) or not Path(root_path).is_absolute():
        raise ValueError("QARAWORK_DC_SNAPSHOT_ROOT must be an absolute directory.")
    root = Path(root_path)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Snapshot root must exist and must not be a symlink.")
    name = f"{document_id}--{revision}"
    content = _regular_file(root, name + ".bin", MAX_BYTES)
    raw_evidence = _regular_file(root, name + ".evidence.json", MAX_ENVELOPE_BYTES)
    try:
        envelope = json.loads(raw_evidence.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Signed evidence sidecar must contain valid UTF-8 JSON.") from exc
    if not isinstance(envelope, dict):
        raise ValueError("Signed evidence sidecar must be an object.")
    return content, envelope, name
