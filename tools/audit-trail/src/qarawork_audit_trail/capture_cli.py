"""Explicit capture command (writes) and read-only offline verification.

Example:
 python -m qarawork_audit_trail.capture_cli capture \
   --repository example-org/example-repo --pr-number 123 \
   --root /absolute/path/to/ignored/captures --acknowledge-local-capture
 python -m qarawork_audit_trail.capture_cli verify \
   --root /absolute/path/to/ignored/captures --capture-id pr-39-...
"""
from __future__ import annotations

import argparse
import asyncio
import json

from .evidence_capture import fetch_github_evidence, capture_evidence, verify_evidence


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicit local QARAWORK Audit Trail evidence capture")
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("--repository", required=True)
    capture.add_argument("--pr-number", required=True, type=int)
    capture.add_argument("--root", required=True)
    capture.add_argument("--acknowledge-local-capture", action="store_true")
    verify = sub.add_parser("verify")
    verify.add_argument("--root", required=True)
    verify.add_argument("--capture-id", required=True)
    args = parser.parse_args()
    if args.command == "verify":
        print(json.dumps(verify_evidence(args.root, args.capture_id), indent=2))
        return
    if not args.acknowledge_local_capture:
        parser.error("Capture writes local files. Pass --acknowledge-local-capture explicitly.")
    payload = asyncio.run(fetch_github_evidence(args.repository, args.pr_number))
    target = capture_evidence(args.root, args.repository, args.pr_number, payload)
    print(json.dumps({
        "status": "Local evidence bundle created; not independently immutable",
        "capture_id": target.name,
        "path": str(target),
        "qara_report": str(target / "QARA-REVIEW.md"),
        "manifest": str(target / "manifest.json"),
        "verification": verify_evidence(args.root, target.name),
    }, indent=2))


if __name__ == "__main__":
    main()
