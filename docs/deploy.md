# Deploying

## The demo on Vercel (no backend, no keys, $0)

The web app has a **static demo mode**. It plays recorded runs (UI-event JSONL files bundled in `apps/web/public/demo/`) entirely in the browser: the ladder, diagnoses, red failing steps, verdicts and the results page. No API, no API keys, and nobody can spend your TinyFish or Anthropic credit through the public link.

Demo mode is on automatically for Vercel builds that have no `NEXT_PUBLIC_API_BASE`. It can be forced with `NEXT_PUBLIC_DEMO_MODE=true|false`.

```sh
cd apps/web
npx vercel login              # once, opens the browser
npx vercel link               # once: create/link the project (root = apps/web)
npx vercel --prod             # build on Vercel and publish
```

After recording demo sites (`make record SITE=<id>`, see `docs/demo.md`), refresh the bundled data, commit, and redeploy:

```sh
cd apps/web && npm run demo:sync && cd ../.. && git add apps/web/public/demo fixtures/traces
```

## Why the API is not on Vercel

The FastAPI backend runs each ladder as a background task for minutes, keeps the live event bus in memory, and stores runs in SQLite. Vercel functions are short-lived and stateless, with no persistent disk. Host the API on a long-running service instead (Render, Railway, Fly.io or any VM):

- **One process, one worker:** `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT` from `apps/api`.
- **Persistence:** a persistent disk for SQLite, or Postgres via `DATABASE_URL=postgresql+asyncpg://…`.
- **Secrets:** `TINYFISH_API_KEY`, `ANTHROPIC_API_KEY`, `ANTHROPIC_BUDGET_USD` as the host's secrets, never in git.
- **CORS:** set `CORS_ORIGINS` to the Vercel URL. On Vercel, set `NEXT_PUBLIC_API_BASE` to the API URL and redeploy (demo mode then turns off).
- **Warning:** the API has no authentication. Anyone who can reach it can start live runs on your keys (the per-run and Claude caps still apply). Keep it private, or add an access check, before sharing its URL.
