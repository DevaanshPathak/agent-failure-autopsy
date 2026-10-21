"""Replay a recorded run: the same UI events, re-emitted under a new run id.

Nothing is injected or changed apart from the run id, seq numbers and nested trace run ids, so
a replay shows exactly what was recorded. The UI labels it REPLAY from `Run.mode`.
"""

import asyncio
import json
import logging
from pathlib import Path

from app import db
from app.events import Emitter, RunEventBus, utcnow
from app.models import (
    Attempt,
    AttemptOutcome,
    AttemptStartedEvent,
    BudgetEvent,
    DiagnosisEvent,
    LiveViewEvent,
    Run,
    RunStatus,
    TraceKind,
    TraceUiEvent,
    UiEventAdapter,
    VerdictEvent,
    VerifyEvent,
)
from app.routes.dev import read_jsonl_lines

log = logging.getLogger(__name__)

MAX_GAP_S = 3.0


def trace_path(fixtures_dir: Path, site_id: str | None) -> Path | None:
    if not site_id:
        return None
    path = fixtures_dir / "traces" / f"{site_id}.jsonl"
    return path if path.is_file() else None


def _attempt(run: Run, attempt_no: int) -> Attempt | None:
    return next((a for a in run.attempts if a.attempt_no == attempt_no), None)


def apply_ui_event(run: Run, ev: object) -> None:
    """Rebuild the Run record from a stream of UI events (the same facts the UI shows)."""
    match ev:
        case AttemptStartedEvent():
            run.attempts.append(
                Attempt(attempt_no=ev.attempt_no, rung=ev.rung, config=ev.config, started_at=ev.ts)
            )
        case TraceUiEvent():
            attempt = _attempt(run, ev.attempt_no)
            if attempt is None:
                return
            raw = ev.event.raw
            if ev.event.kind is TraceKind.started:
                attempt.tf_run_id = ev.event.tf_run_id
            elif ev.event.kind is TraceKind.progress:
                attempt.progress_count += 1
                attempt.credits_estimated = attempt.num_of_steps or attempt.progress_count
            elif ev.event.kind is TraceKind.complete:
                status = raw.get("status")
                attempt.tf_status = status if isinstance(status, str) else None
                result = raw.get("result")
                attempt.result = result if isinstance(result, dict) else None
                attempt.finished_at = ev.ts
            elif ev.event.kind is TraceKind.run_snapshot:
                steps = raw.get("num_of_steps")
                if isinstance(steps, int):
                    attempt.num_of_steps = steps
                    attempt.credits_estimated = steps
            elif ev.event.kind in (TraceKind.fetch_result, TraceKind.fetch_error):
                attempt.tf_status = "OK" if ev.event.kind is TraceKind.fetch_result else "ERROR"
            elif ev.event.kind is TraceKind.extraction and raw.get("found"):
                try:
                    result = json.loads(raw.get("result_json") or "")
                except ValueError:
                    result = None
                attempt.result = result if isinstance(result, dict) else None
        case LiveViewEvent():
            if attempt := _attempt(run, ev.attempt_no):
                attempt.streaming_url = ev.streaming_url
        case BudgetEvent():
            run.credits_used = ev.credits_used
        case VerifyEvent():
            if attempt := _attempt(run, ev.attempt_no):
                attempt.verify = ev.result
                attempt.outcome = (
                    AttemptOutcome.verified if ev.result.passed else AttemptOutcome.rejected
                )
        case DiagnosisEvent():
            if attempt := _attempt(run, ev.attempt_no):
                attempt.diagnosis = ev.diagnosis
        case VerdictEvent():
            run.status = ev.status
            run.verdict_reason = ev.reason
            run.final_result = ev.final_result
            run.credits_used = ev.credits_used
            run.baseline_credits_estimate = ev.baseline_credits_estimate
            run.finished_at = utcnow()


async def replay_run(run: Run, bus: RunEventBus, fixtures_dir: Path, speed: float) -> None:
    """Stream the recorded trace for `run.request.site_id`. Never raises except on cancel."""
    em = Emitter(run.id, bus)
    path = trace_path(fixtures_dir, run.request.site_id)
    try:
        if path is None:
            raise FileNotFoundError(f"no recorded trace for site {run.request.site_id!r}")
        events = [UiEventAdapter.validate_json(line) for line in read_jsonl_lines(path)]
        run.status = RunStatus.running
        await db.save_run(run)
        previous = None
        for ev in events:
            if previous is not None:
                gap = max(0.0, (ev.ts - previous).total_seconds())
                await asyncio.sleep(min(gap / max(speed, 0.01), MAX_GAP_S))
            previous = ev.ts
            update: dict[str, object] = {"run_id": run.id, "seq": 0}
            if isinstance(ev, TraceUiEvent):
                trace = ev.event.model_copy(update={"run_id": run.id})
                update["event"] = trace
                await db.append_trace_event(trace)
            replayed = ev.model_copy(update=update)
            apply_ui_event(run, replayed)
            if isinstance(replayed, VerdictEvent):
                await db.save_run(run)  # saved before the verdict goes out, like a live run
            await bus.publish(replayed)
        if run.status in (RunStatus.queued, RunStatus.running):
            await _finish(run, em, RunStatus.error, "The recorded trace ended without a verdict.")
    except asyncio.CancelledError:
        await asyncio.shield(_finish(run, em, RunStatus.cancelled, "Cancelled by user."))
        raise
    except Exception as e:
        log.exception("replay of %s failed", run.id)
        await _finish(run, em, RunStatus.error, f"Replay failed: {type(e).__name__}: {e}")


async def _finish(run: Run, em: Emitter, status: RunStatus, reason: str) -> None:
    run.status = status
    run.verdict_reason = reason
    run.finished_at = utcnow()
    await db.save_run(run)
    await em.verdict(
        status,
        reason,
        final_result=run.final_result,
        attempts_used=len(run.attempts),
        credits_used=run.credits_used,
        baseline_credits_estimate=run.baseline_credits_estimate,
    )
