from datetime import UTC, datetime
from typing import Any

from app.diagnose.rules import classify
from app.models import (
    Attempt,
    AttemptConfig,
    EvidenceSource,
    FailureClass,
    FetchExtraction,
    Rung,
    RunRequest,
    TraceEvent,
    TraceKind,
    TraceSource,
)
from app.verify.verifier import verify

T0 = datetime(2026, 11, 1, 11, 0, tzinfo=UTC)
MIN3 = {"type": "min_items", "path": "products", "min": 3}


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


def _agent_trace(*purposes: str) -> list[TraceEvent]:
    events = [_ev(1, TraceKind.started), _ev(2, TraceKind.live_view)]
    for i, p in enumerate(purposes, start=1):
        events.append(_ev(2 + i, TraceKind.progress, p, step_no=i))
    events.append(_ev(3 + len(purposes), TraceKind.complete))
    return events


def _classify(
    rung: Rung,
    trace: list[TraceEvent],
    *,
    expected: dict | None = None,
    fetch: dict | None = None,
    extraction: FetchExtraction | None = None,
    **attempt_fields: Any,
):
    cfg = AttemptConfig(
        attempt_no=1,
        rung=rung,
        url="https://x.example",
        goal="g",
        max_duration_seconds=150,
        credit_limit=0 if rung is Rung.fetch else 40,
    )
    attempt = Attempt(attempt_no=1, rung=rung, config=cfg, started_at=T0, **attempt_fields)
    request = RunRequest(url="https://x.example", goal="g", expected=expected)
    vr = verify(attempt, request, trace, fetch)
    return classify(attempt, vr, trace, [], extraction, fetch)


def _fetch(
    text: str | None = None, error: dict | None = None, final_url: str = "https://x.example"
) -> dict:
    results = (
        [{"url": "https://x.example", "final_url": final_url, "text": text}]
        if text is not None
        else []
    )
    return {"results": results, "errors": [error] if error else []}


FETCH_TRACE = [_ev(1, TraceKind.fetch_result), _ev(2, TraceKind.extraction)]
FETCH_ERROR_TRACE = [_ev(1, TraceKind.fetch_error)]


def test_r1_captcha_in_steps():
    trace = _agent_trace("Opened the form", "A reCAPTCHA checkbox blocks the submit button")
    v = _classify(Rung.agent, trace, tf_status="COMPLETED", result=None)
    assert (v.failure_class, v.confidence, v.rule) == (FailureClass.captcha, 0.95, "R1")
    assert v.failing_step_seq == 4


def test_r1_weak_captcha_only_in_fetch_text_defers_to_llm():
    v = _classify(
        Rung.fetch,
        FETCH_TRACE,
        fetch=_fetch("Please verify you are human. Press & hold."),
        tf_status="OK",
        result={"status": "failure", "reason": "no data"},
    )
    assert (v.failure_class, v.confidence) == (FailureClass.captcha, 0.6)
    assert v.evidence[0].source is EvidenceSource.fetch_text


def test_r2_fetch_login_required():
    v = _classify(
        Rung.fetch,
        FETCH_ERROR_TRACE,
        fetch=_fetch(error={"url": "u", "error": "login_required"}),
        tf_status="ERROR",
    )
    assert (v.failure_class, v.confidence, v.rule) == (FailureClass.auth_wall, 0.9, "R2")


def test_r2_login_redirect_in_agent_steps():
    trace = _agent_trace("Navigated to https://github.com/login?return_to=%2Fsettings", "Stopped")
    v = _classify(Rung.agent, trace, tf_status="COMPLETED", result=None)
    assert v.failure_class is FailureClass.auth_wall
    assert v.failing_step_seq == 3


def test_r3_bot_blocked_beats_a_turnstile_word_in_page_text():
    fetch = _fetch(
        "<div class='cf-turnstile'>Just a moment</div>", error={"url": "u", "error": "bot_blocked"}
    )
    v = _classify(Rung.fetch, FETCH_ERROR_TRACE, fetch=fetch, tf_status="ERROR")
    assert (v.failure_class, v.confidence, v.rule) == (FailureClass.bot_block, 0.9, "R3")


