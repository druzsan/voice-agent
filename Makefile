SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
MAKEFLAGS += --warn-undefined-variables --no-builtin-rules
.DEFAULT_GOAL := help

UV_RUN := uv --directory backend run
PNPM := pnpm --dir frontend
DEV_COMPOSE := docker compose -f compose.yaml -f compose.dev.yaml
# Message of a new migration (make db-revision m="...")
m ?=
# Arguments of the scripted live call (make call-smoke args="...")
args ?=

.PHONY: help
help: ## List the available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: init
init: ## Install dependencies and git hooks
init: init-backend init-frontend
	$(UV_RUN) --frozen pre-commit install

.PHONY: init-backend
init-backend: ## Install backend dependencies from uv.lock
	uv --directory backend sync --locked

.PHONY: init-frontend
init-frontend: ## Install frontend dependencies from pnpm-lock.yaml
	$(PNPM) install --frozen-lockfile

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
test-backend: ## Run backend tests (pytest; in-memory storage, no containers)
	$(UV_RUN) pytest

.PHONY: test-speech
test-speech: ## Run the speech tests with the real models (downloaded into backend/models if missing)
	$(UV_RUN) pytest -m speech

.PHONY: test-openai
test-openai: ## Run the tests against OpenAI's speech models (needs OPENAI_API_KEY; costs a few cents)
	$(UV_RUN) pytest -m openai

.PHONY: test-db
test-db: ## Run the customer care system's tests against PostgreSQL (needs `make dev`; uses its own test database)
	$(UV_RUN) pytest -m db

.PHONY: test-frontend
test-frontend: ## Run frontend tests (vitest)
	$(PNPM) test

.PHONY: build
build: ## Build the production images
	docker compose build

.PHONY: run
run: ## Run the production-like stack on http://localhost:8080
	docker compose up --build

.PHONY: dev
dev: ## Run the dev stack with hot reload on http://localhost:8080 (backend on :8000)
	@# Mount points for the volumes that hide .venv / node_modules (can't be created inside the read-only mounts)
	mkdir -p backend/.venv frontend/node_modules
	@# Fresh containers, so the volumes are filled from the current images (removes only anonymous volumes)
	$(DEV_COMPOSE) rm --stop --force --volumes
	$(DEV_COMPOSE) up --build

.PHONY: db-upgrade
db-upgrade: ## Apply the database migrations to the dev database
	mkdir -p backend/.venv
	$(DEV_COMPOSE) run --rm --build migrate

.PHONY: db-revision
db-revision: ## Generate a migration from the models against the dev database: make db-revision m="add x"
	@test -n "$(m)" || { echo 'Usage: make db-revision m="describe the change"'; exit 1; }
	$(UV_RUN) alembic upgrade head
	$(UV_RUN) alembic revision --autogenerate -m "$(m)"

.PHONY: seed
seed: ## Reset the customer care system to its 20 starting cases (dev database)
	$(UV_RUN) python -m voice_agent.crm.seed --reset

.PHONY: psql
psql: ## Open psql on the dev database
	$(DEV_COMPOSE) exec postgres psql --username voice_agent voice_agent

.PHONY: llm-smoke
llm-smoke: ## Ask the configured language model one question (settings from .env)
	$(UV_RUN) python -m scripts.llm_smoke

.PHONY: eval
eval: ## Run Carrie's scenario evaluation against the configured model (costs tokens): make eval args="--only DEL-1"
	$(UV_RUN) python -m scripts.scenario_eval $(args)

.PHONY: call-smoke
call-smoke: ## Make a scripted live call against the running stack: make call-smoke args="--speak question.wav"
	$(UV_RUN) python -m scripts.call_smoke $(args)

.PHONY: down
down: ## Stop and remove the containers
	$(DEV_COMPOSE) down

.PHONY: logs
logs: ## Follow the container logs
	$(DEV_COMPOSE) logs --follow

.PHONY: clean
clean: ## Remove containers, volumes (including the database) and the locally built images
	$(DEV_COMPOSE) down --volumes --rmi local
