# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.1] — 2026-06-08

0.1.0 was published manually to bootstrap PyPI and npm. This release adds
trusted publishing (PyPI) and npm token automation, and fixes the CI issues
discovered during that process.

### Fixed
- **latchgate-ai-sdk** — renamed from scoped `@latchgate/ai-sdk` to unscoped `latchgate-ai-sdk` (npm org creation was not possible).
- **release.yml** — ESM smoke test used `require()` instead of `import()`.
- **Makefile / CI** — `sed` pattern for `../` path deps broke on non-GNU sed; switched to portable `\.\.` pattern. Audit now uses `--ignore-vuln` instead of line removal for unfixable transitive CVEs.

## [0.1.1] - 2026-06-08

### Fixed
- **latchgate-ai-sdk** — migrated from removed `CoreTool` to `ToolSet` and `parameters` to `inputSchema` for Vercel AI SDK v6 compatibility. Peer dependency tightened to `ai>=6.0.0`.
- **Dependency bounds** — tightened lower bounds: `openai-agents>=0.13.0`, `pydantic-ai>=1.99.0`. Override vulnerable transitive deps where fixes exist (pyjwt≥2.13.0, starlette≥1.0.1, aiohttp≥3.14.0).
- **CI audit** — switched from sed-based line removal to `--ignore-vuln` for transitive dep CVEs with no upstream fix (chromadb, diskcache). Sed-based suppression was ineffective because pip-audit resolves full dependency trees.
- **CI smoke test** — fixed ESM smoke test (`import()` instead of `require()` for the ESM-only `latchgate-ai-sdk` package).
- **Build reproducibility** — pinned `exclude-newer` to fixed date instead of relative `"1 week"`.

### Added
- **common test suite** — 107 tests covering serialization (output-only filtering), discovery (identifier validation, description redaction, HTTP flow), schema conversion, transport resolution, and sync bridge.
- **LICENSE** added to common, openai-agents, and pydantic packages.

## [0.1.0] — 2026-06-06

### Added
- **latchgate-integrations-common** — shared package for discovery, schema conversion, result serialization, transport resolution, and sync bridge. Security-relevant redaction logic (expose_security_details, output-only serialization) exists in exactly one place.
- **Audit metadata callback** — optional `on_audit` parameter on all toolset factories. Receives `AuditRecord(action_id, receipt_id, trace_id, verification)` after every successful execution. Default behaviour (INFO-level logging) is preserved.
- **Background-thread sync bridge** — `latchgate_common.sync.run_sync()` replaces `nest_asyncio.apply()` in LangChain and CrewAI. No global side-effects, safe in Jupyter, FastAPI, and Celery.
- **Pydantic AI lifecycle** — `LatchGateToolset` now supports `close()`, `async with`, matching LangChain and CrewAI.
- **Runnable examples** — one minimal script per framework in `examples/`. Works against a local LatchGate instance with the built-in `http_fetch` action. No LLM key required for the basic path.
- **CI/CD** — GitHub Actions workflows for testing (Python 3.12 + Node 20), supply-chain audit (pip-audit, OWASP CVE-lite), smoke installs, and tag-triggered release to PyPI (trusted publishing) and npm (provenance).
- **Makefile** — top-level dev workflow: `make test`, `make lint`, `make fmt`, `make audit`, `make ci`. Supports `PKG=<name>` filtering.

### Security
- Tool descriptions default to `expose_security_details="none"`, omitting egress profiles, allowed domains, database modes, and statement IDs from model-visible output.
- Result serialization strips `receipt_id`, `trace_id`, and `verification` from model-facing output. Metadata is emitted only via structured log and the optional `on_audit` callback.
- Approval IDs are never returned to the model. They are routed to framework-specific side-channels (LangChain `run_manager`, logging).
- OpenAI Agents strict schema conversion validated against the real SDK's `ensure_strict_json_schema`.

### Framework support
- **LangChain** (`latchgate-langchain`) — `BaseTool` + `run_manager` callback side-channel for receipts and approvals.
- **CrewAI** (`latchgate-crewai`) — `BaseTool` + sync/async factories.
- **OpenAI Agents SDK** (`latchgate-openai-agents`) — `FunctionTool` factory with strict JSON Schema conversion.
- **Pydantic AI** (`latchgate-pydantic-ai`) — `AbstractToolset` implementation with full lifecycle support.
- **Vercel AI SDK** (`latchgate-ai-sdk`) — TypeScript `ToolSet` records via `latchgateToolset()`.

[0.1.1]: https://github.com/latchgate-ai/latchgate-integrations/releases/tag/v0.1.1
[0.1.0]: https://github.com/latchgate-ai/latchgate-integrations/releases/tag/v0.1.0
