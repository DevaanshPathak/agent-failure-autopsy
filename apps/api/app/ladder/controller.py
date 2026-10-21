"""Ladder controller: runs attempts, enforces the budget, and emits every UI event."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app import db
from app.config import Settings
from app.diagnose.diagnoser import diagnose
from app.diagnose.rules import explain
from app.events import Emitter, RunEventBus, utcnow
from app.extract.fetch_extract import extract_from_fetch
from app.models import (
    RUNG_LABEL,
    Attempt,
    AttemptConfig,
    AttemptOutcome,
    BrowserProfile,
    Diagnosis,
    FetchExtraction,
    Run,
    Rung,
    RunStatus,
    TraceEvent,
    TraceKind,
    TraceSource,
)
from app.patch.planner import PlanContext, compose_goal
from app.sites import find_site
from app.tinyfish.client import (
    TinyFishClient,
    TinyFishError,
    build_agent_body,
    map_sse_event,
    normalize_tf_error,
)
from app.verify.verifier import verify

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 2.0
POLL_TIMEOUT_S = 120.0
CANCEL_GRACE_S = 15.0
WATCHDOG_EXTRA_S = 60.0
RETRY_BEFORE_START_S = 5.0
TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
# TinyFish refusals that another attempt cannot fix.
HARD_STOP_CODES = {
    "INSUFFICIENT_CREDITS",
    "FREE_ALLOWANCE_EXHAUSTED",
    "FORBIDDEN",
    "INVALID_API_KEY",
    "MISSING_API_KEY",
    "UNAUTHORIZED",
    "INVALID_INPUT",
}


@dataclass
class RunState:
    run: Run
    em: Emitter
    rung: Rung
    schema: dict[str, Any] | None
    skipped: set[Rung] = field(default_factory=set)
    prefixes: list[str] = field(default_factory=list)
    suffixes: list[str] = field(default_factory=list)
    from_fetch_cache: bool = False
    fetch_raw: dict[str, Any] | None = None
    fetch_text: str | None = None
    extraction: FetchExtraction | None = None
    reextract_tried: bool = False
    history: list[Diagnosis] = field(default_factory=list)
    history_rungs: list[Rung] = field(default_factory=list)
    patches_applied: list[str] = field(default_factory=list)
    schema_entitled: bool = True
    active: tuple[Attempt, "_Trace"] | None = None


class _Trace:
    """Collects one attempt's trace events and emits each as it is recorded."""

    def __init__(self, em: Emitter, run_id: str, attempt_no: int) -> None:
        self.em = em
        self.run_id = run_id
        self.attempt_no = attempt_no
        self.events: list[TraceEvent] = []
        self.seq = 0

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    async def record(self, ev: TraceEvent) -> TraceEvent:
        self.events.append(ev)
        await self.em.trace(ev)
        return ev

    async def note(
        self,
        kind: TraceKind,
        label: str,
        raw: dict[str, Any] | None = None,
        *,
        source: TraceSource = TraceSource.system,
        tf_run_id: str | None = None,
    ) -> TraceEvent:
        return await self.record(
            TraceEvent(
                run_id=self.run_id,
                attempt_no=self.attempt_no,
                seq=self.next_seq(),
                kind=kind,
                source=source,
                ts=utcnow(),
                tf_run_id=tf_run_id,
                label=label,
                raw=raw or {},
            )
        )


def _first_page(fetch_raw: dict[str, Any] | None) -> dict[str, Any] | None:
    results = (fetch_raw or {}).get("results") or []
    return results[0] if results and isinstance(results[0], dict) else None


def _apply_complete(attempt: Attempt, obj: dict[str, Any]) -> None:
    """Copy status/result/error from a COMPLETE event or a run object onto the attempt."""
    status = obj.get("status")
    attempt.tf_status = status if isinstance(status, str) else None
    result = obj.get("result")
    if result is not None and not isinstance(result, dict):
        result = {"value": result}
    attempt.result = result
    attempt.tf_error = normalize_tf_error(obj)


