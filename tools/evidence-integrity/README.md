# <img src="../../assets/tools/evidence-integrity.svg" width="58" height="58" align="center" alt="" /> MCP Evidence Integrity

**Trust the approved revision, not just the document title.**

**Status: In design**

[← Back to the QARAWORK toolkit](../../README.md)

## Intended capability

Calculate and verify SHA-256 fingerprints of controlled documents and evidence against an independently preserved approval baseline. Flag content changes after approval or missing baselines.

## Key design condition

A hash can demonstrate that bytes differ from a reference. It cannot by itself prove who approved them, whether an approval was valid, or whether the reference store can be tampered with.

## Planned tests

- Verify unchanged content against a stored fingerprint.
- Detect a one-character edit after approval.
- Fail closed if the trusted baseline is unavailable.

**Status:** concept only. This builds on fingerprint concepts demonstrated in the Traceability change-control prototype.