def test_r3_throttled_fetch():
    fetch = _fetch(error={"url": "u", "error": "target_http_error", "status": 429})
    v = _classify(Rung.fetch, FETCH_ERROR_TRACE, fetch=fetch, tf_status="ERROR")
    assert v.failure_class is FailureClass.bot_block


def test_r3_site_blocked_run_error():
    v = _classify(
        Rung.agent,
        _agent_trace("Loading"),
        tf_status="FAILED",
        tf_error={"code": "SITE_BLOCKED", "message": "Target site blocked the automation."},
    )
    assert (v.failure_class, v.confidence) == (FailureClass.bot_block, 0.9)


def test_r4_popup_like_the_sample_attempt_2():
    trace = _agent_trace(
        "Navigating to https://shop.example.com/products",
        "A cookie consent dialog is covering the page",
        "Looking for the product grid behind the dialog",
        "Could not read any products; finishing",
    )
    v = _classify(Rung.agent, trace, expected=MIN3, tf_status="COMPLETED", result=None)
    assert (v.failure_class, v.confidence, v.rule) == (FailureClass.popup_overlay, 0.9, "R4")
    assert v.failing_step_seq == 4
    assert v.explanation == (
        "A cookie/consent or popup dialog covered the page at step 2, "
        "so the agent finished without reading the data."
    )
    assert [(e.source, e.quote, e.event_seq) for e in v.evidence] == [
        (EvidenceSource.trace, "A cookie consent dialog is covering the page", 4),
        (EvidenceSource.verifier, "Agent reported COMPLETED but result is null", None),
    ]


def test_r5_popup_text_in_the_result():
    v = _classify(
        Rung.agent,
        _agent_trace("Reading"),
        expected=MIN3,
        tf_status="COMPLETED",
        result={"note": "Please accept all cookies to continue", "products": []},
    )
    assert (v.failure_class, v.confidence, v.rule) == (FailureClass.popup_overlay, 0.8, "R5")


def test_r6_needs_interaction_like_the_sample_attempt_1():
    hint = (
        "The product grid only says 'Loading products…' behind a cookie notice; "
        "it needs a real browser to load."
    )
    v = _classify(
        Rung.fetch,
        FETCH_TRACE,
        expected=MIN3,
        fetch=_fetch("# Products\n\nLoading products…"),
        extraction=FetchExtraction(
            found=False, result_json="", missing=["products"], interaction_hint=hint
        ),
        tf_status="OK",
        result=None,
    )
    assert (v.failure_class, v.confidence, v.rule) == (FailureClass.needs_interaction, 0.9, "R6")
    assert v.failing_step_seq == 2
    assert [(e.source, e.event_seq) for e in v.evidence] == [
        (EvidenceSource.trace, 2),
        (EvidenceSource.verifier, None),
    ]


def test_r6_without_a_hint_is_less_confident():
    v = _classify(Rung.fetch, FETCH_TRACE, fetch=_fetch("text"), tf_status="OK", result=None)
    assert (v.failure_class, v.confidence) == (FailureClass.needs_interaction, 0.8)


def test_r7_misread_page():
    v = _classify(
        Rung.agent,
        _agent_trace("Reading the availability"),
        expected={"type": "regex", "value": r"\b22\b"},
        tf_status="COMPLETED",
        result={"copies": "In stock"},
    )
    assert (v.failure_class, v.confidence, v.rule) == (FailureClass.misread_page, 0.85, "R7")
    assert "no match" in v.explanation


def test_r8_null_result_without_popup_cue_defers_to_llm():
    v = _classify(Rung.agent, _agent_trace("Reading"), tf_status="COMPLETED", result=None)
    assert (v.failure_class, v.confidence, v.rule) == (FailureClass.misread_page, 0.5, "R8")


def test_r9_unclassified_failure():
    v = _classify(
        Rung.agent,
        _agent_trace("Navigating"),
        tf_status="FAILED",
        tf_error={"code": "TASK_FAILED", "message": "navigation failed"},
    )
    assert (v.failure_class, v.confidence, v.rule) == (None, 0.0, "R9")
    assert v.evidence and v.failing_step_seq == 4
