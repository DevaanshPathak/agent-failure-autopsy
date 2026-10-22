"""Persistence: SQLite by default, Postgres via DATABASE_URL (SQLAlchemy async Core).

No migrations: tables are created on startup. Delete the SQLite file when the schema changes.
Provider URLs (`postgres://…?sslmode=require`, as Neon gives them) are normalized for asyncpg.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    case,
    func,
    select,
    text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings
from app.models import Run, TraceEvent

metadata = MetaData()

runs = Table(
    "runs",
    metadata,
    Column("id", String, primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("finished_at", DateTime(timezone=True)),
    Column("status", String, nullable=False),
    Column("mode", String, nullable=False),
    Column("site_id", String),
    Column("url", String, nullable=False),
    Column("credits_used", Integer, nullable=False, default=0),
    Column("run_json", JSON, nullable=False),
)

ui_events = Table(
    "ui_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String, nullable=False, index=True),
    Column("seq", Integer, nullable=False),
    Column("type", String, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("run_id", "seq", name="uq_ui_events_run_seq"),
)

trace_events = Table(
    "trace_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String, nullable=False, index=True),
    Column("attempt_no", Integer, nullable=False),
    Column("seq", Integer, nullable=False),
    Column("kind", String, nullable=False),
    Column("source", String, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
)

llm_usage = Table(
    "llm_usage",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("model", String, nullable=False),
    Column("purpose", String, nullable=False),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("cost_usd", Float, nullable=False),
)

_engine: AsyncEngine | None = None


def engine_args(url: str) -> tuple[str, dict[str, Any]]:
    """SQLAlchemy URL and engine options for a database URL as a provider hands it out."""
    if url.startswith("sqlite"):
        return url, {"connect_args": {"timeout": 15}}
    parsed = make_url(url)
    if parsed.drivername in ("postgres", "postgresql"):
        parsed = parsed.set(drivername="postgresql+asyncpg")
    query = dict(parsed.query)
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)  # libpq-only; asyncpg rejects unknown parameters
    parsed = parsed.set(query=query)
    connect_args = {"ssl": "require"} if sslmode and sslmode != "disable" else {}
    # Serverless instances sleep between requests: check pooled connections before use.
    options = {"connect_args": connect_args, "pool_pre_ping": True, "pool_recycle": 240}
    return parsed.render_as_string(hide_password=False), options


def configure(database_url: str | None = None) -> AsyncEngine:
    """(Re)create the engine. Tests call this with a temporary database URL."""
    global _engine
    settings = get_settings()
    url, options = engine_args(
        database_url or settings.database_url_unpooled or settings.database_url
    )
    _engine = create_async_engine(url, **options)
    return _engine


def get_engine() -> AsyncEngine:
    return _engine or configure()


async def init_db() -> None:
    async with get_engine().begin() as conn:
        await conn.run_sync(metadata.create_all)


async def dispose() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def ping() -> bool:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _run_row(run: Run) -> dict[str, Any]:
    return {
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "status": run.status.value,
        "mode": run.mode.value,
        "site_id": run.request.site_id,
        "url": run.request.url,
        "credits_used": run.credits_used,
        "run_json": run.model_dump(mode="json"),
    }


async def insert_run(run: Run) -> None:
    async with get_engine().begin() as conn:
        await conn.execute(runs.insert().values(id=run.id, **_run_row(run)))


async def save_run(run: Run) -> None:
    row: dict[str, Any] = _run_row(run)
    if run.status.value in ("queued", "running"):
        # Progress saves must not erase a pending cancel request (`cancelling`, request_cancel).
        row["status"] = case((runs.c.status == "cancelling", "cancelling"), else_=row["status"])
    async with get_engine().begin() as conn:
        await conn.execute(runs.update().where(runs.c.id == run.id).values(**row))


async def get_run(run_id: str) -> Run | None:
    async with get_engine().connect() as conn:
        row = (await conn.execute(select(runs.c.run_json).where(runs.c.id == run_id))).first()
    return Run.model_validate(row.run_json) if row else None


async def claim_run(run_id: str, from_statuses: Iterable[str] = ("queued",)) -> bool:
    """Atomically move a run's status column to `running`. False when someone else got it."""
    query = (
        runs.update()
        .where(runs.c.id == run_id, runs.c.status.in_(list(from_statuses)))
        .values(status="running")
    )
    async with get_engine().begin() as conn:
        return (await conn.execute(query)).rowcount == 1


