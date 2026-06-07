# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] — 2026-06-07

### Added
- **latchgate-integrations-common** — shared package for discovery, schema
  conversion, result serialization, transport resolution, and sync bridge.
  Security-relevant redaction logic (expose_security_details, output-only
  serialization) exists in exactly one place. 107 tests covering all modules.
- **latchgate-langchain** — LangChain `BaseTool` integration with
  `run_manager` callback side-channel for receipts and approvals.
- **latchgate-crewai** — CrewAI `BaseTool` integration with sync/async
  factories. Safe in Jupyter, FastAPI, and Celery via background-thread
  sync bridge (no `nest_asyncio`).
- **latchgate-openai-agents** — OpenAI Agents SDK `FunctionTool` factory
  with strict JSON Schema conversion (nullable wrapping for optional fields).
- **latchgate-pydantic-ai** — Pydantic AI `AbstractToolset` implementation
  with full lifecycle support (`close()`, `async with`).
- **@latchgate/ai-sdk** — Vercel AI SDK (v6+) `ToolSet` records via
  `latchgateToolset()`. TypeScript, ESM-only.
- **Audit metadata callback** — optional `on_audit` parameter on all toolset
  factories. Receives `AuditRecord(action_id, receipt_id, trace_id,
  verification)` after every successful execution. Default behaviour
  (INFO-level logging) is preserved.
- **UDS transport** — all integrations default to Unix Domain Socket discovery
  when no explicit URL or `LATCHGATE_URL` is set, matching `latchgate up`.
- **Runnable examples** — one minimal script per framework in `examples/`.
  Works against a local LatchGate instance with the built-in `http_fetch`
  action.
- **CI/CD** — GitHub Actions workflows for testing (Python 3.12 + Node 20),
  supply-chain audit (pip-audit with `--ignore-vuln` for unfixable transitive
  CVEs, OWASP CVE-lite for npm), smoke installs from built artifacts, and
  tag-triggered release to PyPI (trusted publishing) and npm (provenance).
- **Makefile** — top-level dev workflow: `make test`, `make lint`, `make fmt`,
  `make audit`, `make ci`. Supports `PKG=<name>` filtering and `PYTHON=3.x`
  override.

### Security
- Tool descriptions default to `expose_security_details="none"`, omitting
  egress profiles, allowed domains, database modes, and statement IDs from
  model-visible output. A compromised model could use exposed enforcement
  topology for targeted attacks.
- Result serialization strips `receipt_id`, `trace_id`, and `verification`
  from model-facing output. Metadata is emitted only via structured log
  and the optional `on_audit` callback.
- Approval IDs are never returned to the model. They are routed to
  framework-specific side-channels (LangChain `run_manager`, logging).
- Action identifiers are validated against path traversal before URL
  interpolation during discovery. Rejects `../`, query strings, fragments,
  and other injection patterns.
- Vulnerable transitive dependencies overridden where fixes exist
  (pyjwt≥2.13.0, starlette≥1.0.1, aiohttp≥3.14.0). Unfixable CVEs
  (chromadb, diskcache via crewai) suppressed with explicit `--ignore-vuln`.
