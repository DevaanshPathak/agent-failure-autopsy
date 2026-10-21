"""Rule-based failure classifier (pure).

Two passes: rules R1-R9 run on strong signals (result, steps, TinyFish/Fetch errors, profile
hints) and the first match wins; only if nothing matched do R1-R3 run again on weak signals
(Fetch page text) at a confidence low enough to defer to Claude. Challenge pages often contain
words like "turnstile" or "captcha-delivery", which must not hide a hard `bot_blocked` error.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.models import (
    Attempt,
    BlockSignal,
    BlockSignalKind,
    CheckName,
    Diagnosis,
    Evidence,
    EvidenceSource,
    FailureClass,
    FetchExtraction,
    Rung,
    SignalWhere,
    TraceEvent,
    TraceKind,
    VerifyResult,
)
from app.verify.verifier import (
    RE_CAPTCHA,
    RE_LOGIN,
    RE_LOGIN_URL,
    RE_POPUP,
    cut,
    is_blocking,
)

STRONG_WHERE = {
    SignalWhere.result,
    SignalWhere.progress,
    SignalWhere.tf_error,
    SignalWhere.fetch_error,
    SignalWhere.profile_hint,
}
CAPTCHA_KINDS = {BlockSignalKind.captcha}
AUTH_KINDS = {
    BlockSignalKind.fetch_login_required,
    BlockSignalKind.profile_hint_auth_wall,
    BlockSignalKind.login_form,
}
BOT_KINDS = {
    BlockSignalKind.fetch_bot_blocked,
    BlockSignalKind.site_blocked_error,
    BlockSignalKind.profile_hint_bot_challenge,
    BlockSignalKind.access_denied,
    BlockSignalKind.http_403,
}
WEAK_CONFIDENCE = 0.6

EXPLAIN: dict[FailureClass, str] = {
    FailureClass.needs_interaction: (
        "The data only appears after interacting with the page in a real browser, "
        "so a read-only fetch cannot see it."
    ),
    FailureClass.popup_overlay: (
        "A cookie/consent or popup dialog covered the page{at_step}, "
        "so the agent finished without reading the data."
    ),
    FailureClass.bot_block: (
        "The site served a bot-protection or access-denied page instead of the content."
    ),
    FailureClass.misread_page: (
        "The agent returned data, but it does not match the expected output: {detail}."
    ),
    FailureClass.auth_wall: "The content is behind a login wall.",
    FailureClass.captcha: "The site served a CAPTCHA, which TinyFish cannot solve.",
}

_SOURCE_OF_WHERE = {
    SignalWhere.result: EvidenceSource.result,
    SignalWhere.progress: EvidenceSource.trace,
    SignalWhere.tf_error: EvidenceSource.tinyfish_error,
    SignalWhere.fetch_error: EvidenceSource.tinyfish_error,
    SignalWhere.fetch_text: EvidenceSource.fetch_text,
    SignalWhere.profile_hint: EvidenceSource.tinyfish_error,
}


@dataclass
class RuleVerdict:
    failure_class: FailureClass | None
    confidence: float
    failing_step_seq: int | None
    evidence: list[Evidence] = field(default_factory=list)
    explanation: str = ""
    rule: str = ""


def explain(failure_class: FailureClass, *, step_no: int | None = None, detail: str = "") -> str:
    at_step = f" at step {step_no}" if step_no else ""
    return EXPLAIN[failure_class].format(at_step=at_step, detail=detail or "see the verifier")


@dataclass
class _Ctx:
    attempt: Attempt
    vr: VerifyResult
    trace: list[TraceEvent]
    extraction: FetchExtraction | None
    fetch: dict[str, Any] | None

    @property
    def is_agent(self) -> bool:
        return self.attempt.rung is not Rung.fetch

    def first(self, *kinds: TraceKind) -> TraceEvent | None:
        return next((ev for ev in self.trace if ev.kind in kinds), None)

    def progress_matching(self, pattern: re.Pattern[str]) -> TraceEvent | None:
        return next(
            (ev for ev in self.trace if ev.kind is TraceKind.progress and pattern.search(ev.label)),
            None,
        )

    def check(self, name: CheckName) -> bool | None:
        found = next((c for c in self.vr.checks if c.name is name), None)
        return None if found is None else found.passed

    def failed_detail(self) -> str | None:
        return next((c.detail for c in self.vr.checks if not c.passed), None)

    def signals(self, kinds: set[BlockSignalKind], strong: bool) -> list[BlockSignal]:
        return [
            s
            for s in self.vr.block_signals
            if s.kind in kinds and ((s.where in STRONG_WHERE) is strong)
        ]

    def fetch_error(self) -> dict[str, Any] | None:
        errors = (self.fetch or {}).get("errors") or []
        return errors[0] if errors and isinstance(errors[0], dict) else None

    def fetch_final_url(self) -> str:
        results = (self.fetch or {}).get("results") or []
        if results and isinstance(results[0], dict):
            return str(results[0].get("final_url") or results[0].get("url") or "")
        return ""


def _evidence(ctx: _Ctx, first: list[Evidence]) -> list[Evidence]:
    evidence = [e for e in first if e.quote.strip()][:2]
    detail = ctx.failed_detail()
    if detail:
        evidence.append(Evidence(source=EvidenceSource.verifier, quote=cut(detail, 300)))
    if not evidence:
        evidence.append(Evidence(source=EvidenceSource.verifier, quote=cut(ctx.vr.summary, 300)))
    return evidence[:3]


def _signal_evidence(signal: BlockSignal) -> Evidence:
    return Evidence(
        source=_SOURCE_OF_WHERE[signal.where],
        quote=cut(signal.evidence, 300),
        event_seq=signal.event_seq,
    )


def _terminal_seq(ctx: _Ctx) -> int | None:
    kinds = (
        (TraceKind.complete,) if ctx.is_agent else (TraceKind.fetch_error, TraceKind.fetch_result)
    )
    ev = ctx.first(*kinds) or (ctx.trace[-1] if ctx.trace else None)
    return ev.seq if ev else None


def _verdict(
    ctx: _Ctx,
    cls: FailureClass,
    confidence: float,
    step: TraceEvent | None,
    fallback_seq: int | None,
    evidence: list[Evidence],
    rule: str,
) -> RuleVerdict:
    detail = ctx.failed_detail() or ""
    return RuleVerdict(
        failure_class=cls,
        confidence=confidence,
        failing_step_seq=step.seq if step else fallback_seq,
        evidence=_evidence(ctx, evidence),
        explanation=explain(cls, step_no=step.step_no if step else None, detail=detail),
        rule=rule,
    )


def _block_rules(ctx: _Ctx, strong: bool) -> RuleVerdict | None:
    """R1-R3 (captcha > auth wall > bot block), on strong or weak signals."""
    confidence = 0.95 if strong else WEAK_CONFIDENCE
    if sigs := ctx.signals(CAPTCHA_KINDS, strong):
        step = ctx.progress_matching(RE_CAPTCHA)
        return _verdict(
            ctx,
            FailureClass.captcha,
            confidence,
            step,
            sigs[0].event_seq or _terminal_seq(ctx),
            [_signal_evidence(sigs[0])],
            "R1",
        )

    confidence = 0.9 if strong else WEAK_CONFIDENCE
    auth = ctx.signals(AUTH_KINDS, strong)
    login_step = ctx.progress_matching(RE_LOGIN_URL) or ctx.progress_matching(RE_LOGIN)
    login_url = RE_LOGIN_URL.search(ctx.fetch_final_url())
    if auth or (strong and (login_step or login_url)):
        evidence = [_signal_evidence(auth[0])] if auth else []
        if login_url and not auth:
            evidence.append(
                Evidence(source=EvidenceSource.tinyfish_error, quote=ctx.fetch_final_url())
            )
        if login_step and not auth:
            evidence.append(
                Evidence(
                    source=EvidenceSource.trace, quote=login_step.label, event_seq=login_step.seq
                )
            )
        fallback = auth[0].event_seq if auth else _terminal_seq(ctx)
        return _verdict(
            ctx, FailureClass.auth_wall, confidence, login_step, fallback, evidence, "R2"
        )

    bot = ctx.signals(BOT_KINDS, strong)
    fetch_err = ctx.fetch_error()
    throttled = (
        strong
        and fetch_err is not None
        and fetch_err.get("error") == "target_http_error"
        and fetch_err.get("status") in (403, 429)
    )
    if bot or throttled:
        evidence = (
            [_signal_evidence(bot[0])]
            if bot
            else [
                Evidence(
                    source=EvidenceSource.tinyfish_error,
                    quote=f"target_http_error {fetch_err['status']}",
                )
            ]
        )
        step = next(
            (
                ev
                for ev in ctx.trace
                if bot and ev.kind is TraceKind.progress and ev.seq == bot[0].event_seq
            ),
            None,
        )
        fallback = bot[0].event_seq if bot and bot[0].event_seq else _terminal_seq(ctx)
        return _verdict(ctx, FailureClass.bot_block, confidence, step, fallback, evidence, "R3")
    return None


def classify(
    attempt: Attempt,
    vr: VerifyResult,
    trace: list[TraceEvent],
    history: list[Diagnosis],
    extraction: FetchExtraction | None,
    fetch: dict[str, Any] | None = None,
) -> RuleVerdict:
    ctx = _Ctx(attempt=attempt, vr=vr, trace=trace, extraction=extraction, fetch=fetch)

    # Pass 1: strong signals.
    if verdict := _block_rules(ctx, strong=True):
        return verdict

    failed = {c.name for c in vr.checks if not c.passed}
    if ctx.is_agent:
        popup_step = ctx.progress_matching(RE_POPUP)
        content_failed = failed & {
            CheckName.result_present,
            CheckName.expected,
            CheckName.not_all_null,
        }
        if popup_step and content_failed:  # R4
            return _verdict(
                ctx,
                FailureClass.popup_overlay,
                0.9,
                popup_step,
                None,
                [
                    Evidence(
                        source=EvidenceSource.trace,
                        quote=popup_step.label,
                        event_seq=popup_step.seq,
                    )
                ],
                "R4",
            )
        result_text = json.dumps(attempt.result, ensure_ascii=False) if attempt.result else ""
        if failed and (m := RE_POPUP.search(result_text)):  # R5
            return _verdict(
                ctx,
                FailureClass.popup_overlay,
                0.8,
                None,
                _terminal_seq(ctx),
                [
                    Evidence(
                        source=EvidenceSource.result,
                        quote=cut(result_text[max(0, m.start() - 60) : m.end() + 60], 300),
                    )
                ],
                "R5",
            )
    else:
        fetch_err = ctx.fetch_error()
        empty = fetch_err is not None and fetch_err.get("error") == "empty_content"
        if empty or CheckName.result_present in failed:  # R6
            hint = (extraction.interaction_hint if extraction else "").strip()
            step = ctx.first(TraceKind.extraction)
            evidence = (
                [
                    Evidence(
                        source=EvidenceSource.trace,
                        quote=cut(hint, 300),
                        event_seq=step.seq if step else None,
                    )
                ]
                if hint
                else []
            )
            fallback = step.seq if step else _terminal_seq(ctx)
            return _verdict(
                ctx,
                FailureClass.needs_interaction,
                0.9 if hint else 0.8,
                None,
                fallback,
                evidence,
                "R6",
            )

    result_ok = ctx.check(CheckName.result_present) and ctx.check(CheckName.not_all_null)
    content_mismatch = failed & {CheckName.output_schema, CheckName.expected}
    no_blocking = not any(is_blocking(s) for s in vr.block_signals)
    if result_ok and content_mismatch and no_blocking:  # R7
        anchor = ctx.first(TraceKind.complete) if ctx.is_agent else ctx.first(TraceKind.extraction)
        return _verdict(
            ctx,
            FailureClass.misread_page,
            0.85,
            None,
            anchor.seq if anchor else _terminal_seq(ctx),
            [],
            "R7",
        )

    if ctx.is_agent and attempt.tf_status == "COMPLETED" and attempt.result is None:  # R8
        return _verdict(ctx, FailureClass.misread_page, 0.5, None, _terminal_seq(ctx), [], "R8")

    # Pass 2: weak signals only (Fetch page text).
    if verdict := _block_rules(ctx, strong=False):
        return verdict

    return RuleVerdict(  # R9
        failure_class=None,
        confidence=0.0,
        failing_step_seq=_terminal_seq(ctx),
        evidence=_evidence(ctx, []),
        explanation="",
        rule="R9",
    )