async def request_cancel(run_id: str) -> bool:
    """Flag a running run for cancellation by whichever process is executing it."""
    query = (
        runs.update()
        .where(runs.c.id == run_id, runs.c.status.in_(["queued", "running"]))
        .values(status="cancelling")
    )
    async with get_engine().begin() as conn:
        return (await conn.execute(query)).rowcount == 1


async def get_status(run_id: str) -> str | None:
    """The status column only (cheap; `cancelling` is visible here, never in run_json)."""
    async with get_engine().connect() as conn:
        return (await conn.execute(select(runs.c.status).where(runs.c.id == run_id))).scalar()


async def live_usage(active_since: datetime, hour_since: datetime) -> tuple[int, int, int]:
    """(live runs still queued/running, live runs started in the last hour, credits ever used)."""
    live = runs.c.mode == "live"
    active = select(func.count(runs.c.id)).where(
        live,
        runs.c.status.in_(["queued", "running", "cancelling"]),
        runs.c.created_at >= active_since,
    )
    recent = select(func.count(runs.c.id)).where(live, runs.c.created_at >= hour_since)
    credits = select(func.coalesce(func.sum(runs.c.credits_used), 0)).where(live)
    async with get_engine().connect() as conn:
        n_active = (await conn.execute(active)).scalar() or 0
        n_recent = (await conn.execute(recent)).scalar() or 0
        used = (await conn.execute(credits)).scalar() or 0
    return int(n_active), int(n_recent), int(used)


async def list_runs(limit: int = 200) -> list[Run]:
    query = select(runs.c.run_json).order_by(runs.c.created_at.desc()).limit(limit)
    async with get_engine().connect() as conn:
        rows = (await conn.execute(query)).all()
    return [Run.model_validate(r.run_json) for r in rows]


async def append_ui_event(payload: dict[str, Any]) -> None:
    async with get_engine().begin() as conn:
        await conn.execute(
            ui_events.insert().values(
                run_id=payload["run_id"],
                seq=payload["seq"],
                type=payload["type"],
                ts=datetime.fromisoformat(payload["ts"]),
                payload=payload,
            )
        )


async def list_ui_events(run_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
    query = (
        select(ui_events.c.payload)
        .where(ui_events.c.run_id == run_id, ui_events.c.seq > after_seq)
        .order_by(ui_events.c.seq)
    )
    async with get_engine().connect() as conn:
        rows = (await conn.execute(query)).all()
    return [r.payload for r in rows]


async def max_ui_seq(run_id: str) -> int:
    query = select(func.max(ui_events.c.seq)).where(ui_events.c.run_id == run_id)
    async with get_engine().connect() as conn:
        value = (await conn.execute(query)).scalar()
    return value or 0


async def append_trace_event(ev: TraceEvent) -> None:
    async with get_engine().begin() as conn:
        await conn.execute(
            trace_events.insert().values(
                run_id=ev.run_id,
                attempt_no=ev.attempt_no,
                seq=ev.seq,
                kind=ev.kind.value,
                source=ev.source.value,
                ts=ev.ts,
                payload=ev.model_dump(mode="json"),
            )
        )


async def list_trace_events(run_id: str, attempt_no: int | None = None) -> list[TraceEvent]:
    """Full (untruncated) trace events, ordered by attempt then seq."""
    query = select(trace_events.c.payload).where(trace_events.c.run_id == run_id)
    if attempt_no is not None:
        query = query.where(trace_events.c.attempt_no == attempt_no)
    query = query.order_by(trace_events.c.attempt_no, trace_events.c.seq)
    async with get_engine().connect() as conn:
        rows = (await conn.execute(query)).all()
    return [TraceEvent.model_validate(r.payload) for r in rows]


async def append_llm_usage(
    *, model: str, purpose: str, input_tokens: int, output_tokens: int, cost_usd: float
) -> None:
    async with get_engine().begin() as conn:
        await conn.execute(
            llm_usage.insert().values(
                ts=datetime.now(UTC),
                model=model,
                purpose=purpose,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            )
        )


async def llm_spend_total() -> tuple[float, int]:
    """(total USD, number of calls) across every Claude call ever recorded."""
    query = select(func.coalesce(func.sum(llm_usage.c.cost_usd), 0.0), func.count(llm_usage.c.id))
    async with get_engine().connect() as conn:
        total, calls = (await conn.execute(query)).one()
    return float(total or 0.0), int(calls or 0)
