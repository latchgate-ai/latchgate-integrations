# latchgate-integrations-common

Shared discovery, schema conversion, serialization, and transport logic for [LatchGate](https://github.com/latchgate-ai/latchgate) framework integrations.

This package is an **internal dependency** — not a public SDK. It provides the canonical implementation of security-relevant code used by:

- [`latchgate-langchain`](../langchain/)
- [`latchgate-crewai`](../crewai/)
- [`latchgate-openai-agents`](../openai-agents/)
- [`latchgate-pydantic-ai`](../pydantic/)

## Modules

| Module | Responsibility |
|---|---|
| `discovery` | Action registry fetch, `expose_security_details` redaction |
| `schema` | JSON Schema → Pydantic model conversion |
| `serialization` | Output-only result filtering (strips receipt/trace/verification) |
| `transport` | Gate URL + UDS transport resolution |
| `audit` | `AuditRecord` dataclass and `AuditCallback` protocol |
| `sync` | Sync-to-async bridge via background thread (no `nest_asyncio`) |

## Why a separate package?

Every function in this package is security-relevant. Duplicating it across framework adapters meant a fix in one copy could be missed in another. A single implementation eliminates drift.
