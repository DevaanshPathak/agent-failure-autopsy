"""Run endpoints: create a run, read it, and stream its UI events over SSE."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sse_starlette import EventSourceResponse, ServerSentEvent

from app import db
from app.events import utcnow
from app.models import (
    VERDICT_STATUSES,
    Run,
    RunCreated,
    RunMode,
    RunRequest,
    RunStatus,
    SiteInfo,
)
from app.services import Services, get_services
from app.sites import SitesError, find_site, load_sites

router = APIRouter(tags=["runs"])
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
        raise HTTPException(status_code=501, detail="replay mode arrives in Phase 5")
    if svc.tinyfish is None:
        raise HTTPException(status_code=503, detail="TINYFISH_API_KEY is not set — use replay mode")
    if svc.live_semaphore.locked():
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
    svc.track(run.id, asyncio.create_task(_run_live(svc, run.id), name=f"run-{run.id}"))
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
            current = await db.get_run(run_id)
            if current is not None and current.status in VERDICT_STATUSES:
                return
            while True:
                payload = await queue.get()
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
