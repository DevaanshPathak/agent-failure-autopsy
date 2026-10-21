from datetime import UTC, datetime

from app import db
from app.events import Emitter, RunEventBus
from app.models import TraceEvent, TraceKind, TraceSource

T0 = datetime(2026, 11, 1, 11, 0, tzinfo=UTC)


def _trace(seq: int, kind: TraceKind, label: str, raw: dict) -> TraceEvent:
    return TraceEvent(
        run_id="r1",
        attempt_no=1,
        seq=seq,
        kind=kind,
        source=TraceSource.tinyfish_sse,
        ts=T0,
        label=label,
        raw=raw,
    )


async def test_publish_assigns_seq_persists_and_delivers(temp_db):
    bus = RunEventBus()
    em = Emitter("r1", bus)
    queue = bus.subscribe("r1")
    await em.budget(0, 4, 0, 40)
    await em.trace(_trace(1, TraceKind.heartbeat, "heartbeat", {"type": "HEARTBEAT"}))
    await em.trace(
        _trace(2, TraceKind.progress, "Clicking", {"type": "PROGRESS", "purpose": "x" * 3000})
    )
    await em.live_view(1, "https://live.example/1")

    stored = await db.list_ui_events("r1")
    assert [(e["seq"], e["type"]) for e in stored] == [
        (1, "budget"),
        (2, "trace_event"),
        (3, "live_view"),
    ]
    delivered = [queue.get_nowait() for _ in range(queue.qsize())]
    assert delivered == stored
    assert stored[1]["event"]["raw"]["purpose"].endswith("…[truncated 1000 chars]")
    assert next(iter(stored[0])) == "type"


async def test_seq_continues_from_the_database_after_restart(temp_db):
    await Emitter("r2", RunEventBus()).budget(0, 4, 0, 40)
    await Emitter("r2", RunEventBus()).budget(1, 4, 5, 40)
    assert [e["seq"] for e in await db.list_ui_events("r2")] == [1, 2]


async def test_unsubscribed_queue_gets_nothing(temp_db):
    bus = RunEventBus()
    queue = bus.subscribe("r3")
    bus.unsubscribe("r3", queue)
    await Emitter("r3", bus).budget(0, 4, 0, 40)
    assert queue.empty()
