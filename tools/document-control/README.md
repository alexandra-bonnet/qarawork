<div align="center">

<img src="../../assets/tools/document-control.svg" alt="" width="58" />

# MCP Document Control

**Know which revision is recorded. Check whether its evidence still matches.**

Identify document-status gaps, inspect approval metadata, and verify supported integrity references without replacing your documentation system.

**Available · Read-only prototype · Notion + local evidence**

[← Back to QARAWORK](../../README.md)

</div>

## The problem

A document can be labeled “Approved” while the associated approval information is incomplete:or the available file no longer matches its recorded reference.

A status field alone cannot establish that the right revision was approved or remains unchanged.

## The benefits

- **QARA:** identify missing review and approval evidence before relying on a document status.
- **Product:** understand whether a revision is ready for further review.
- **Development:** spot mismatches between available files and recorded references.

**The result:** fewer assumptions about document status and a clearer basis for human decisions.

## The solution

MCP Document Control checks supported registers, revision metadata, and supplied integrity evidence. It reports inconsistencies and missing information rather than treating an “Approved” label as sufficient proof.

It does not approve, sign, lock, or publish documents.

## How it works

1. **Connect:** configure access to a supported document register and optional evidence references.
2. **Inspect:** review revision states, required metadata, and available approval information.
3. **Verify:** compare supported file or page content against separately captured references where configured.
4. **Review:** present findings and verification limits to the responsible team.

## What it does today

| Capability | Result |
| --- | --- |
| Revision and register checks | Reports missing metadata, conflicting revisions, and review-state gaps. |
| Notion register inspection | Reads supported document metadata from an authorized data source. |
| Signed-evidence checks | Verifies specific cryptographic properties of supplied evidence. |
| Source integrity checks | Compares supported source evidence with recorded references. |
| Read-only findings | Returns inconsistencies without changing approval status. |

## Get started

Install the Python package and run the included tests:

```bash
cd tools/document-control
python -m pip install -e ".[dev]"
python -m pytest tests -q
```

Configure an MCP-compatible client to run `python -m qarawork_document_control.server`. See the [getting started guide](../../docs/getting-started.md) and [source code](src/qarawork_document_control/server.py) for supported inputs and configuration.

Provide your own test data and appropriate read permissions. Keep credentials, private keys, and client-specific settings outside version control.

## Scope and limitations

A register status is not independent proof of approval. A valid hash or signature check establishes a defined technical property, not an approver's identity or authority. Trust depends on the integrity of the reference and associated key management.

The prototype does not enforce access permissions, provide independently immutable records, establish retention, or implement an electronic-approval workflow.

**Approval decisions, controlled records, and intended-use validation remain the adopting organization's responsibility.**

<sub>Prototype only; not a validated eQMS or evidence of ISO 13485 or 21 CFR Part 11 compliance.</sub>
