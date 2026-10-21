# Agent Failure Autopsy

**TinyFish agents can do the work. We tell you when they didn't, why, and fix it automatically.** Agent Failure Autopsy is a reliability layer for TinyFish web agents. You give it a URL, a plain-English goal and, optionally, a check the output must pass. It climbs an escalation ladder: TinyFish Fetch first (read-only, free), then the TinyFish Agent with every step traced live, then the Agent with a stealth browser profile and a proxy. After every attempt an independent verifier checks the output instead of trusting the agent's own `COMPLETED`. When an attempt fails, a diagnoser names the failure, points at the failing step, quotes the evidence and patches the next attempt. Six failure classes are covered: needs interaction, popup overlay, bot block, misread page, auth wall and captcha. Retries stay inside a hard budget of attempts and credits. Auth walls and captchas stop at once with an honest reason instead of burning credits.

## What it does

- **Escalation ladder:** Rung 1 TinyFish Fetch + Claude extraction (0 TinyFish credits), Rung 2 TinyFish Agent (`/run-sse`, every event streamed), Rung 3 Agent with a stealth browser and a proxy. A bot wall seen by Fetch skips Rung 2.
- **Independent verifier:** the user's expected check, the output schema, and detectors for empty or null results, self-reported failure, access-denied pages, 403s, login walls and captchas.
- **Diagnosis:** six failure classes, from deterministic rules first and Claude (strict JSON, verbatim evidence) when the rules are unsure. Each diagnosis points at the failing step and patches the next attempt: a goal prefix that dismisses popups, an interaction suffix, a tighter schema, or a free re-extraction from the cached Fetch text.
- **Budget:** hard caps on attempts and estimated credits (1 per agent step). The TinyFish run is cancelled at the limit. Auth walls and captchas stop at once.
- **Demo safety:** recorded runs replay offline under a REPLAY badge, a one-click switch to replay is available mid-run, and a results page compares credits with a naive "always stealth, run 3 times" baseline.

## Stack

- **Web:** Next.js 16 (TypeScript, Tailwind): run form, live run view (browser panel, trace timeline, ladder, diagnosis and verdict cards), results page, `/dev`
- **API:** FastAPI (Python 3.12): TinyFish client (raw httpx), ladder controller, verifier, rules + Claude diagnoser, patch planner, replay player, SSE stream to the web app
- **Storage:** SQLite by default, Postgres via `DATABASE_URL`
- **Contracts:** pydantic models in `apps/api/app/models.py`, exported to JSON Schema and generated into TypeScript (`make types`)

## Setup

You need uv, Node 24 and GNU make (on Windows, run make from Git Bash).

```sh
make setup     # install dependencies and create .env from .env.example
make sample    # open http://localhost:3000/dev: a full sample run, no API keys needed
make dev       # API on :8000 and web app on :3000 (add your keys to .env first)
make test      # API and web tests
```

See [docs/setup.md](docs/setup.md) for details, [docs/architecture.md](docs/architecture.md) for how the pieces connect, and [docs/demo.md](docs/demo.md) for recording the demo sites and running the demo.
