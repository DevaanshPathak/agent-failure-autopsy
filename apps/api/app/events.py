"""In-memory event bus: assigns each run's UI-event seq, persists, then fans out to SSE subscribers.

One process only (ADR-012). Every event is stored before delivery, so a reconnecting client can
backfill from the database with `Last-Event-ID`.
"""

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from app import db
from app.models import (
    AttemptConfig,
    AttemptStartedEvent,
    BudgetEvent,
    Diagnosis,
    DiagnosisEvent,
    LiveViewEvent,
    Rung,
    RungChangeEvent,
    RunStatus,
    TraceEvent,
    TraceKind,
    TraceUiEvent,
    VerdictEvent,
    VerifyEvent,
    VerifyResult,
)
from app.tinyfish.client import ui_copy

UiEventModel = (
    AttemptStartedEvent
    | TraceUiEvent
    | LiveViewEvent
    | VerifyEvent
    | DiagnosisEvent
    | RungChangeEvent
    | BudgetEvent
    | VerdictEvent
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class RunEventBus:
    def __init__(self) -> None:
        self._seq: dict[str, int] = {}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._subscribers: defaultdict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    async def publish(self, event: UiEventModel) -> dict[str, Any]:
        """Assign the next seq, persist, deliver. Returns the delivered payload."""
        run_id = event.run_id
        async with self._locks[run_id]:
            if run_id not in self._seq:
                self._seq[run_id] = await db.max_ui_seq(run_id)
            self._seq[run_id] += 1
            payload = event.model_copy(update={"seq": self._seq[run_id]}).model_dump(mode="json")
            await db.append_ui_event(payload)
            for queue in list(self._subscribers.get(run_id, ())):
                queue.put_nowait(payload)
        return payload

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers[run_id].add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        subscribers = self._subscribers.get(run_id)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                del self._subscribers[run_id]


class Emitter:
    """Emits one run's UI events. Constructs each event with seq=0; the bus assigns the real one."""

    def __init__(self, run_id: str, bus: RunEventBus) -> None:
        self.run_id = run_id
        self.bus = bus

    def _base(self) -> dict[str, Any]:
        return {"seq": 0, "run_id": self.run_id, "ts": utcnow()}

    async def budget(
        self, attempts_used: int, max_attempts: int, credits_used: int, max_credits: int
    ) -> None:
        await self.bus.publish(
            BudgetEvent(
                **self._base(),
                attempts_used=attempts_used,
                max_attempts=max_attempts,
                credits_used=credits_used,
                max_credits=max_credits,
            )
        )

    async def rung_change(
        self, from_rung: Rung | None, to_rung: Rung, skipped: list[Rung], reason: str
    ) -> None:
        await self.bus.publish(
            RungChangeEvent(
                **self._base(), from_rung=from_rung, to_rung=to_rung, skipped=skipped, reason=reason
            )
        )

    async def attempt_started(self, cfg: AttemptConfig) -> None:
        await self.bus.publish(
            AttemptStartedEvent(
                **self._base(), attempt_no=cfg.attempt_no, rung=cfg.rung, config=cfg
            )
        )

    async def trace(self, ev: TraceEvent) -> None:
        """Persist the full trace event; stream a truncated copy (never heartbeats)."""
        await db.append_trace_event(ev)
        if ev.kind is not TraceKind.heartbeat:
            await self.bus.publish(
                TraceUiEvent(**self._base(), attempt_no=ev.attempt_no, event=ui_copy(ev))
            )

    async def live_view(self, attempt_no: int, streaming_url: str) -> None:
        await self.bus.publish(
            LiveViewEvent(**self._base(), attempt_no=attempt_no, streaming_url=streaming_url)
        )

    async def verify(self, result: VerifyResult) -> None:
        await self.bus.publish(
            VerifyEvent(**self._base(), attempt_no=result.attempt_no, result=result)
        )

    async def diagnosis(self, diagnosis: Diagnosis) -> None:
        await self.bus.publish(
            DiagnosisEvent(**self._base(), attempt_no=diagnosis.attempt_no, diagnosis=diagnosis)
        )

    async def verdict(
        self,
        status: RunStatus,
        reason: str,
        *,
        final_result: dict[str, Any] | None,
        attempts_used: int,
        credits_used: int,
        baseline_credits_estimate: int | None,
    ) -> None:
        await self.bus.publish(
            VerdictEvent(
                **self._base(),
                status=status,
                reason=reason,
                final_result=final_result,
                attempts_used=attempts_used,
                credits_used=credits_used,
                baseline_credits_estimate=baseline_credits_estimate,
            )
        )
