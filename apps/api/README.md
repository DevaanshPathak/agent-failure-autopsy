# apps/api

The FastAPI backend. It holds the TinyFish client, the escalation ladder (Fetch → Agent → Agent + stealth/proxy), the independent verifier, the diagnoser (rules first, then Claude), the patch planner, the replay player and persistence (SQLite by default, Postgres via `DATABASE_URL`). It streams every trace event to the web app over SSE.
Phase 1 sets it up (contracts, `/health`, `/dev/sample-stream`). Phase 2 adds the runner and verifier, Phase 3 the ladder and diagnoser, Phase 4 stealth and patches, and Phase 5 replay and `/stats`.
