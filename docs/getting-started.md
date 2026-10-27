# Getting started with QARAWORK

QARAWORK offers independent MCP prototypes for regulated software teams. These tools inspect evidence and assist human review. They are not a validated eQMS or an approval service.

## Requirements

- Python 3.10 or newer.
- An MCP-compatible client.
- An isolated Python environment for each tool.
- Your own authorized data sources and credentials for connected checks.

## Choose a tool

| Tool | Purpose | Package location |
| --- | --- | --- |
| Traceability | Check requirement-to-test links and prepare change-impact drafts | `tools/traceability` |
| Document Control | Review revisions and verify supported evidence | `tools/document-control` |
| Audit Trail | Inspect reported activity and local evidence integrity | `tools/audit-trail` |

Install a selected package from the repository root:

```bash
python -m venv .venv
python -m pip install -e "./tools/document-control[dev]"
python -m pytest tools/document-control/tests -q
```

To run another package, replace `document-control` with `audit-trail` or `traceability`. The three packages are included in this repository.

## MCP server entrypoints

- Traceability: `python -m samd_traceability_mcp.server`
- Document Control: `python -m qarawork_document_control.server`
- Audit Trail: `python -m qarawork_audit_trail.server`

Configure the command and required read permissions in your MCP client using its official documentation. Keep tokens in a local secret manager or environment, not in committed files.

Some capabilities explicitly write draft content or capture local evidence. Review the individual tool documentation and permissions before enabling them.

## Understanding results

A missing link, matching hash, provider event, or passing test has a limited meaning. The adopting organization remains responsible for verifying evidence quality, assigning human review, enforcing approvals, and validating use in its own quality system.

## Demonstrations

Use only synthetic data or information you are authorized to process. A public Demo Hub may provide fictional examples; duplicate these into your own authorized workspace before connecting your integration. Public Notion visibility alone does not grant API access.

## Security

Do not commit access tokens, client configurations, local captures, private keys, patient data, or proprietary product information. Report suspected vulnerabilities through the instructions in `SECURITY.md`.