class LadderController:
    def __init__(
        self,
        settings: Settings,
        tinyfish: TinyFishClient | None,
        claude: Any,
        bus: RunEventBus,
    ) -> None:
        self.settings = settings
        self.tinyfish = tinyfish
        self.claude = claude
        self.bus = bus

    # --- Config --------------------------------------------------------------------------------

    def build_config(self, st: RunState, attempt_no: int) -> AttemptConfig:
        run = st.run
        stealth = st.rung is Rung.agent_stealth
        return AttemptConfig(
            attempt_no=attempt_no,
            rung=st.rung,
            url=run.request.url,
            goal=compose_goal(run.request.goal, st.prefixes, st.suffixes),
            output_schema=st.schema if st.schema_entitled else None,
            browser_profile=BrowserProfile.stealth if stealth else BrowserProfile.lite,
            proxy_enabled=stealth,
            proxy_country=self.settings.proxy_country if stealth else None,
            max_duration_seconds=self.settings.agent_max_duration_s,
            from_fetch_cache=st.rung is Rung.fetch and st.from_fetch_cache,
            patches_applied=list(st.patches_applied),
            credit_limit=0 if st.rung is Rung.fetch else max(0, run.max_credits - run.credits_used),
        )

    # --- Agent attempt -------------------------------------------------------------------------

    async def _safe_cancel(self, tf_run_id: str) -> None:
        assert self.tinyfish is not None
        try:
            await self.tinyfish.cancel(tf_run_id)
        except (TinyFishError, httpx.HTTPError) as e:
            log.warning("cancel %s failed: %s", tf_run_id, e)

    async def _poll_until_terminal(self, tf_run_id: str, timeout_s: float) -> dict[str, Any] | None:
        assert self.tinyfish is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while loop.time() < deadline:
            try:
                run_obj = await self.tinyfish.get_run(tf_run_id)
                if run_obj.get("status") in TERMINAL_STATUSES:
                    return run_obj
            except (TinyFishError, httpx.HTTPError) as e:
                log.warning("poll %s failed: %s", tf_run_id, e)
            await asyncio.sleep(POLL_INTERVAL_S)
        return None

    async def _stream(
        self, attempt: Attempt, tr: _Trace, cfg: AttemptConfig
    ) -> tuple[int, bool, bool]:
        """Consume the SSE stream. Returns (progress_count, completed, cancelled_at_limit)."""
        assert self.tinyfish is not None
        loop = asyncio.get_running_loop()
        progress = 0
        cancelled = False
        cancel_deadline = 0.0
        body = build_agent_body(cfg)
        for try_no in (1, 2):
            try:
                async for raw in self.tinyfish.agent_stream(body):
                    is_progress = raw.get("type") == "PROGRESS"
                    if is_progress:
                        progress += 1
                        attempt.progress_count = progress
                    ev = map_sse_event(
                        raw,
                        run_id=tr.run_id,
                        attempt_no=tr.attempt_no,
                        seq=tr.next_seq(),
                        step_no=progress if is_progress else None,
                        now=utcnow(),
                    )
                    await tr.record(ev)
                    kind = raw.get("type")
                    if kind == "STARTED" and ev.tf_run_id:
                        attempt.tf_run_id = ev.tf_run_id
                    elif kind == "STREAMING_URL" and isinstance(raw.get("streaming_url"), str):
                        attempt.streaming_url = raw["streaming_url"]
                        await tr.em.live_view(cfg.attempt_no, raw["streaming_url"])
                    elif kind == "COMPLETE":
                        _apply_complete(attempt, raw)
                        return progress, True, cancelled
                    if is_progress and not cancelled and progress >= cfg.credit_limit:
                        cancelled = True
                        cancel_deadline = loop.time() + CANCEL_GRACE_S
                        if attempt.tf_run_id:
                            await self._safe_cancel(attempt.tf_run_id)
                        await tr.note(
                            TraceKind.system, f"Cancelled at the credit limit ({cfg.credit_limit})"
                        )
                    if cancelled and loop.time() > cancel_deadline:
                        break
                return progress, False, cancelled
            except TinyFishError as e:
                retryable = e.http_status in (429, 503)
                if attempt.tf_run_id is None and retryable and try_no == 1:
                    await tr.note(
                        TraceKind.stream_error,
                        f"TinyFish {e.code}; retrying once in {RETRY_BEFORE_START_S:.0f}s",
                        e.as_dict(),
                    )
                    await asyncio.sleep(RETRY_BEFORE_START_S)
                    continue
                attempt.outcome = AttemptOutcome.error
                attempt.tf_error = e.as_dict()
                await tr.note(
                    TraceKind.stream_error, f"TinyFish refused the run: {e.code}", e.as_dict()
                )
                return progress, False, cancelled
            except httpx.HTTPError as e:
                await tr.note(TraceKind.stream_error, f"Stream error: {type(e).__name__}")
                return progress, False, cancelled
        return progress, False, cancelled

    async def run_agent_attempt(
        self, st: RunState, cfg: AttemptConfig
    ) -> tuple[Attempt, list[TraceEvent]]:
        assert self.tinyfish is not None, "live agent attempts need a TinyFish client"
        attempt = Attempt(attempt_no=cfg.attempt_no, rung=cfg.rung, config=cfg, started_at=utcnow())
        tr = _Trace(st.em, st.run.id, cfg.attempt_no)
        st.active = (attempt, tr)
        progress, completed, cancelled = 0, False, False
        try:
            async with asyncio.timeout(cfg.max_duration_seconds + WATCHDOG_EXTRA_S):
                progress, completed, cancelled = await self._stream(attempt, tr, cfg)
        except TimeoutError:
            await tr.note(
                TraceKind.stream_error,
                f"No result after {cfg.max_duration_seconds + WATCHDOG_EXTRA_S:.0f}s; cancelling",
            )
            if attempt.tf_run_id:
                await self._safe_cancel(attempt.tf_run_id)

        if not completed and attempt.outcome is not AttemptOutcome.error:
            if attempt.tf_run_id:
                await tr.note(TraceKind.stream_error, "Stream dropped — polling the run status")
                run_obj = await self._poll_until_terminal(attempt.tf_run_id, POLL_TIMEOUT_S)
                if run_obj is not None:
                    _apply_complete(attempt, run_obj)
                    completed = True
                    await tr.record(
                        TraceEvent(
                            run_id=tr.run_id,
                            attempt_no=tr.attempt_no,
                            seq=tr.next_seq(),
                            kind=TraceKind.complete,
                            source=TraceSource.tinyfish_runs,
                            ts=utcnow(),
                            tf_run_id=attempt.tf_run_id,
                            label=f"Agent finished: {run_obj.get('status')}",
                            raw=run_obj,
                        )
                    )
                else:
                    await self._safe_cancel(attempt.tf_run_id)
                    attempt.outcome = AttemptOutcome.error
                    attempt.tf_error = {"code": "STREAM_LOST", "message": "no terminal status"}
            else:
                attempt.outcome = AttemptOutcome.error
                attempt.tf_error = attempt.tf_error or {
                    "code": "NO_RUN",
                    "message": "the stream ended before TinyFish started a run",
                }

        if attempt.tf_run_id:
            try:
                snap = await self.tinyfish.get_run(attempt.tf_run_id, screenshots="none")
                steps = snap.get("num_of_steps")
                attempt.num_of_steps = steps if isinstance(steps, int) else None
                proxy_on = bool((snap.get("browser_config") or {}).get("proxy_enabled"))
                await tr.note(
                    TraceKind.run_snapshot,
                    f"Run record: {steps} steps, proxy {'on' if proxy_on else 'off'}",
                    snap,
                    source=TraceSource.tinyfish_runs,
                    tf_run_id=attempt.tf_run_id,
                )
                if cfg.proxy_enabled and "browser_config" in snap and not proxy_on:
                    await tr.note(
                        TraceKind.system, "Warning: TinyFish reports the proxy was not applied"
                    )
            except (TinyFishError, httpx.HTTPError) as e:
                await tr.note(TraceKind.stream_error, f"Could not read the run record: {e}")

        attempt.progress_count = progress
        attempt.credits_estimated = (
            attempt.num_of_steps if attempt.num_of_steps is not None else progress
        )
        if cancelled:
            attempt.outcome = AttemptOutcome.cancelled_budget
        attempt.finished_at = utcnow()
        return attempt, tr.events

    # --- Fetch attempt (rung 1) ----------------------------------------------------------------

    async def run_fetch_attempt(
        self, st: RunState, cfg: AttemptConfig
    ) -> tuple[Attempt, list[TraceEvent], dict[str, Any] | None]:
        """Fetch the page (or reuse the cached Fetch text) and let Claude extract the answer.
        Costs 0 TinyFish credits. Returns (attempt, trace, the Fetch response used)."""
        attempt = Attempt(attempt_no=cfg.attempt_no, rung=cfg.rung, config=cfg, started_at=utcnow())
        tr = _Trace(st.em, st.run.id, cfg.attempt_no)
        st.active = (attempt, tr)
        fetch_raw: dict[str, Any] | None

        if cfg.from_fetch_cache and st.fetch_raw is not None:
            fetch_raw = st.fetch_raw
            page = _first_page(fetch_raw)
            await tr.note(
                TraceKind.fetch_result,
                "Using cached Fetch text (0 credits)",
                {
                    "cached": True,
                    "final_url": (page or {}).get("final_url"),
                    "chars": len(st.fetch_text or ""),
                },
            )
        else:
            assert self.tinyfish is not None, "the Fetch rung needs a TinyFish client"
            try:
                fetch_raw = await self.tinyfish.fetch(cfg.url)
            except (TinyFishError, httpx.HTTPError) as e:
                err = (
                    e.as_dict()
                    if isinstance(e, TinyFishError)
                    else {"code": "NETWORK", "message": str(e)}
                )
                attempt.tf_status = "ERROR"
                attempt.tf_error = err
                attempt.outcome = AttemptOutcome.error
                await tr.note(
                    TraceKind.fetch_error,
                    f"Fetch failed: {err['code']}",
                    err,
                    source=TraceSource.tinyfish_fetch,
                )
                attempt.finished_at = utcnow()
                return attempt, tr.events, None
            st.fetch_raw = fetch_raw
            page = _first_page(fetch_raw)
            st.fetch_text = page.get("text") if page and isinstance(page.get("text"), str) else None
            if page is not None:
                where = page.get("final_url") or page.get("url") or cfg.url
                title = page.get("title")
                label = f"Fetched {where} ({title})" if title else f"Fetched {where}"
                await tr.note(
                    TraceKind.fetch_result, label, fetch_raw, source=TraceSource.tinyfish_fetch
                )
            else:
                errors = fetch_raw.get("errors") or [{}]
                code, status = errors[0].get("error"), errors[0].get("status")
                await tr.note(
                    TraceKind.fetch_error,
                    f"Fetch error: {code}" + (f" {status}" if status else ""),
                    fetch_raw,
                    source=TraceSource.tinyfish_fetch,
                )

        page = _first_page(fetch_raw)
        attempt.tf_status = "OK" if page is not None else "ERROR"
        if page is not None and self.claude is not None:
            result, extraction, err = await extract_from_fetch(
                self.claude,
                goal=cfg.goal,
                output_schema=cfg.output_schema,
                expected=st.run.request.expected,
                page=page,
                max_chars=self.settings.fetch_text_max_chars,
            )
            if extraction is not None:
                st.extraction = extraction
            if result is not None:
                label = f"Extractor: found {', '.join(result)}"
            elif err:
                label = f"Extractor error: {err}"
            else:
                missing = ", ".join(extraction.missing) if extraction else ""
                label = f"Extractor: {missing or 'nothing'} not in the page text"
            raw = extraction.model_dump() if extraction else {"error": err}
            await tr.note(TraceKind.extraction, label, raw, source=TraceSource.claude_extract)
            attempt.result = result
        attempt.credits_estimated = 0
        attempt.finished_at = utcnow()
        return attempt, tr.events, fetch_raw

    # --- Run -----------------------------------------------------------------------------------

    def _baseline_estimate(self, run: Run) -> int:
        """Naive baseline (ADR-005): always stealth + proxy, run 3 times = 3 x steps of one run."""
        site = find_site(self.settings.fixtures_dir, run.request.site_id)
        agent_steps = [
            a.num_of_steps
            for a in run.attempts
            if a.rung is not Rung.fetch and a.num_of_steps is not None
        ]
        if site is not None and site.baseline_steps:
            steps = site.baseline_steps
        elif agent_steps:
            steps = max(agent_steps)
        else:
            steps = self.settings.baseline_default_steps
        return 3 * steps

    async def _verdict(
        self, st: RunState, status: RunStatus, reason: str, final_result: dict[str, Any] | None
    ) -> None:
        run = st.run
        run.status = status
        run.finished_at = utcnow()
        run.verdict_reason = reason
        run.final_result = final_result
        run.baseline_credits_estimate = self._baseline_estimate(run)
        await db.save_run(run)
        await st.em.verdict(
            status,
            reason,
            final_result=final_result,
            attempts_used=len(run.attempts),
            credits_used=run.credits_used,
            baseline_credits_estimate=run.baseline_credits_estimate,
        )

    async def execute(self, run_id: str) -> None:
        """Climb the ladder for one run. Never raises: a crash becomes an `error` verdict."""
        run = await db.get_run(run_id)
        if run is None:
            log.error("run %s not found", run_id)
            return
        st = RunState(
            run=run,
            em=Emitter(run_id, self.bus),
            rung=run.request.start_rung,
            schema=run.request.output_schema,
        )
        try:
            await self._climb(st)
        except asyncio.CancelledError:
            await asyncio.shield(self._on_user_cancel(st))
            raise
        except Exception as e:
            log.exception("run %s crashed", run_id)
            await self._verdict(
                st, RunStatus.error, f"Internal error: {type(e).__name__}: {e}", None
            )

    async def _on_user_cancel(self, st: RunState) -> None:
        """POST /runs/{id}/cancel: stop the TinyFish run in flight, keep what it cost, say so."""
        run = st.run
        if st.active is not None and st.active[0] not in run.attempts:
            attempt, tr = st.active
            if attempt.tf_run_id:
                await self._safe_cancel(attempt.tf_run_id)
            await tr.note(TraceKind.system, "Cancelled by user")
            attempt.outcome = AttemptOutcome.error
            attempt.credits_estimated = attempt.progress_count
            attempt.finished_at = utcnow()
            run.attempts.append(attempt)
            run.credits_used += attempt.credits_estimated
        await self._verdict(st, RunStatus.cancelled, "Cancelled by user.", None)

    def _plan_context(self, st: RunState, attempt: Attempt) -> PlanContext:
        return PlanContext(
            rung=attempt.rung,
            request=st.run.request,
            from_fetch_cache=attempt.config.from_fetch_cache,
            current_schema=st.schema,
            skipped=set(st.skipped),
            history=list(st.history),
            history_rungs=list(st.history_rungs),
            fetch_text_available=bool(st.fetch_text),
            fetch_extraction_found=bool(st.extraction and st.extraction.found),
            fetch_text=st.fetch_text,
            reextract_tried=st.reextract_tried,
            proxy_country=self.settings.proxy_country,
            schema_entitled=st.schema_entitled,
        )

    async def _climb(self, st: RunState) -> None:
        run, em, settings = st.run, st.em, self.settings
        run.status = RunStatus.running
        await db.save_run(run)
        await em.budget(0, run.max_attempts, 0, run.max_credits)

        if st.rung is Rung.fetch and self.claude is None:
            st.rung = Rung.agent
            st.skipped.add(Rung.fetch)
            await em.rung_change(
                None,
                Rung.agent,
                [Rung.fetch],
                "Rung 1 needs the extractor (ANTHROPIC_API_KEY not set) — starting at Rung 2.",
            )
        else:
            await em.rung_change(None, st.rung, [], f"Start at {RUNG_LABEL[st.rung]}.")

        for attempt_no in range(1, run.max_attempts + 1):
            if st.rung is not Rung.fetch:
                remaining = run.max_credits - run.credits_used
                if remaining < settings.agent_min_credits:
                    await self._verdict(
                        st,
                        RunStatus.budget_exhausted,
                        "Budget spent: not enough credits left for another agent attempt "
                        f"({remaining} left, {settings.agent_min_credits} needed).",
                        None,
                    )
                    return

            cfg = self.build_config(st, attempt_no)
            await em.attempt_started(cfg)
            fetch_used: dict[str, Any] | None = None
            if st.rung is Rung.fetch:
                attempt, trace, fetch_used = await self.run_fetch_attempt(st, cfg)
            else:
                attempt, trace = await self.run_agent_attempt(st, cfg)
            run.attempts.append(attempt)
            run.credits_used += attempt.credits_estimated
            await db.save_run(run)
            await em.budget(len(run.attempts), run.max_attempts, run.credits_used, run.max_credits)

            tf_error = attempt.tf_error or {}
            code = str(tf_error.get("code") or "").upper()
            if attempt.outcome is AttemptOutcome.error and code in HARD_STOP_CODES:
                message = str(tf_error.get("message") or "")
                if code == "FORBIDDEN" and "output_schema" in message and cfg.output_schema:
                    st.schema_entitled = False  # retry the same rung without a schema
                    continue
                await self._verdict(
                    st, RunStatus.error, f"TinyFish refused the request: {code} — {message}", None
                )
                return

            vr = verify(attempt, run.request, trace, fetch_used)
            attempt.verify = vr
            await em.verify(vr)
            if vr.passed:
                attempt.outcome = AttemptOutcome.verified
                fixed = [d.failure_class.value for d in st.history]
                reason = f"Verified on attempt {attempt_no} ({RUNG_LABEL[attempt.rung]})"
                if fixed:
                    reason += f" after fixing {' → '.join(fixed)}"
                await self._verdict(st, RunStatus.verified, reason + ".", attempt.result)
                return
            if attempt.outcome is AttemptOutcome.cancelled_budget:
                await self._verdict(
                    st,
                    RunStatus.budget_exhausted,
                    "Budget spent: the attempt was cancelled at the credit limit.",
                    None,
                )
                return
            attempt.outcome = attempt.outcome or AttemptOutcome.rejected

            diagnosis = await diagnose(
                attempt=attempt,
                vr=vr,
                trace=trace,
                fetch=fetch_used,
                fetch_text=st.fetch_text,
                extraction=st.extraction if attempt.rung is Rung.fetch else None,
                history=list(st.history),
                plan_ctx=self._plan_context(st, attempt),
                claude=self.claude,
                threshold=settings.rules_confidence_threshold,
                goal=run.request.goal,
                url=run.request.url,
            )
            attempt.diagnosis = diagnosis
            await db.save_run(run)
            await em.diagnosis(diagnosis)
            st.history.append(diagnosis)
            st.history_rungs.append(attempt.rung)

            patch = diagnosis.patch
            if patch.stop or not diagnosis.recoverable:
                await self._verdict(
                    st,
                    RunStatus.unrecoverable,
                    patch.stop_reason or explain(diagnosis.failure_class),
                    None,
                )
                return

            previous = st.rung
            st.rung = patch.next_rung or st.rung
            st.skipped |= set(patch.skip_rungs)
            if patch.goal_prefix and patch.goal_prefix not in st.prefixes:
                st.prefixes.append(patch.goal_prefix)
            if patch.goal_suffix and patch.goal_suffix not in st.suffixes:
                st.suffixes.append(patch.goal_suffix)
            if patch.output_schema is not None:
                st.schema = patch.output_schema
            st.from_fetch_cache = patch.reextract_from_fetch
            st.reextract_tried = st.reextract_tried or patch.reextract_from_fetch
            st.patches_applied.extend(patch.summary)
            if st.rung is not previous or patch.skip_rungs:
                headline = patch.summary[0] if patch.summary else "next attempt"
                await em.rung_change(
                    previous,
                    st.rung,
                    list(patch.skip_rungs),
                    f"{diagnosis.failure_class.value}: {headline}",
                )

        await self._verdict(
            st,
            RunStatus.budget_exhausted,
            f"Budget spent: {run.max_attempts}/{run.max_attempts} attempts used "
            f"({run.credits_used}/{run.max_credits} credits).",
            None,
        )
