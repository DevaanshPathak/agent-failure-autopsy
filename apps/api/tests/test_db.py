from datetime import UTC, datetime

from sqlalchemy import inspect

from app import db
from app.models import Run, RunMode, RunRequest, RunStatus, TraceEvent, TraceKind, TraceSource


def _run(run_id: str, created: datetime) -> Run:
    return Run(
        id=run_id,
        created_at=created,
        mode=RunMode.live,
        request=RunRequest(url="https://example.com", goal="Return the page heading"),
        status=RunStatus.queued,
        max_attempts=4,
        max_credits=40,
    )


async def test_init_creates_three_tables(temp_db):
    async with db.get_engine().connect() as conn:
        names = await conn.run_sync(lambda c: inspect(c).get_table_names())
    assert {"runs", "ui_events", "trace_events"} <= set(names)


async def test_run_round_trip_and_ordering(temp_db):
    older = _run("run-old", datetime(2026, 11, 1, 11, 0, tzinfo=UTC))
    newer = _run("run-new", datetime(2026, 11, 1, 12, 0, tzinfo=UTC))
    await db.insert_run(older)
    await db.insert_run(newer)

    older.status = RunStatus.verified
    older.credits_used = 9
    await db.save_run(older)

    loaded = await db.get_run("run-old")
    assert loaded == older
    assert await db.get_run("missing") is None
    assert [r.id for r in await db.list_runs()] == ["run-new", "run-old"]


async def test_ui_events_are_ordered_and_filtered(temp_db):
    for seq in (2, 1, 3):
        await db.append_ui_event(
            {"type": "budget", "seq": seq, "run_id": "r1", "ts": "2026-11-01T11:00:00Z"}
        )
    assert [e["seq"] for e in await db.list_ui_events("r1")] == [1, 2, 3]
    assert [e["seq"] for e in await db.list_ui_events("r1", after_seq=1)] == [2, 3]
    assert await db.max_ui_seq("r1") == 3
    assert await db.max_ui_seq("other") == 0


async def test_trace_event_is_stored(temp_db):
    ev = TraceEvent(
        run_id="r1",
        attempt_no=1,
        seq=1,
        kind=TraceKind.heartbeat,
        source=TraceSource.tinyfish_sse,
        ts=datetime(2026, 11, 1, 11, 0, tzinfo=UTC),
        label="heartbeat",
        raw={"type": "HEARTBEAT", "timestamp": "2026-11-01T11:00:00Z"},
    )
    await db.append_trace_event(ev)
    assert await db.ping()
