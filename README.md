# LatchGate Integrations

Framework integrations for [LatchGate](https://github.com/latchgate-ai/latchgate), execution security kernel for AI agents.

[![CI](https://github.com/latchgate-ai/latchgate-integrations/actions/workflows/ci.yml/badge.svg)](https://github.com/latchgate-ai/latchgate-integrations/actions/workflows/ci.yml)
![License](https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/python-3.12-blue?style=flat-square)
![Node](https://img.shields.io/badge/node-20%2B-green?style=flat-square)

[LatchGate docs](https://latchgate-docs.pages.dev/) · [Integration guides](https://latchgate-docs.pages.dev/integrations/) · [Report a vulnerability](SECURITY.md)

---

## What this does

Every package wraps LatchGate for a specific agent framework. Tool calls go through the full enforcement pipeline — **auth → policy → WASM sandbox → verification → signed receipt** — instead of executing directly. The model never holds credentials and never contacts external systems.

| Package | Install | Framework |
|---|---|---|
| [`latchgate-langchain`](langchain/) | `pip install latchgate-langchain` | [LangChain](https://www.langchain.com/) |
| [`latchgate-crewai`](crewai/) | `pip install latchgate-crewai` | [CrewAI](https://www.crewai.com/) |
| [`latchgate-openai-agents`](openai-agents/) | `pip install latchgate-openai-agents` | [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) |
| [`latchgate-pydantic-ai`](pydantic/) | `pip install latchgate-pydantic-ai` | [Pydantic AI](https://ai.pydantic.dev/) |
| [`latchgate-ai-sdk`](ai-sdk/) | `npm install latchgate-ai-sdk` | [Vercel AI SDK](https://ai-sdk.dev/) |
| [`latchgate-integrations-common`](common/) | *(internal — not a public API)* | — |

## Quick start

Start a LatchGate instance:

```bash
curl -fsSL https://raw.githubusercontent.com/latchgate-ai/latchgate/main/install.sh | bash
latchgate up
```

Then pick your framework:

```python
# LangChain
from latchgate_langchain import LatchGateToolset

async with await LatchGateToolset.create() as toolset:
    tools = toolset.get_tools()

# CrewAI
from latchgate_crewai import LatchGateToolset

async with await LatchGateToolset.create() as toolset:
    tools = toolset.all()

# OpenAI Agents SDK
from latchgate_openai_agents import latchgate_tools

tools = await latchgate_tools()

# Pydantic AI
from pydantic_ai import Agent
from latchgate_pydantic_ai import LatchGateToolset

async with await LatchGateToolset.create() as toolset:
    agent = Agent("openai:gpt-4o", toolsets=[toolset])
```

```typescript
// Vercel AI SDK
import { latchgateToolset } from "latchgate-ai-sdk";
import { generateText } from "ai";

const { tools, close } = await latchgateToolset();
try {
  const { text } = await generateText({ model, tools, prompt: "..." });
} finally {
  await close();
}
```

All examples default to `latchgate up`'s Unix Domain Socket transport — no URL required. Pass `gate_url="http://localhost:3000"` / `gateUrl: "http://localhost:3000"` for explicit TCP, or set `LATCHGATE_URL`.

See [`examples/`](examples/) for complete runnable scripts.

## How it works

```
Framework (LangChain, CrewAI, ...)
  │
  ├─ Discovery     GET /v1/actions + JSON Schemas (unauthenticated, structural only)
  ├─ Wrapping      Framework-native tool objects with discovered schemas
  ├─ Execution     LatchGate SDK client → DPoP auth → gate pipeline
  │
  ▼
Model sees only the action output (never receipts, traces, or verification)
```

1. **Discovery** — fetch actions and JSON Schemas from LatchGate's REST API. No credentials involved.
2. **Wrapping** — create framework-native tool objects with the discovered schemas and descriptions.
3. **Execution** — tool calls go through the LatchGate SDK client which handles DPoP auth, lease management, and error mapping.

Every side effect is gated, audited, and receipted.

## Security properties

**Output-only serialization.** Tool output contains only the action result. Receipt IDs, trace IDs, and verification outcomes are never returned to the model — a compromised model could use them to forge downstream evidence, correlate execution traces, or craft targeted social-engineering prompts. Enforcement metadata is emitted at INFO log level for orchestrator consumption.

**Description redaction.** By default, tool descriptions omit egress profiles, allowed domains, database modes, and statement IDs. Exposing enforcement topology to a potentially compromised model leaks information useful for targeted attacks. Pass `expose_security_details="debug"` only in trusted development environments.

**Error isolation.** LatchGate errors (denied, approval required, budget exhausted) are returned as structured text the model can reason about. Approval IDs are routed to framework-specific side-channels (LangChain `run_manager`, logging), never to the model.

## Audit metadata

Receipt metadata (receipt ID, trace ID, verification outcome) is logged at INFO level by default. Consume it programmatically with the `on_audit` callback:

```python
from latchgate_common.audit import AuditRecord

def on_audit(record: AuditRecord) -> None:
    db.store(record.receipt_id, record.trace_id, record.verification)

toolset = await LatchGateToolset.create(on_audit=on_audit)
```

```typescript
const { tools } = await latchgateToolset({
  onAudit: ({ receiptId, traceId, verification }) => {
    db.store(receiptId, traceId, verification);
  },
});
```

## Repository structure

```
latchgate-integrations/
├── common/              shared discovery, schema, serialization, transport
├── langchain/           LangChain BaseTool + run_manager callback side-channel
├── crewai/              CrewAI BaseTool + sync/async factories
├── openai-agents/       OpenAI Agents FunctionTool + strict schema conversion
├── pydantic/            Pydantic AI AbstractToolset with full lifecycle
├── ai-sdk/              Vercel AI SDK ToolSet via latchgateToolset()
├── examples/            one runnable script per framework
├── .github/workflows/   CI (test + audit + smoke) and tag-triggered release
└── Makefile             make test / lint / fmt / audit / ci [PKG=<name>]
```

## Development

```bash
make sync                  # install all dev dependencies (uv + npm)
make test                  # test everything
make test PKG=langchain    # test one package
make lint                  # ruff check + tsc --noEmit
make audit                 # pip-audit + npm audit
make ci                    # full local CI gate (lint + fmt-check + test)
```

Tests are self-contained — mocked HTTP, no running LatchGate instance needed.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

If you find a security vulnerability, **do not open a public issue**. See [SECURITY.md](SECURITY.md).

For vulnerabilities in LatchGate core (server, kernel, auth, policy, ledger, providers), report to [latchgate-ai/latchgate](https://github.com/latchgate-ai/latchgate/security/advisories/new).

## License

[Apache License, Version 2.0](LICENSE).
