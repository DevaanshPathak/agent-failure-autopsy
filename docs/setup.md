# Setup

## Prerequisites

| Tool | Version | Check |
|---|---|---|
| Git | 2.40+ | `git --version` |
| uv | recent (installs Python 3.12 for you) | `uv --version` |
| Node.js + npm | Node 24 LTS | `node -v`, `npm -v` |
| GNU make | 4.x | `make -v` |

**Windows:** run every `make` command from **Git Bash**, not PowerShell. If `make` is missing, install it (MSYS2 `pacman -S make`, `scoop install make` or `choco install make`), or run the commands from the `Makefile` by hand.

## First run

```sh
git clone https://github.com/DevaanshPathak/agent-failure-autopsy.git
cd agent-failure-autopsy
make setup          # uv sync + npm install + creates .env from .env.example
```

Then edit `.env` at the repo root and add `TINYFISH_API_KEY` and `ANTHROPIC_API_KEY`. Never commit `.env`.

## Everyday commands

| Command | What it does |
|---|---|
| `make sample` | API in replay mode + web app. Open http://localhost:3000/dev to watch the hand-written sample run. **No API keys needed** |
| `make dev` | API on http://localhost:8000 and web app on http://localhost:3000 |
| `make api` / `make web` | One of the two |
| `make test` | API tests (pytest) + web tests (vitest) |
| `make lint` | ruff + ESLint + TypeScript |
| `make fmt` | Format everything (ruff, prettier) |
| `make types` | Regenerate `shared/schemas/contracts.schema.json` and `apps/web/lib/types.ts` after changing `apps/api/app/models.py`. Commit all three |

Useful URLs while `make dev` runs: http://localhost:8000/health (API status: mode, keys present, DB) and http://localhost:8000/docs (OpenAPI UI).

## Configuration

The API reads the repo-root `.env`; real environment variables win over it. `.env.example` lists the main variables (keys, model, `DATABASE_URL`, `MODE`, budgets, proxy country). Everything else has a default in `apps/api/app/config.py`. The web app talks to `http://localhost:8000` unless `NEXT_PUBLIC_API_BASE` is set in `apps/web/.env.local`.

**Claude spend is capped.** `ANTHROPIC_BUDGET_USD` (default 4.00) limits the total Claude spend, costed from real token usage and stored in the database, so it survives restarts. `curl localhost:8000/health` shows `claude_spent_usd`, `claude_budget_usd` and `claude_calls`. At the cap, Claude is no longer called: Rung 1 extraction is skipped and diagnosis uses the rules. Tests, replays and `/dev` never call Claude.

SQLite is the default database (`apps/api/autopsy.db`, gitignored). No migrations: delete the file when the schema changes.

## Troubleshooting

- **Ports 3000/8000 in use:** stop the other process, or run `uv run uvicorn app.main:app --port 8001` from `apps/api` and set `NEXT_PUBLIC_API_BASE=http://localhost:8001` in `apps/web/.env.local`.
- **`pytest` fails with "Access is denied" on its temp folder (Windows):** delete `%TEMP%\pytest-of-<you>`, or run with `PYTEST_DEBUG_TEMPROOT` pointing at a folder you own.
- **CI "contracts" job fails:** someone changed `models.py` without running `make types`. Run it and commit the generated files.
