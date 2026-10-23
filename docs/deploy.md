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

## The live demo: the API on Vercel too (real runs, shared caps)

The API can run as a Vercel Function (`apps/api/vercel_app.py`, project `agent-failure-autopsy-api`). Serverless changes three things, all switched on by env vars:

- **`RUN_IN_STREAM=true`:** Vercel stops background work once a response is sent, so a run executes inside the request that streams it (`GET /runs/{id}/stream`; the web app opens it right after `POST /runs`). Other viewers, cancel requests and interrupted runs go through the database.
- **`RUN_DEADLINE_S=270`:** a function request lasts at most 300 s (Hobby), so each run ends with an honest "Time budget spent" verdict before that. `STALE_RUN_S=330` closes runs whose instance was stopped anyway.
- **Postgres:** a free Neon database from the Vercel Marketplace (`DATABASE_URL` / `DATABASE_URL_UNPOOLED`, used as given). It holds runs and the spend counters.

Anyone with the URL spends your keys, so the shared caps are counted in the database for every visitor: one live run at a time, `LIVE_RUNS_PER_HOUR`, `LIVE_CREDIT_CAP` (estimated TinyFish credits across all runs; each run also stays within the default 4 attempts / 40 credits) and `ANTHROPIC_BUDGET_USD`. `/health` reports them and the home page shows what is left. Raise a cap with `vercel env add LIVE_CREDIT_CAP production --force` in the linked API directory, then redeploy. To reset the shared credit budget without deleting runs (they stay on the results page), set `LIVE_BUDGET_SINCE` to the current UTC time, e.g. `2026-10-23T12:30:00Z`, the same way.

```sh
# once: create + link the project, add Neon (accept its terms in the browser when asked), set env vars
vercel project add agent-failure-autopsy-api
D=$(sh scripts/api_bundle.sh /tmp/api-bundle) && cd "$D" && vercel link --yes --project agent-failure-autopsy-api
cp -r .vercel <repo>/apps/api/        # keep the link for the next deploys (gitignored)
vercel integration add neon --plan free_v3 -m region=iad1 -m auth=false -e production
# secrets from .env on stdin, e.g.: vercel env add TINYFISH_API_KEY production --sensitive
# plus RUN_IN_STREAM, RUN_DEADLINE_S, STALE_RUN_S, LIVE_CREDIT_CAP, LIVE_RUNS_PER_HOUR,
# ANTHROPIC_MODEL, ANTHROPIC_BUDGET_USD, CORS_ORIGINS=https://agent-failure-autopsy.vercel.app

# every deploy: bundle HEAD (apps/api + fixtures/) and publish
D=$(sh scripts/api_bundle.sh /tmp/api-bundle) && cd "$D" && vercel --prod --yes
```

Then point the web project at it: `NEXT_PUBLIC_API_BASE=https://agent-failure-autopsy-api.vercel.app` and `NEXT_PUBLIC_PUBLIC_DEMO=true` (the "Live demo" banner) for production, and redeploy the web app. Demo mode turns off; the bundled runs stay on the home page.

## Or host the API on a long-running service

Without the serverless switches the API runs each ladder as a background task and keeps the live event bus in memory. On Render, Railway, Fly.io or any VM:

- **One process, one worker:** `uv run uvicorn --factory app.main:create_app --host 0.0.0.0 --port $PORT` from `apps/api`.
- **Persistence:** a persistent disk for SQLite, or Postgres via `DATABASE_URL`.
- **Secrets:** `TINYFISH_API_KEY`, `ANTHROPIC_API_KEY`, `ANTHROPIC_BUDGET_USD` as the host's secrets, never in git.
- **CORS:** set `CORS_ORIGINS` to the Vercel URL. On Vercel, set `NEXT_PUBLIC_API_BASE` to the API URL and redeploy (demo mode then turns off).
- **Warning:** the API has no authentication. Anyone who can reach it can start live runs on your keys. Set the shared caps above (`LIVE_CREDIT_CAP`, `LIVE_RUNS_PER_HOUR`) before sharing its URL.
