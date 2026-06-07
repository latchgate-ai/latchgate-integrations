.DEFAULT_GOAL := help
SHELL := /bin/bash -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────
# Single Python version for all CI and dev tasks.
# Override: make test PYTHON=3.13
PYTHON ?= 3.12

# ── Package lists ─────────────────────────────────────────────────────────
PY_PACKAGES  := common langchain crewai openai-agents pydantic
TS_PACKAGES  := ai-sdk
ALL_PACKAGES := $(PY_PACKAGES) $(TS_PACKAGES)

# Filter to a single package: make test PKG=langchain
ifdef PKG
  PY_TARGETS  := $(filter $(PKG),$(PY_PACKAGES))
  TS_TARGETS  := $(filter $(PKG),$(TS_PACKAGES))
else
  PY_TARGETS  := $(PY_PACKAGES)
  TS_TARGETS  := $(TS_PACKAGES)
endif

UV_RUN := uv run --python $(PYTHON)

# Transitive dependency CVEs with no upstream fix — suppress in pip-audit.
# chromadb 1.1.1: CVE-2026-45829 (pulled in by crewai, no fix released)
# diskcache 5.6.3: CVE-2025-69872 (pulled in by crewai, excluded from lockfile
#   but pip-audit still resolves it transitively)
PIP_AUDIT_IGNORE := \
	--ignore-vuln CVE-2026-45829 \
	--ignore-vuln CVE-2025-69872

# ── Help ──────────────────────────────────────────────────────────────────

