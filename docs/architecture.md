# Architecture

The browser only talks to our API. The API holds both API keys and is the only thing that calls TinyFish and Claude. The one direct browser → TinyFish link is the read-only live-view iframe (`streaming_url`), which TinyFish documents as safe to expose.

```mermaid
flowchart LR
  subgraph WEB["apps/web (Next.js)"]
    FORM["Run form<br/>demo sites + paste-any-URL"]
    VIEW["Run view<br/>BrowserPanel · TraceTimeline · LadderStepper<br/>DiagnosisCard · VerdictCard"]
    RES["Results page"]
  end

  subgraph API["apps/api (FastAPI)"]
    ROUTES["routes<br/>POST /runs · GET /runs/{id}<br/>GET /runs/{id}/stream · GET /stats"]
    LADDER["ladder controller<br/>attempt loop + budget"]
    VERIFY["verifier<br/>never trusts COMPLETED"]
    DIAG["diagnoser<br/>rules → Claude"]
    PATCH["patch planner"]
    REPLAY["replay player<br/>MODE=replay"]
  end

  subgraph TF["TinyFish"]
    FETCH["Fetch API<br/>api.fetch.tinyfish.ai"]
    AGENT["Agent API<br/>/v1/automation/run-sse"]
    LIVE["Live browser<br/>streaming_url"]
  end

  CLAUDE["Claude API"]
  DB[("SQLite / Postgres")]

  FORM -- "POST /runs" --> ROUTES
  ROUTES -- "SSE: UI events" --> VIEW
  RES -- "GET /stats" --> ROUTES
  VIEW -. "iframe (read-only)" .-> LIVE

  ROUTES --> LADDER
  LADDER -- "rung 1" --> FETCH
  LADDER -- "rung 2: lite · rung 3: stealth + proxy" --> AGENT
  AGENT -- "SSE: STARTED · STREAMING_URL · PROGRESS · COMPLETE" --> LADDER
  LADDER --> VERIFY
  VERIFY -- "failed" --> DIAG
  DIAG -- "diagnosis" --> PATCH
  PATCH -- "next attempt config" --> LADDER
  DIAG -- "strict JSON diagnosis" --> CLAUDE
  LADDER -- "rung 1 extraction from Fetch text" --> CLAUDE
  REPLAY -- "recorded UI events" --> ROUTES

  ROUTES --> DB
  LADDER --> DB
```

## One attempt, end to end

1. The ladder controller builds the attempt's config: rung, goal (with any patch applied), output schema, browser profile and proxy.
2. It calls TinyFish: Fetch on rung 1, the Agent SSE stream on rungs 2 and 3. Every TinyFish event is stored verbatim and forwarded to the web app as a UI event.
3. The verifier checks the result against the user's expected-output check and the output schema, and looks for block signals: access-denied text, 403s, login forms, captcha markers, and a null result next to `COMPLETED`.
4. If the check fails, the diagnoser classifies the failure and returns the failing step, the evidence and a patch. The planner turns the patch into the next attempt's config, or stops the run when the failure is unrecoverable or the budget is spent.
