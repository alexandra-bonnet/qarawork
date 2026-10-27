# <img src="../../assets/tools/records-retention.svg" width="58" height="58" align="center" alt="" /> MCP Records & Retention

**Evidence should remain findable and retrievable.**

**Status: In design**

[← Back to the QARAWORK toolkit](../../README.md)

## Intended capability

Check which records require retention, whether an export is complete, whether copies can be located and whether a sample restore succeeds.

## Key design condition

A periodic check cannot by itself guarantee retention duration, integrity or long-term access. Records must be preserved in suitable storage with documented retention policies and tested recovery.

## Planned tests

- Detect a missing required evidence file.
- Compare an export manifest with source identifiers and digests.
- Verify retrieval of a retained synthetic test record.

**Status:** concept only. No archival or retention compliance claim.
