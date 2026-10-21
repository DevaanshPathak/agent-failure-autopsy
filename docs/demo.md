# Demo runbook

How to turn the code into a demo: record the demo sites, rehearse, and run the live demo with a replay fallback.

## 1. Before you record (needs real keys)

1. Put `TINYFISH_API_KEY` and `ANTHROPIC_API_KEY` in the repo-root `.env`. Check: `curl -s localhost:8000/health` should say `"tinyfish_key":true,"anthropic_key":true`.
2. Fill the remaining `TODO` entry in `fixtures/sites.yaml` (popup overlay), or accept that the popup story is shown from `/dev` only.
3. Every site in `fixtures/sites.yaml` is pre-screened over plain HTTP only. Run each one live twice from the web app (`make dev`, then http://localhost:3000) and check it shows its `expected_class`. Swap in the backup listed in `notes` if it doesn't.

## 2. Record every site (one live run at a time)

```sh
make api                               # terminal 1
make record SITE=ajax-films            # terminal 2, then the other ids
make baseline SITE=ajax-films          # optional: measured baseline (one stealth + proxy run)
```

- `make record` writes `fixtures/traces/<id>.jsonl` (every UI event, verbatim) and `fixtures/traces/<id>/attempt-<n>.jpg` (failing-step screenshots). Commit both.
- `make baseline` prints `baseline_steps: N`. Paste it into the site's entry in `fixtures/sites.yaml`. Without it, the baseline is estimated as 3 × the most steps any agent attempt took.
- Re-record a site whose recording doesn't show its class (at most twice), then use its backup.
- Rough cost: about 25 agent steps per recording and 15 per baseline, at about $0.016 per step.

## 3. Replay (offline, no keys)

- The run form shows "● recorded" for sites with a trace. **▶ Replay recorded run** streams the recording, labelled **REPLAY · recorded trace**.
- During a live run of a recorded site, **Switch to replay** (top bar) cancels the live TinyFish run (`POST /runs/{id}/cancel`) and starts the replay of the same site.
- `MODE=replay` in `.env` makes replay the default for every run. `REPLAY_SPEED=2` plays recordings twice as fast.
- `/dev` always works: it is the hand-written sample run and needs no keys and no database.

## 4. Results page

http://localhost:3000/results: diagnosed / fixed / honest stops / verified first try, and credits used vs the naive baseline ("always stealth + proxy, run 3 times"). Replays are excluded unless you toggle them in, so a replay never double-counts its recording. **Don't delete `apps/api/autopsy.db` before the demo**: it holds the live runs the page shows.

## 5. Day-of checklist

- [ ] `make lint test` is green on the commit you demo from, and `git status` is clean
- [ ] `curl -s localhost:8000/health` shows both keys and `"db":"ok"`
- [ ] TinyFish wallet balance ≥ $10; nobody else is using the key during the slot
- [ ] Every demo site has a recorded trace (`ls fixtures/traces/*.jsonl`)
- [ ] Browser tabs: `/` (hero site preselected), `/` (bot-block site), `/` (captcha or auth site), `/results`, `/dev` (last resort)
- [ ] A second laptop on the same commit with `MODE=replay`, plus a phone hotspot
- [ ] The terminal with `.env` is closed

## 6. If something goes wrong on stage

| Symptom | Do this |
|---|---|
| The live site hasn't failed the expected way within ~20 s, or is stuck | **Switch to replay** and say: "this is the recorded run of this site from earlier today" |
| A live run passes first time | Let it finish ("the verifier confirms it"), then replay the recorded failure |
| `POST /runs` answers 503 (no key) or 402 (wallet) | Use replay; the run form offers it |
| "Reconnecting…" stays up | Reload the page: the stream resumes from the last event |
| The API is down | Switch to the second laptop, or show `/dev` |