.PHONY: help
help: ## Show this help
	@printf "\033[1mUsage:\033[0m make <target> [PKG=<package>] [PYTHON=3.x]\n\n"
	@printf "\033[1mPackages:\033[0m %s\n" "$(ALL_PACKAGES)"
	@printf "\033[1mPython:\033[0m  %s\n\n" "$(PYTHON)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@printf "\n\033[1mExamples:\033[0m\n"
	@printf "  make test                    # test everything\n"
	@printf "  make test PKG=langchain      # test langchain only\n"
	@printf "  make lint PKG=common         # lint common only\n"
	@printf "  make fmt                     # format all packages\n"
	@printf "  make test PYTHON=3.13        # test with Python 3.13\n"

# ── Sync / install ────────────────────────────────────────────────────────

.PHONY: sync
sync: ## Install dev dependencies for all packages
	@for pkg in $(PY_TARGETS); do \
		printf "\n\033[1;34m── sync $$pkg ──\033[0m\n"; \
		(cd "$$pkg" && uv sync --python $(PYTHON) --all-extras --group dev); \
	done
	@for pkg in $(TS_TARGETS); do \
		printf "\n\033[1;34m── sync $$pkg ──\033[0m\n"; \
		(cd "$$pkg" && npm ci); \
	done

# ── Test ──────────────────────────────────────────────────────────────────

.PHONY: test
test: ## Run tests (all or PKG=<name>)
	@for pkg in $(PY_TARGETS); do \
		printf "\n\033[1;32m── test $$pkg ──\033[0m\n"; \
		(cd "$$pkg" && $(UV_RUN) pytest -v; rc=$$?; \
			if [ $$rc -eq 5 ]; then printf "(no tests collected)\n"; \
			elif [ $$rc -ne 0 ]; then exit $$rc; fi) || exit 1; \
	done
	@for pkg in $(TS_TARGETS); do \
		printf "\n\033[1;32m── test $$pkg ──\033[0m\n"; \
		(cd "$$pkg" && npm test) || exit 1; \
	done

# ── Lint ──────────────────────────────────────────────────────────────────

.PHONY: lint
lint: ## Lint check (ruff + tsc --noEmit)
	@for pkg in $(PY_TARGETS); do \
		printf "\n\033[1;33m── lint $$pkg ──\033[0m\n"; \
		(cd "$$pkg" && $(UV_RUN) ruff check .) || exit 1; \
	done
	@for pkg in $(TS_TARGETS); do \
		printf "\n\033[1;33m── lint $$pkg ──\033[0m\n"; \
		(cd "$$pkg" && npm run lint) || exit 1; \
	done

# ── Format ────────────────────────────────────────────────────────────────

.PHONY: fmt
fmt: ## Auto-format (ruff format + prettier)
	@for pkg in $(PY_TARGETS); do \
		printf "\n\033[1;35m── fmt $$pkg ──\033[0m\n"; \
		(cd "$$pkg" && $(UV_RUN) ruff format . && $(UV_RUN) ruff check --fix .); \
	done
	@for pkg in $(TS_TARGETS); do \
		printf "\n\033[1;35m── fmt $$pkg ──\033[0m\n"; \
		(cd "$$pkg" && npm run format); \
	done

.PHONY: fmt-check
fmt-check: ## Check formatting without modifying files
	@for pkg in $(PY_TARGETS); do \
		printf "\n\033[1;35m── fmt-check $$pkg ──\033[0m\n"; \
		(cd "$$pkg" && $(UV_RUN) ruff format --check .) || exit 1; \
	done

# ── Typecheck ─────────────────────────────────────────────────────────────

.PHONY: typecheck
typecheck: ## Run type checks (mypy + tsc)
	@for pkg in $(PY_TARGETS); do \
		printf "\n\033[1;36m── typecheck $$pkg ──\033[0m\n"; \
		(cd "$$pkg" && $(UV_RUN) mypy .) || exit 1; \
	done
	@for pkg in $(TS_TARGETS); do \
		printf "\n\033[1;36m── typecheck $$pkg ──\033[0m\n"; \
		(cd "$$pkg" && npm run typecheck) || exit 1; \
	done

# ── Audit ─────────────────────────────────────────────────────────────────

.PHONY: audit
audit: ## Supply-chain dependency audit (pip-audit + npm audit)
	@for pkg in $(PY_TARGETS); do \
		printf "\n\033[1;31m── audit $$pkg ──\033[0m\n"; \
		(cd "$$pkg" && \
			uv export --python $(PYTHON) --no-hashes --frozen -o /tmp/_reqs_$$pkg.txt && \
			sed -i '/^-e /d; /^latchgate[@ ]/d; /^latchgate-/d; /^\.\./d; /git+/d' /tmp/_reqs_$$pkg.txt && \
			uvx --python $(PYTHON) pip-audit -r /tmp/_reqs_$$pkg.txt $(PIP_AUDIT_IGNORE)) || exit 1; \
	done
	@for pkg in $(TS_TARGETS); do \
		printf "\n\033[1;31m── audit $$pkg ──\033[0m\n"; \
		(cd "$$pkg" && npm audit --omit=dev) || exit 1; \
	done

# ── Build ─────────────────────────────────────────────────────────────────

.PHONY: build
build: ## Build wheels / npm pack
	@for pkg in $(PY_TARGETS); do \
		printf "\n\033[1;34m── build $$pkg ──\033[0m\n"; \
		(cd "$$pkg" && uv build --python $(PYTHON)) || exit 1; \
	done
	@for pkg in $(TS_TARGETS); do \
		printf "\n\033[1;34m── build $$pkg ──\033[0m\n"; \
		(cd "$$pkg" && npm run build && npm pack --pack-destination dist/) || exit 1; \
	done

# ── Clean ─────────────────────────────────────────────────────────────────

.PHONY: clean
clean: ## Remove build artifacts, caches, venvs
	@for pkg in $(ALL_PACKAGES); do \
		printf "cleaning $$pkg\n"; \
		rm -rf "$$pkg/dist" "$$pkg/.ruff_cache" "$$pkg/.mypy_cache" \
			"$$pkg/.pytest_cache" "$$pkg/__pycache__" "$$pkg/node_modules"; \
		find "$$pkg" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; \
	done
	@printf "done\n"

# ── CI (mirrors GitHub Actions) ──────────────────────────────────────────

.PHONY: ci
ci: lint fmt-check test ## Run the full CI gate locally
