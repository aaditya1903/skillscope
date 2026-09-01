# SkillScope developer commands. Every target is a thin, readable wrapper
# around the command it runs, so nothing here hides a step.

SHELL := /bin/bash
TEST_DATABASE_URL ?= postgresql+psycopg://skillscope_test:skillscope_test@127.0.0.1:5433/skillscope_test
COMPOSE := docker compose

.DEFAULT_GOAL := help
.PHONY: help setup db-up db-down migrate ingest index evaluate demo dev serve \
        frontend-install frontend-dev test test-model lint format typecheck \
        check docker-up docker-down docker-smoke clean-clone-smoke clean

help: ## List the available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Install locked backend and frontend dependencies
	uv sync --locked
	npm ci --prefix frontend

db-up: ## Start the development and test databases
	$(COMPOSE) up -d --wait --wait-timeout 60 db
	$(COMPOSE) --profile test up -d --wait --wait-timeout 60 db-test

db-down: ## Stop every database container
	$(COMPOSE) --profile test --profile app down

migrate: ## Apply migrations to the development database
	uv run alembic upgrade head

ingest: ## Discover and ingest public skills; requires GITHUB_TOKEN
	uv run skillscope ingest discover --target-skills 200
	uv run skillscope ingest run

index: ## Embed the frozen corpus; requires the local model extra
	uv run --extra model skillscope index dense

evaluate: ## Compare BM25, dense and hybrid on the development split
	uv run --extra model skillscope evaluate compare --split development

demo: ## Load the token-free demonstration corpus into the current database
	uv run alembic upgrade head
	uv run skillscope demo load

serve: ## Run the API against the evaluated local corpus
	uv run --extra model skillscope serve

frontend-install: ## Install locked frontend dependencies
	npm ci --prefix frontend

frontend-dev: ## Run the interface against a locally running API
	npm run dev --prefix frontend

dev: ## Print the two commands a local development session needs
	@echo "Run in two terminals:"
	@echo "  make serve"
	@echo "  make frontend-dev"

test: ## Run the backend suite with coverage against the test database
	SKILLSCOPE_TEST_DATABASE_URL="$(TEST_DATABASE_URL)" \
		uv run pytest --cov=skillscope --cov-report=term-missing --cov-fail-under=80
	npm test --prefix frontend

test-model: ## Run the opt-in smoke test against the real embedding model
	SKILLSCOPE_RUN_MODEL_SMOKE=1 uv run --extra model pytest tests/model -v

lint: ## Check formatting and lint both workspaces
	uv run ruff format --check .
	uv run ruff check .
	npm run lint --prefix frontend

format: ## Apply formatting fixes
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## Type-check both workspaces
	uv run mypy src
	npm run typecheck --prefix frontend

check: lint typecheck test ## Run the complete local quality gate

docker-up: ## Start the containerised demonstration stack
	$(COMPOSE) --profile app up -d --build --wait --wait-timeout 300
	@echo "Interface: http://localhost:5173"
	@echo "API:       http://localhost:8000/docs"

docker-down: ## Stop the containerised stack and remove only its own volumes
	$(COMPOSE) --profile app down
	docker volume rm --force skillscope_demo_postgres_data \
		skillscope_demo_evidence skillscope_demo_config 2>/dev/null || true

docker-smoke: ## Build, start and probe the containerised stack, then tear it down
	./scripts/docker_smoke.sh

clean-clone-smoke: ## Verify a fresh clone builds and passes in a temporary directory
	./scripts/clean_clone_smoke.sh

clean: ## Remove local build and tool caches
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov frontend/dist
