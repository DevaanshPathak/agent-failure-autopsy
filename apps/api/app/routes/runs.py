"""Run endpoints: create a run, read it, and stream its UI events over SSE."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sse_starlette import EventSourceResponse, ServerSentEvent

from app import db
from app.events import Emitter, utcnow
from app.models import (
    VERDICT_STATUSES,
    Run,
    RunCreated,
    RunMode,
    RunRequest,
    RunStatus,
    SiteInfo,
    Stats,
    TraceEvent,
    TraceKind,
)
from app.replay.player import replay_run, trace_path
from app.services import Services, get_services
from app.sites import SitesError, find_site, load_sites
from app.stats import MAX_ROWS, compute_stats
from app.tinyfish.client import TinyFishError

router = APIRouter(tags=["runs"])
# How long a stream of an already-finished run waits for a verdict that is still in flight.
FINISHED_RUN_GRACE_S = 3.0
ServicesDep = Annotated[Services, Depends(get_services)]


@router.get("/sites", response_model=list[SiteInfo])
async def list_sites(svc: ServicesDep) -> list[SiteInfo]:
    try:
        return load_sites(svc.settings.fixtures_dir)
    except SitesError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


async def _run_live(svc: Services, run_id: str) -> None:
    async with svc.live_semaphore:
        await svc.controller.execute(run_id)


@router.post("/runs", status_code=201, response_model=RunCreated)
async def create_run(req: RunRequest, svc: ServicesDep) -> RunCreated:
    settings = svc.settings
    mode = req.mode or RunMode(settings.mode)
    if req.site_id:
        site = find_site(settings.fixtures_dir, req.site_id)
        if site is not None:
            req = req.model_copy(
                update={
                    "expected": req.expected or site.expected,
                    "output_schema": req.output_schema or site.output_schema,
                }
            )
    if mode is RunMode.replay:
        if trace_path(settings.fixtures_dir, req.site_id) is None:
            raise HTTPException(
                status_code=409,
                detail=f"replay_unavailable: no recorded trace for site '{req.site_id}'",
            )
    elif svc.tinyfish is None:
        raise HTTPException(status_code=503, detail="TINYFISH_API_KEY is not set — use replay mode")
    elif svc.live_semaphore.locked():
        raise HTTPException(status_code=429, detail="another live run is in progress")

    run = Run(
        id=uuid4().hex[:12],
        created_at=utcnow(),
        mode=mode,
        request=req,
        status=RunStatus.queued,
        max_attempts=req.max_attempts or settings.max_attempts,
        max_credits=req.max_credits if req.max_credits is not None else settings.max_credits,
    )
    await db.insert_run(run)
    if mode is RunMode.replay:
        work = replay_run(run, svc.bus, settings.fixtures_dir, settings.replay_speed)
    else:
        work = _run_live(svc, run.id)
    svc.track(run.id, asyncio.create_task(work, name=f"run-{run.id}"))
    return RunCreated(run_id=run.id, mode=mode, stream_url=f"/runs/{run.id}/stream")


@router.get("/runs/{run_id}", response_model=Run)
async def get_run(run_id: str) -> Run:
    run = await db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


def _sse(payload: dict[str, Any]) -> ServerSentEvent:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return ServerSentEvent(data=data, id=str(payload["seq"]))


def _parse_seq(value: str | None) -> int:
    try:
        return max(0, int(value or 0))
    except ValueError:
        return 0


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str,
    svc: ServicesDep,
    after: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header()] = None,
) -> EventSourceResponse:
    """Backfill stored events after `after` / `Last-Event-ID`, then follow live until the verdict.

    The queue is subscribed before the backfill read, so nothing published in between is lost;
    anything at or below the last sent seq is skipped.
    """
    if await db.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    start = after if after is not None else _parse_seq(last_event_id)
    queue = svc.bus.subscribe(run_id)

    async def events() -> AsyncIterator[ServerSentEvent]:
        try:
            last = start
            for payload in await db.list_ui_events(run_id, start):
                last = payload["seq"]
                yield _sse(payload)
                if payload["type"] == "verdict":
                    return
            # A finished run's final status is saved just before its verdict is published, so a
            # final status doesn't mean everything is stored yet: wait (briefly) for the verdict.
            current = await db.get_run(run_id)
            finished = current is not None and current.status in VERDICT_STATUSES
            while True:
                try:
                    timeout = FINISHED_RUN_GRACE_S if finished else None
                    payload = await asyncio.wait_for(queue.get(), timeout)
                except TimeoutError:
                    # No verdict will come (e.g. the API restarted mid-run): send what is stored.
                    for payload in await db.list_ui_events(run_id, last):
                        yield _sse(payload)
                    return
                if payload["seq"] <= last:
                    continue
                last = payload["seq"]
                yield _sse(payload)
                if payload["type"] == "verdict":
                    return
        finally:
            svc.bus.unsubscribe(run_id, queue)

    return EventSourceResponse(
        events(),
        ping=15,
        sep="\n",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Failing-step screenshot ---------------------------------------------------------------------

SAFE_SITE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
SCREENSHOT_HEADERS = {"Cache-Control": "max-age=3600"}


def _parse_ts(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def failing_step_id(trace: list[TraceEvent], failing_seq: int) -> str | None:
    """Map the red trace event onto a step id from the run record (`steps[]`).

    PROGRESS events and steps[] are not documented to be 1:1, so: same count -> by position;
    otherwise the step nearest in time. Non-step events (e.g. COMPLETE) show the last step.
    """
    failing = next((ev for ev in trace if ev.seq == failing_seq), None)
    snapshot = next((ev for ev in reversed(trace) if ev.kind is TraceKind.run_snapshot), None)
    steps = [
        s
        for s in ((snapshot.raw.get("steps") or []) if snapshot else [])
        if isinstance(s, dict) and s.get("id")
    ]
    if failing is None or not steps:
        return None
    if failing.kind is not TraceKind.progress or not failing.step_no:
        return str(steps[-1]["id"])
    progress = [ev for ev in trace if ev.kind is TraceKind.progress]
    if len(steps) == len(progress) and failing.step_no <= len(steps):
        return str(steps[failing.step_no - 1]["id"])
    target = _parse_ts(failing.tf_timestamp) or failing.ts
    timed = [(s, _parse_ts(s.get("timestamp"))) for s in steps]
    timed = [(s, t) for s, t in timed if t is not None]
    if not timed:
        return str(steps[min(failing.step_no, len(steps)) - 1]["id"])
    best = min(timed, key=lambda pair: abs((pair[1] - target).total_seconds()))
    return str(best[0]["id"])


@router.get("/runs/{run_id}/attempts/{attempt_no}/screenshot")
async def failing_step_screenshot(run_id: str, attempt_no: int, svc: ServicesDep) -> Response:
    run = await db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    attempt = next((a for a in run.attempts if a.attempt_no == attempt_no), None)
    seq = attempt.diagnosis.failing_step_seq if attempt and attempt.diagnosis else None
    if attempt is None or seq is None:
        raise HTTPException(status_code=404, detail="no failing step for this attempt")

    if run.mode is RunMode.replay:
        site_id = run.request.site_id or ""
        path = svc.settings.fixtures_dir / "traces" / site_id / f"attempt-{attempt_no}.jpg"
        if not SAFE_SITE_ID.match(site_id) or not path.is_file():
            raise HTTPException(status_code=404, detail="no recorded screenshot")
        return FileResponse(path, media_type="image/jpeg", headers=SCREENSHOT_HEADERS)

    if svc.tinyfish is None or not attempt.tf_run_id:
        raise HTTPException(status_code=404, detail="no TinyFish run for this attempt")
    step_id = failing_step_id(await db.list_trace_events(run_id, attempt_no), seq)
    if step_id is None:
        raise HTTPException(status_code=404, detail="no matching step in the run record")
    try:
        content = await svc.tinyfish.step_screenshot(attempt.tf_run_id, step_id)
    except (TinyFishError, httpx.HTTPError) as e:
        raise HTTPException(status_code=404, detail="screenshot unavailable") from e
    return Response(content=content, media_type="image/jpeg", headers=SCREENSHOT_HEADERS)


@router.post("/runs/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: str, svc: ServicesDep) -> dict[str, str]:
    """Stop a queued or running run (used by "Switch to replay"). Idempotent while running."""
    run = await db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status in VERDICT_STATUSES:
        raise HTTPException(status_code=409, detail="run already finished")
    task = svc.run_tasks.get(run_id)
    if task is not None:
        task.cancel()
    else:  # no task (e.g. the API restarted mid-run): close the run record honestly
        run.status = RunStatus.cancelled
        run.verdict_reason = "Cancelled by user."
        run.finished_at = utcnow()
        await db.save_run(run)
        await Emitter(run_id, svc.bus).verdict(
            RunStatus.cancelled,
            "Cancelled by user.",
            final_result=None,
            attempts_used=len(run.attempts),
            credits_used=run.credits_used,
            baseline_credits_estimate=run.baseline_credits_estimate,
        )
    return {"run_id": run_id, "status": "cancelling"}


@router.get("/stats", response_model=Stats)
async def stats(include_replay: bool = False) -> Stats:
    return compute_stats(await db.list_runs(MAX_ROWS), include_replay)
