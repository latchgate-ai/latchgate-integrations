# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest release | Yes |
| older releases | No |

Only the latest release receives security updates. Pin to a specific version for production and upgrade promptly when a security advisory is published.

## Reporting a Vulnerability

**Do not open a public issue.**

1. **Preferred:** use [GitHub Private Vulnerability Reporting](https://github.com/latchgate-ai/latchgate-integrations/security/advisories/new).
2. **Fallback:** email m2papierz@gmail.com with subject `[LatchGate Integrations Security]`.

Include: description of the vulnerability and its impact, affected package(s) and version(s), reproduction steps or proof of concept, and severity assessment if known.

## Severity Classification

We use [CVSS v3.1](https://www.first.org/cvss/v3.1/specification-document) for severity assessment:

| Severity | CVSS Score | Response target |
|----------|------------|-----------------|
| Critical | 9.0 – 10.0 | Fix within 3 days, advisory within 24h of fix |
| High | 7.0 – 8.9 | Fix within 5 days |
| Medium | 4.0 – 6.9 | Fix within 14 days |
| Low | 0.1 – 3.9 | Fix in next scheduled release |

These are targets, not guarantees. Complex issues may take longer. We will communicate progress to the reporter throughout.

## Response Timeline

| Step | Target |
|------|--------|
| Acknowledgement | 48 hours |
| Triage and severity assessment | 3 business days |
| Fix (see severity table above) | 3 – 14 days |
| Public disclosure | After fix is released |

## Coordinated Disclosure

We follow coordinated disclosure. We ask reporters to keep findings confidential until a fix is released. We will coordinate a disclosure timeline with the reporter and request a CVE where applicable.

We credit reporters in the release notes and security advisory unless anonymity is requested.

## Safe Harbor

We consider security research conducted in good faith to be authorized and will not pursue legal action against researchers who:

- Make a good-faith effort to avoid privacy violations, data destruction, and service disruption
- Only interact with accounts they own or with explicit permission of the account holder
- Do not exploit a vulnerability beyond the minimum necessary to demonstrate it
- Report the vulnerability through the channels described above before any public disclosure

## Scope

### In scope

This policy covers all integration packages in this repository:

- **latchgate-integrations-common** — shared discovery, schema conversion, result serialization, transport resolution
- **latchgate-langchain** — LangChain BaseTool integration
- **latchgate-crewai** — CrewAI BaseTool integration
- **latchgate-openai-agents** — OpenAI Agents SDK FunctionTool integration
- **latchgate-pydantic-ai** — Pydantic AI AbstractToolset integration
- **latchgate-ai-sdk** — Vercel AI SDK ToolSet integration
- **CI/CD pipeline** — GitHub Actions workflows, release pipeline

Security-relevant areas include output-only serialization (what the model sees), description redaction (enforcement topology exposure), identifier validation (path traversal), and the sync-to-async bridge.

### Out of scope

- LatchGate core (server, kernel, auth, policy, ledger, providers) — report to [latchgate-ai/latchgate](https://github.com/latchgate-ai/latchgate/security/advisories/new)
- Python SDK (`latchgate` on PyPI) and TypeScript SDK (`latchgate` on npm) — report to [latchgate-ai/latchgate](https://github.com/latchgate-ai/latchgate/security/advisories/new)
- Example scripts in `examples/`
- Third-party framework bugs (LangChain, CrewAI, etc.)
