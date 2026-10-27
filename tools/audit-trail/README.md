<div align="center">

<img src="../../assets/tools/audit-trail.svg" alt="" width="58" />

# MCP Audit Trail

**Understand reported activity. See what the evidence cannot prove.**

Inspect supported activity metadata, identify inconsistent event sequences, and verify locally captured evidence without confusing provider history with an independently protected audit log.

**Available · Tested prototype · Notion + GitHub**

[← Back to QARAWORK](../../README.md)

</div>

## The problem

A modification timestamp does not explain every change, who actually performed it, or whether the event history is complete.

Teams need to investigate available activity records without overstating their provenance or reliability.

## The benefits

- **QARA:** identify missing evidence and questions for follow-up.
- **Product:** understand whether available change information is sufficient for review.
- **Development:** inspect reported events, sequence anomalies, and supporting metadata.

**The result:** more transparent investigations, with uncertainty made explicit.

## The solution

MCP Audit Trail inspects the activity information available from supported providers and checks supplied event sequences. An optional, separate command can capture GitHub evidence locally for subsequent integrity verification.

It helps investigate history; it does not create a complete or independently immutable audit record.

## How it works

1. **Connect:** authorize read access to a supported Notion page or GitHub pull request.
2. **Inspect:** retrieve available activity metadata or check a supplied event list.
3. **Verify:** optionally check an explicitly captured local evidence bundle against its manifest.
4. **Report:** return observations, gaps, and limits for human review.

## What it does today

| Capability | Result |
| --- | --- |
| Notion activity inspection | Reads creation and most-recent-edit metadata, not a complete edit history. |
| Event-sequence review | Flags duplicates, missing sequence numbers, timestamp inconsistencies, and absent actor fields in supplied events. |
| GitHub PR inspection | Reads available pull-request events, submitted reviews, and commit metadata. |
| Local evidence capture | An **explicit separate CLI** collects selected GitHub evidence into a local bundle. |
| Evidence verification | Checks captured files against a local SHA-256 manifest and reports discrepancies. |

## Get started

Install the package and run the included tests:

```bash
cd tools/audit-trail
python -m pip install -e ".[dev]"
python -m pytest tests -q
```

Configure an MCP-compatible client to run `python -m qarawork_audit_trail.server`. Provide authorized, read-only credentials locally and test with your own permitted data.

For optional evidence capture, inspect the CLI with `python -m qarawork_audit_trail.capture_cli --help` and choose a local output directory excluded from version control. Never commit credentials or captured evidence.

## Scope and limitations

Provider timestamps and user identifiers are not independent proof of human identity. The available Notion page metadata is not a complete edit history; GitHub PR activity does not establish formal QARA approval.

A local SHA-256 manifest can detect changes relative to that manifest, but cannot guarantee immutability if both the evidence and manifest can be replaced. Independent preservation, retention, approvals, and electronic signatures remain outside this tool.

**Use findings to guide investigation and human review, not to claim a complete or compliant audit trail.**

<sub>Prototype only; not an independently protected audit log or validated eQMS.</sub>
