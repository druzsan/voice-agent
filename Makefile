SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
MAKEFLAGS += --warn-undefined-variables --no-builtin-rules
.DEFAULT_GOAL := help

UV_RUN := uv --directory backend run
PNPM := pnpm --dir frontend

.PHONY: help
help: ## List the available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: init
init: ## Install dependencies and git hooks
	uv --directory backend sync --locked
	$(PNPM) install --frozen-lockfile
	$(UV_RUN) --frozen pre-commit install

.PHONY: check
check: ## Format, lint (with fixes) and type-check backend and frontend
check: check-backend check-frontend

.PHONY: check-backend
check-backend: ## Format, lint (with fixes) and type-check the backend, check uv.lock
	$(UV_RUN) ruff format .
	$(UV_RUN) ruff check --fix .
	$(UV_RUN) pyright
	uv --directory backend lock --check

.PHONY: check-frontend
check-frontend: ## Format, lint (with fixes) and type-check the frontend
	$(PNPM) format
	$(PNPM) lint:fix
	$(PNPM) typecheck

.PHONY: pre-commit
pre-commit: ## Run all pre-commit hooks on all files
	$(UV_RUN) --frozen pre-commit run --all-files

.PHONY: test
test: test-backend test-frontend ## Run backend and frontend tests

.PHONY: test-backend
test-backend: ## Run backend tests (pytest)
	$(UV_RUN) pytest

.PHONY: test-frontend
test-frontend: ## Run frontend tests (vitest)
	$(PNPM) test
