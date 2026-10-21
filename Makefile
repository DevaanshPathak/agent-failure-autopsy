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
	cd apps/api && uv run ruff check . ../../scripts && uv run ruff format --check . ../../scripts
	cd apps/web && npm run lint && npm run typecheck

fmt:
	cd apps/api && uv run ruff format . ../../scripts && uv run ruff check --fix . ../../scripts
	cd apps/web && npx prettier --write .

types:
	cd apps/api && uv run python -m app.export_schema ../../shared/schemas/contracts.schema.json
	cd apps/web && npm run types

sample:
	@echo "Open http://localhost:3000/dev (no API keys needed)"
	MODE=replay $(MAKE) dev

record:
	@[ -n "$(SITE)" ] || { echo "usage: make record SITE=<id from fixtures/sites.yaml>"; exit 1; }
	cd apps/api && uv run python ../../scripts/record_trace.py --site $(SITE)

baseline:
	@[ -n "$(SITE)" ] || { echo "usage: make baseline SITE=<id from fixtures/sites.yaml>"; exit 1; }
	cd apps/api && uv run python ../../scripts/record_trace.py --site $(SITE) --baseline
