# <img src="../../assets/tools/access-control.svg" width="58" height="58" align="center" alt="" /> MCP Access Control

**Make permissions match responsibilities.**

**Status: In design**

[← Back to the QARAWORK toolkit](../../README.md)

## Intended capability

Compare a defined role-and-permissions policy with the rights that connected systems expose. Flag unexpected editors, absent reviewers, excessive access and approval-role conflicts.

## Key design condition

A diagnostic MCP does **not** itself prevent someone with platform permissions from editing a document. Enforcement belongs to platform access controls, identity management and a validated approval process.

## Planned tests

- Detect an unintended editor on a controlled record.
- Detect a missing QARA reviewer permission.
- Verify a rejected action fails closed when access evidence is unavailable.

**Status:** concept only. No broad Notion/GitHub permission enforcement claim.
