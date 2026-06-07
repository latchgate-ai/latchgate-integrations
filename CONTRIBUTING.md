# Contributing to latchgate-integrations

Contributions are welcome. Each package is independent — you can work on one without touching the others.

## Reporting issues

**Security vulnerabilities** — do not open a public issue. See [SECURITY.md](SECURITY.md).

**Bugs** — open a GitHub issue with: package name, package version, framework version, Python/Node version, minimal reproduction, expected vs. actual behavior.

**Feature requests** — open an issue describing the use case and target framework. For new framework integrations, wait for maintainer feedback before investing significant effort — there may be architectural constraints that aren't obvious from the code.

## Development setup

**Prerequisites:** Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) for the Python packages; Node.js 20+ and `npm` for the TypeScript package. GNU Make for the top-level workflow.

**First-time setup:**

```bash
git clone https://github.com/latchgate-ai/latchgate-integrations.git
cd latchgate-integrations
make sync       # installs all dev dependencies (uv sync + npm ci)
make test       # run all tests
```

**Single package:**

```bash
# Python
cd langchain && uv sync --all-extras --group dev
uv run pytest -v

# TypeScript
cd ai-sdk && npm ci
npm run build && npm test
```

Tests are self-contained — mocked HTTP, no running LatchGate instance required.

## Running the full CI gate locally

```bash
make ci         # lint + format check + test (mirrors GitHub Actions)
make audit      # supply-chain vulnerability scan (pip-audit + npm audit)
```

## Code style

**Python:** [ruff](https://docs.astral.sh/ruff/) for linting and formatting, [mypy](https://mypy-lang.org/) strict mode for type checking. `make fmt` auto-formats; `make lint` checks.

**TypeScript:** strict mode, ESM, target ES2022. `npm run lint` checks; `npm run format` auto-formats.

Keep packages small. Each integration should be under 300 LOC of source (excluding tests and the shared common package).

## Testing

Every package must have self-contained tests that run without external dependencies. Mock the LatchGate HTTP API and SDK client. Test all error paths (denied, approval required, budget exhausted, unavailable, transport failure).

The `common` package contains security-critical code (output-only serialization, description redaction, identifier validation). Changes there require thorough test coverage — especially for any code that controls what the model sees.

## Making changes

1. Fork the repo and create a branch from `main`.
2. Make your changes. Add tests for new functionality.
3. Run `make fmt` to auto-format and fix lints.
4. Run `make ci` (always). Run `make audit` if you changed dependencies.
5. Commit using [conventional commits](#commit-conventions).
6. Open a PR against `main`.

## Commit conventions

[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>(<scope>): <description>
```

Types: `feat`, `fix`, `security`, `refactor`, `test`, `docs`, `chore`, `perf`.

Scope is optional but helpful: the affected package, e.g. `langchain`, `ai-sdk`, `common`, `ci`.

```
feat(langchain): add streaming support for tool execution
fix(common): reject action_ids containing path separators
security(common): strip verification metadata from model output
```

## Pull requests

1. One package per PR unless changes are coupled.
2. Include tests for new functionality.
3. Update the package README if the public API changes.
4. Ensure `make ci` passes.

## Security-sensitive changes

Changes to `common/` (serialization, discovery, schema, transport) or any code controlling what the model sees receive extra scrutiny. For these changes:

1. Describe the security impact in the PR description.
2. Add regression tests that verify the security invariant holds.
3. If the change affects output filtering or description redaction, test both the positive case (correct data reaches the model) and the negative case (sensitive data is excluded).

## License

By contributing, you agree that your contributions will be licensed under the same license as this project (Apache-2.0).
