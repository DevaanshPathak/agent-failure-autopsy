"""The public deployment: runs executed by their stream, shared spend caps, interrupted runs."""

import asyncio
import json
from datetime import timedelta

import httpx
import pytest

from app import db
from app.config import Settings
from app.events import utcnow
from app.main import create_app
from app.models import Run, RunMode, RunRequest, RunStatus
from app.routes.runs import INTERRUPTED
from tests.fakes import FakeTinyFish, run_record, sse_run

PRODUCTS = {
    "products": [{"name": "Blue Mug", "price": "$12.00"}, {"name": "Kettle", "price": "$9"}]
}
BODY = {
    "url": "https://shop.example.com/products",
    "goal": "List the first 2 products",
    "expected": {"type": "min_items", "path": "products", "min": 2},
    "start_rung": "agent",
}


def _app(fake, **settings):
    return create_app(Settings(_env_file=None, **settings), tinyfish=fake, claude=None)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _events(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def _verified_fake(tf_id: str = "tf_1") -> FakeTinyFish:
    return FakeTinyFish(
        streams=[sse_run(tf_id, ["Navigating", "Reading products"], result=PRODUCTS)],
        runs={tf_id: run_record(tf_id, 2)},
    )


async def _past_live_run(run_id: str, *, status: RunStatus, credits: int, age_s: float) -> None:
    run = Run(
        id=run_id,
        created_at=utcnow() - timedelta(seconds=age_s),
        mode=RunMode.live,
        request=RunRequest(url=BODY["url"], goal=BODY["goal"]),
        status=status,
        max_attempts=4,
        max_credits=40,
        credits_used=credits,
    )
    await db.insert_run(run)


async def test_run_in_stream_executes_the_run_inside_its_stream(temp_db):
    fake = _verified_fake()
    async with _client(_app(fake, run_in_stream=True)) as c:
        run_id = (await c.post("/runs", json=BODY)).json()["run_id"]
        await asyncio.sleep(0.05)
        queued = (await c.get(f"/runs/{run_id}")).json()
        assert queued["status"] == "queued" and fake.bodies == []  # nothing runs in background
        events = _events((await c.get(f"/runs/{run_id}/stream")).text)
        run = (await c.get(f"/runs/{run_id}")).json()
    assert events[-1]["type"] == "verdict" and events[-1]["status"] == "verified"
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert run["status"] == "verified" and len(fake.bodies) == 1


async def test_a_run_is_claimed_by_one_stream_only(temp_db):
    await _past_live_run("q1", status=RunStatus.queued, credits=0, age_s=1)
    assert await db.claim_run("q1") is True
    assert await db.claim_run("q1") is False


async def test_live_runs_are_limited_one_at_a_time(temp_db):
    async with _client(_app(_verified_fake(), run_in_stream=True)) as c:
        first = await c.post("/runs", json=BODY)
        second = await c.post("/runs", json=BODY)
        replay_ok = await c.post("/runs", json={**BODY, "mode": "replay", "site_id": "nope"})
    assert first.status_code == 201
    assert second.status_code == 429 and "Another live run" in second.json()["detail"]
    assert replay_ok.status_code == 409  # replay is never counted against live limits


async def test_live_runs_per_hour_cap(temp_db):
    await _past_live_run("h1", status=RunStatus.verified, credits=2, age_s=600)
    await _past_live_run("h2", status=RunStatus.verified, credits=2, age_s=7200)  # over an hour
    app = _app(
        _verified_fake(), run_in_stream=True, max_concurrent_live_runs=5, live_runs_per_hour=2
    )
    async with _client(app) as c:
        ok = await c.post("/runs", json=BODY)
        refused = await c.post("/runs", json=BODY)
    assert ok.status_code == 201
    assert refused.status_code == 429 and "2 live runs per hour" in refused.json()["detail"]


async def test_credit_cap_clamps_each_run_then_refuses(temp_db):
    await _past_live_run("c1", status=RunStatus.verified, credits=44, age_s=600)
    app = _app(_verified_fake(), run_in_stream=True, live_credit_cap=50)
    async with _client(app) as c:
        created = await c.post("/runs", json={**BODY, "max_credits": 400, "max_attempts": 8})
        run = (await c.get(f"/runs/{created.json()['run_id']}")).json()
    assert (run["max_credits"], run["max_attempts"]) == (6, 4)  # 50 - 44 left; defaults cap

    await db.save_run(Run.model_validate({**run, "status": "verified", "credits_used": 4}))
    async with _client(app) as c:
        refused = await c.post("/runs", json=BODY)
        health = (await c.get("/health")).json()
    assert refused.status_code == 503 and "budget (50 credits) is used up" in refused.text
    assert (health["live_credits_used"], health["live_credit_cap"]) == (48, 50)
    assert health["live_run_active"] is False and health["claude_ready"] is False


async def test_interrupted_run_gets_an_honest_verdict(temp_db):
    await _past_live_run("old1", status=RunStatus.running, credits=3, age_s=3600)
    async with _client(_app(FakeTinyFish())) as c:
        run = (await c.get("/runs/old1")).json()
        events = _events((await c.get("/runs/old1/stream")).text)
    assert run["status"] == "error" and run["verdict_reason"] == INTERRUPTED
    assert events[-1]["type"] == "verdict" and events[-1]["credits_used"] == 3


async def test_cancel_request_from_another_process_stops_the_run(temp_db, monkeypatch):
    monkeypatch.setattr("app.routes.runs.FOLLOW_POLL_S", 0.02)
    hang = asyncio.Event()
    stuck = sse_run("tf_c", ["one", "two"], result=PRODUCTS)
    stuck.insert(5, hang)
    fake = FakeTinyFish(streams=[stuck])
    async with _client(_app(fake, run_in_stream=True)) as c:
        run_id = (await c.post("/runs", json=BODY)).json()["run_id"]
        stream = asyncio.create_task(c.get(f"/runs/{run_id}/stream"))
        for _ in range(500):
            if sum(e.kind == "progress" for e in await db.list_trace_events(run_id)) == 2:
                break
            await asyncio.sleep(0.01)
        assert await db.request_cancel(run_id)  # what another instance's cancel endpoint does
        events = _events((await asyncio.wait_for(stream, 5)).text)
    assert events[-1]["type"] == "verdict" and events[-1]["status"] == "cancelled"
    assert fake.cancelled == ["tf_c"]


async def test_progress_saves_keep_a_pending_cancel(temp_db):
    await _past_live_run("k1", status=RunStatus.running, credits=0, age_s=1)
    assert await db.request_cancel("k1")
    run = await db.get_run("k1")
    assert run is not None
    await db.save_run(run)  # still "running" in run_json
    assert await db.get_status("k1") == "cancelling"
    run.status = RunStatus.cancelled
    await db.save_run(run)
    assert await db.get_status("k1") == "cancelled"


async def test_run_deadline_ends_with_a_time_verdict(temp_db):
    fake = _verified_fake()
    async with _client(_app(fake, run_deadline_s=10)) as c:
        run_id = (await c.post("/runs", json=BODY)).json()["run_id"]
        events = _events((await c.get(f"/runs/{run_id}/stream")).text)
    assert events[-1]["status"] == "budget_exhausted"
    assert events[-1]["reason"].startswith("Time budget spent")
    assert fake.bodies == []


@pytest.mark.parametrize(
    ("url", "expected", "ssl"),
    [
        (
            "postgres://u:p@ep-x.neon.tech/db?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p@ep-x.neon.tech/db",
            True,
        ),
        ("postgresql://u:p@localhost:5432/db", "postgresql+asyncpg://u:p@localhost:5432/db", False),
        ("sqlite+aiosqlite:///./autopsy.db", "sqlite+aiosqlite:///./autopsy.db", False),
    ],
)
def test_engine_args_accept_provider_urls(url, expected, ssl):
    rendered, options = db.engine_args(url)
    assert rendered == expected
    assert (options["connect_args"].get("ssl") == "require") is ssl
