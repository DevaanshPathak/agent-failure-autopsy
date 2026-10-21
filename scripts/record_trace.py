"""Record a demo site's live run for replay, or measure its naive baseline.

Talks to the running API over HTTP only (start it first with `make api`; it needs real keys).

    make record SITE=<id>      # live run -> fixtures/traces/<id>.jsonl (+ failing-step JPEGs)
    make baseline SITE=<id>    # one stealth + proxy run -> prints `baseline_steps: N`

Equivalent: cd apps/api && uv run python ../../scripts/record_trace.py --site <id> [--baseline]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "fixtures"
STREAM_TIMEOUT = httpx.Timeout(10.0, read=None)


def load_site(site_id: str) -> dict[str, Any]:
    data = yaml.safe_load((FIXTURES / "sites.yaml").read_text(encoding="utf-8")) or {}
    for site in data.get("sites") or []:
        if site.get("id") == site_id:
            if str(site_id).startswith("TODO"):
                sys.exit(f"site {site_id!r} is still a template entry; fill it in first")
            return site
    sys.exit(f"unknown site {site_id!r}; ids are listed in fixtures/sites.yaml")


def run_body(site: dict[str, Any], baseline: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "url": site["url"],
        "goal": site["goal"],
        "expected": site.get("expected"),
        "output_schema": site.get("output_schema"),
        "site_id": site["id"],
        "mode": "live",
        "start_rung": site.get("start_rung") or "fetch",
        "max_attempts": None,
        "max_credits": None,
    }
    if baseline:
        body.update(start_rung="agent_stealth", max_attempts=1)
    return body


def describe(event: dict[str, Any]) -> str:
    kind = event["type"]
    if kind == "trace_event":
        return f"  [{event['attempt_no']}] {event['event']['kind']}: {event['event']['label']}"
    if kind == "attempt_started":
        return f"attempt {event['attempt_no']} on {event['rung']}"
    if kind == "verify":
        return f"  {event['result']['summary']}"
    if kind == "diagnosis":
        d = event["diagnosis"]
        return f"  diagnosis: {d['failure_class']} ({d['source']}, {d['confidence']:.2f})"
    if kind == "verdict":
        return f"VERDICT {event['status']}: {event['reason']} ({event['credits_used']} credits)"
    return f"  {kind}"


def follow(client: httpx.Client, api: str, run_id: str) -> list[str]:
    """Return every UI event payload, verbatim, until the verdict."""
    lines: list[str] = []
    with client.stream("GET", f"{api}/runs/{run_id}/stream", timeout=STREAM_TIMEOUT) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            lines.append(payload)
            event = json.loads(payload)
            print(describe(event))
            if event["type"] == "verdict":
                break
    return lines


def save_screenshots(client: httpx.Client, api: str, run: dict[str, Any], site_id: str) -> int:
    saved = 0
    folder = FIXTURES / "traces" / site_id
    for attempt in run.get("attempts") or []:
        if not attempt.get("diagnosis"):
            continue
        n = attempt["attempt_no"]
        resp = client.get(f"{api}/runs/{run['id']}/attempts/{n}/screenshot")
        if resp.status_code == 200 and resp.content:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"attempt-{n}.jpg").write_bytes(resp.content)
            saved += 1
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--site", required=True, help="site id from fixtures/sites.yaml")
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--baseline", action="store_true", help="measure one stealth+proxy run")
    args = parser.parse_args()

    site = load_site(args.site)
    api = args.api.rstrip("/")
    with httpx.Client(timeout=30.0) as client:
        created = client.post(f"{api}/runs", json=run_body(site, args.baseline))
        if created.status_code != 201:
            print(f"POST /runs failed ({created.status_code}): {created.text}", file=sys.stderr)
            return 1
        run_id = created.json()["run_id"]
        print(f"run {run_id} ({'baseline' if args.baseline else 'record'}) for {args.site}")
        lines = follow(client, api, run_id)
        run = client.get(f"{api}/runs/{run_id}").json()

        if args.baseline:
            steps = (run.get("attempts") or [{}])[0].get("num_of_steps")
            print(
                f"\nbaseline_steps: {steps}    # paste into fixtures/sites.yaml under {args.site}"
            )
            return 0

        out = FIXTURES / "traces" / f"{args.site}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
        shots = save_screenshots(client, api, run, args.site)
        classes = [a["diagnosis"]["failure_class"] for a in run["attempts"] if a.get("diagnosis")]
        print(f"\nwrote {out.relative_to(REPO)} ({len(lines)} events, {shots} screenshots)")
        print(
            f"classes: {' -> '.join(classes) or 'none'}; verdict: {run['status']}; "
            f"credits: {run['credits_used']} (expected class: {site.get('expected_class')})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
