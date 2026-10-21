from datetime import UTC, datetime

from app.diagnose.diagnoser import diagnose
from app.llm.claude import ParseOutcome
from app.models import (
    Attempt,
    AttemptConfig,
    DiagnosisSource,
    EvidenceSource,
    FailureClass,
    LlmDiagnosis,
    Rung,
    RunRequest,
    TraceEvent,
    TraceKind,
    TraceSource,
)
from app.patch.planner import PlanContext
from app.verify.verifier import verify
from tests.fakes import FakeClaude

T0 = datetime(2026, 11, 1, 11, 0, tzinfo=UTC)
REQ = RunRequest(url="https://x.example", goal="List the products")


def _ev(seq: int, kind: TraceKind, label: str = "", step_no: int | None = None) -> TraceEvent:
    return TraceEvent(
        run_id="r",
        attempt_no=1,
        seq=seq,
        kind=kind,
        source=TraceSource.tinyfish_sse,
        ts=T0,
        step_no=step_no,
        label=label or kind.value,
        raw={},
    )


def _attempt(**fields) -> Attempt:
    cfg = AttemptConfig(
        attempt_no=1,
        rung=Rung.agent,
        url=REQ.url,
        goal=REQ.goal,
        max_duration_seconds=150,
        credit_limit=40,
    )
    return Attempt(attempt_no=1, rung=Rung.agent, config=cfg, started_at=T0, **fields)


async def _diagnose(attempt: Attempt, trace: list[TraceEvent], claude):
    vr = verify(attempt, REQ, trace, None)
    return await diagnose(
        attempt=attempt,
        vr=vr,
        trace=trace,
        fetch=None,
        fetch_text=None,
        extraction=None,
        history=[],
        plan_ctx=PlanContext(rung=Rung.agent, request=REQ),
        claude=claude,
        threshold=0.8,
        goal=REQ.goal,
        url=REQ.url,
    )


POPUP_TRACE = [
    _ev(1, TraceKind.started),
    _ev(2, TraceKind.progress, "A cookie consent dialog is covering the page", step_no=1),
    _ev(3, TraceKind.complete),
]
VAGUE_TRACE = [
    _ev(1, TraceKind.started),
    _ev(2, TraceKind.progress, "Opened the store page", step_no=1),
    _ev(3, TraceKind.progress, "Waited for the grid", step_no=2),
    _ev(4, TraceKind.complete),
]


def _llm(**overrides) -> LlmDiagnosis:
    base = dict(
        failure_class=FailureClass.needs_interaction,
        confidence=0.7,
        failing_step_seq=3,
        evidence_quotes=["Waited for the grid", "this quote is invented"],
        explanation="The products only load after scrolling.",
        suggested_goal_prefix="",
        suggested_goal_suffix="Scroll down until products appear.",
    )
    return LlmDiagnosis(**{**base, **overrides})


async def test_confident_rule_never_calls_claude():
    claude = FakeClaude({LlmDiagnosis: [_llm()]})
    d = await _diagnose(_attempt(tf_status="COMPLETED", result=None), POPUP_TRACE, claude)
    assert (d.failure_class, d.source) == (FailureClass.popup_overlay, DiagnosisSource.rules)
    assert (d.failing_step_seq, d.failing_step_label) == (
        2,
        "A cookie consent dialog is covering the page",
    )
    assert claude.calls == []


async def test_unsure_rule_asks_claude_and_keeps_only_verbatim_quotes():
    claude = FakeClaude({LlmDiagnosis: [_llm()]})
    d = await _diagnose(_attempt(tf_status="COMPLETED", result=None), VAGUE_TRACE, claude)
    assert (d.failure_class, d.source, d.confidence) == (
        FailureClass.needs_interaction,
        DiagnosisSource.llm,
        0.7,
    )
    assert [(e.source, e.quote, e.event_seq) for e in d.evidence] == [
        (EvidenceSource.trace, "Waited for the grid", 3)
    ]
    assert d.failing_step_label == "Waited for the grid"
    call = claude.calls_for(LlmDiagnosis)[0]
    assert "untrusted data" in call["system"]
    assert '"rule_guess"' in call["user"] and '"misread_page"' in call["user"]


async def test_claude_answer_is_sanitized():
    claude = FakeClaude(
        {LlmDiagnosis: [_llm(confidence=7.0, failing_step_seq=99, evidence_quotes=["nope"])]}
    )
    d = await _diagnose(_attempt(tf_status="COMPLETED", result=None), VAGUE_TRACE, claude)
    assert d.confidence == 1.0
    assert d.failing_step_seq == 4  # rule's step: the complete event
    assert d.evidence[0].source is EvidenceSource.verifier  # rule evidence, not the fake quote


async def test_claude_failure_falls_back_to_the_rule():
    claude = FakeClaude({LlmDiagnosis: [ParseOutcome(None, "refusal", "refusal")]})
    d = await _diagnose(_attempt(tf_status="COMPLETED", result=None), VAGUE_TRACE, claude)
    assert (d.failure_class, d.source) == (
        FailureClass.misread_page,
        DiagnosisSource.rules_fallback,
    )
    assert d.explanation.endswith("(automatic diagnosis unavailable: refusal)")


async def test_no_claude_and_no_rule_uses_the_default_class():
    attempt = _attempt(tf_status="FAILED", tf_error={"code": "TASK_FAILED", "message": "x"})
    d = await _diagnose(attempt, VAGUE_TRACE, None)
    assert (d.failure_class, d.source, d.confidence) == (
        FailureClass.misread_page,
        DiagnosisSource.rules_fallback,
        0.4,
    )
    assert "automatic diagnosis unavailable" not in d.explanation
    assert d.evidence


async def test_unrecoverable_class_from_claude_stops_the_run():
    claude = FakeClaude({LlmDiagnosis: [_llm(failure_class=FailureClass.captcha)]})
    d = await _diagnose(_attempt(tf_status="COMPLETED", result=None), VAGUE_TRACE, claude)
    assert d.recoverable is False
    assert d.patch.stop and "CAPTCHA" in d.patch.stop_reason
