# Agent Failure Autopsy

**TinyFish agents can do the work. We tell you when they didn't, why, and fix it automatically.** Agent Failure Autopsy is a reliability layer for TinyFish web agents. You give it a URL, a plain-English goal and, optionally, a check the output must pass. It climbs an escalation ladder: TinyFish Fetch first (read-only, free), then the TinyFish Agent with every step traced live, then the Agent with a stealth browser profile and a proxy. After every attempt an independent verifier checks the output instead of trusting the agent's own `COMPLETED`. When an attempt fails, a diagnoser names the failure, points at the failing step, quotes the evidence and patches the next attempt. Six failure classes are covered: needs interaction, popup overlay, bot block, misread page, auth wall and captcha. Retries stay inside a hard budget of attempts and credits. Auth walls and captchas stop at once with an honest reason instead of burning credits.

## Planned stack

- **Web:** Next.js (TypeScript, Tailwind): run form, live trace timeline with embedded browser view, results page
- **API:** FastAPI (Python): TinyFish client, escalation ladder, verifier, diagnoser, patch planner, SSE stream to the web app
- **Diagnosis:** rule-based classifier first, then Claude with strict JSON output
- **Storage:** SQLite by default, Postgres via `DATABASE_URL`
- **Web agents:** TinyFish Fetch and Agent (`/run-sse`), stealth browser profile and proxies

## Setup

Setup instructions arrive in Phase 1. Until then, `.env.example` lists the environment variables and `docs/architecture.md` shows how the pieces connect.
