<div align="center">

<img src="../../assets/tools/traceability.svg" alt="" width="58" />

# MCP Traceability

**Connect requirements, development work, and test evidence.**

Identify missing traceability links, understand change impact, and support informed reviews without replacing your existing tools.

**Available · Open-source prototype · Notion + GitHub**

[← Back to QARAWORK](../../README.md)

</div>

## The problem

Requirements, code, and tests often live in different systems. When a requirement changes, teams need to understand which implementation and verification evidence relates to it:and where links are missing.

A passing test or an existing link alone does not establish adequate coverage.

## The benefits

- **QARA:** see traceability gaps and prepare better-informed reviews.
- **Product:** understand which requirements and changes need follow-up.
- **Development:** locate linked tests and supporting evidence without duplicating records.

**The result:** a clearer, reviewable picture of coverage and change impact.

## The solution

MCP Traceability connects supported Notion and GitHub information, checks explicit requirement-to-test links, and makes gaps visible. It can prepare draft change-impact information for human assessment.

It supports the existing workflow rather than acting as an approval authority or a new system of record.

## How it works

1. **Connect:** authorize access to supported requirements and development sources.
2. **Inspect:** identify explicit links between requirements and supported tests.
3. **Review:** examine missing links, available test evidence, and proposed change impacts.
4. **Export or hand off:** produce a traceability matrix or a draft for a responsible reviewer.

## What it does today

| Capability | Result |
| --- | --- |
| Traceability gap checks | Identifies requirements without explicit links in supported Python tests. |
| Matrix export | Exports requirement–test references to CSV or Excel, optionally with available matching CI evidence. |
| Change-impact preparation | Collects relevant change and requirement data for a draft assessment. |
| Confirmed draft updates | Writes supported draft fields only after explicit confirmation and a source recheck. |
| Controlled PR check | A **separate GitHub Actions workflow** checks designated PRs against recorded QARA decisions and requirement versions. |

## Get started

See the package at `tools/traceability/`, and follow the common installation guide at `../../docs/getting-started.md`.

Use your own Notion and GitHub sources and an MCP-compatible client. Store credentials and local configuration outside version control.

## Scope and limitations

The prototype supports selected Notion and GitHub workflows and explicit markers in Python tests. Other requirements sources and test frameworks require additional integration.

Linked tests do not prove test adequacy. Impact drafts do not constitute regulatory decisions. The separate PR check requires correct identification rules and enforced branch protection; it is not a general guarantee against bypass.

**Human review, authorization, deployment controls, and intended-use validation remain the adopting organization's responsibility.**

<sub>Prototype only; not a validated eQMS or proof of regulatory conformity.</sub>
