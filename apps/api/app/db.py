"""Persistence: SQLite by default, Postgres via DATABASE_URL (SQLAlchemy async Core).

No migrations: tables are created on startup. Delete the SQLite file when the schema changes.
"""

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
    func,
    select,
    text,
)
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


def configure(database_url: str | None = None) -> AsyncEngine:
    """(Re)create the engine. Tests call this with a temporary database URL."""
    global _engine
    url = database_url or get_settings().database_url
    connect_args = {"timeout": 15} if url.startswith("sqlite") else {}
    _engine = create_async_engine(url, connect_args=connect_args)
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
    async with get_engine().begin() as conn:
        await conn.execute(runs.update().where(runs.c.id == run.id).values(**_run_row(run)))


async def get_run(run_id: str) -> Run | None:
    async with get_engine().connect() as conn:
        row = (await conn.execute(select(runs.c.run_json).where(runs.c.id == run_id))).first()
    return Run.model_validate(row.run_json) if row else None


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
