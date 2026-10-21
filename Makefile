# Agent Failure Autopsy. Recipes are POSIX sh; on Windows run make from Git Bash.

.PHONY: setup api web dev test lint fmt types sample record baseline

setup:
	cd apps/api && uv sync
	cd apps/web && npm install
	@[ -f .env ] || { cp .env.example .env && echo "Created .env from .env.example: add your API keys"; }

api:
	cd apps/api && uv run uvicorn app.main:app --reload --port 8000

web:
	cd apps/web && npm run dev

dev:
	$(MAKE) -j2 api web

test:
	cd apps/api && uv run pytest -q
	cd apps/web && npm test -- --run

lint:
	cd apps/api && uv run ruff check . && uv run ruff format --check .
	cd apps/web && npm run lint && npm run typecheck

fmt:
	cd apps/api && uv run ruff format . && uv run ruff check --fix .
	cd apps/web && npx prettier --write .

types:
	cd apps/api && uv run python -m app.export_schema ../../shared/schemas/contracts.schema.json
	cd apps/web && npm run types

sample:
	@echo "Open http://localhost:3000/dev (no API keys needed)"
	MODE=replay $(MAKE) dev

record baseline:
	@echo "make $@ arrives in Phase 5 (P5-A2: scripts/record_trace.py)"; exit 1
