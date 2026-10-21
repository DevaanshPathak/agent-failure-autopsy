from datetime import UTC, datetime

import httpx

from app.config import Settings
from app.main import create_app
from app.models import TraceEvent, TraceKind, TraceSource
from app.routes.runs import failing_step_id
from tests.fakes import FakeTinyFish, run_record, sse_run

T0 = datetime(2026, 11, 1, 11, 0, tzinfo=UTC)


def _ev(seq: int, kind: TraceKind, *, step_no=None, tf_ts=None, raw=None) -> TraceEvent:
    return TraceEvent(
        run_id="r",
        attempt_no=1,
        seq=seq,
        kind=kind,
        source=TraceSource.tinyfish_sse,
        ts=T0,
        step_no=step_no,
        tf_timestamp=tf_ts,
        label=kind.value,
        raw=raw or {},
    )


def _steps(*stamps: str) -> list[dict]:
    return [{"id": f"s{i}", "timestamp": ts} for i, ts in enumerate(stamps, start=1)]


def _trace(steps: list[dict]) -> list[TraceEvent]:
    return [
        _ev(1, TraceKind.started),
        _ev(2, TraceKind.progress, step_no=1, tf_ts="2026-11-01T11:00:10Z"),
        _ev(3, TraceKind.progress, step_no=2, tf_ts="2026-11-01T11:00:20Z"),
        _ev(4, TraceKind.complete),
        _ev(5, TraceKind.run_snapshot, raw={"steps": steps}),
    ]


def test_same_count_maps_by_position():
    trace = _trace(_steps("2026-11-01T11:00:09Z", "2026-11-01T11:00:30Z"))
    assert failing_step_id(trace, 3) == "s2"


def test_different_count_maps_to_the_nearest_step_in_time():
    trace = _trace(_steps("2026-11-01T11:00:09Z", "2026-11-01T11:00:19Z", "2026-11-01T11:00:40Z"))
    assert failing_step_id(trace, 3) == "s2"


def test_non_step_event_shows_the_last_step_and_missing_record_is_none():
    assert failing_step_id(_trace(_steps("2026-11-01T11:00:09Z")), 4) == "s1"
    assert failing_step_id(_trace([]), 3) is None


async def test_endpoint_serves_the_failing_step_jpeg(temp_db, monkeypatch):
    async def instant(_s):
        return None

    monkeypatch.setattr("app.ladder.controller.asyncio.sleep", instant)
    fake = FakeTinyFish(
        streams=[sse_run("tf_1", ["Opening", "A cookie consent dialog is covering the page"])],
        runs={"tf_1": run_record("tf_1", 2)},
    )
    app = create_app(Settings(_env_file=None, max_attempts=1), tinyfish=fake, claude=None)
    body = {
        "url": "https://shop.example.com",
        "goal": "List products",
        "expected": {"type": "min_items", "path": "products", "min": 1},
        "start_rung": "agent",
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        run_id = (await c.post("/runs", json=body)).json()["run_id"]
        await c.get(f"/runs/{run_id}/stream")
        ok = await c.get(f"/runs/{run_id}/attempts/1/screenshot")
        missing = await c.get(f"/runs/{run_id}/attempts/9/screenshot")
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "image/jpeg"
    assert ok.content == b"\xff\xd8fake-jpeg"
    assert missing.status_code == 404
