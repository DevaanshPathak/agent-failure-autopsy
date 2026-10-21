from datetime import UTC, datetime
from typing import Any

import pytest

from app.models import (
    Attempt,
    AttemptConfig,
    BlockSignalKind,
    CheckName,
    Rung,
    RunRequest,
    SignalWhere,
    TraceEvent,
    TraceKind,
    TraceSource,
)
from app.verify.verifier import all_empty, get_path, to_json_schema, verify

T0 = datetime(2026, 11, 1, 11, 0, tzinfo=UTC)
PRODUCTS = {
    "products": [
        {"name": "Blue Mug", "price": "$12.00"},
        {"name": "Red Kettle", "price": "$39.00"},
        {"name": "Green Teapot", "price": "$24.50"},
    ]
}


def _attempt(rung: Rung = Rung.agent, *, schema: dict | None = None, **fields: Any) -> Attempt:
    cfg = AttemptConfig(
        attempt_no=2,
        rung=rung,
        url="https://shop.example.com/products",
        goal="List the first 3 products",
        output_schema=schema,
        max_duration_seconds=150,
        credit_limit=0 if rung is Rung.fetch else 40,
    )
    return Attempt(attempt_no=2, rung=rung, config=cfg, started_at=T0, **fields)


def _ev(seq: int, kind: TraceKind, label: str = "", **raw: Any) -> TraceEvent:
    return TraceEvent(
        run_id="r",
        attempt_no=2,
        seq=seq,
        kind=kind,
        source=TraceSource.tinyfish_sse,
        ts=T0,
        label=label or kind.value,
        raw=raw,
    )


def _req(expected: dict | None = None) -> RunRequest:
    return RunRequest(url="https://shop.example.com/products", goal="g", expected=expected)


MIN3 = {"type": "min_items", "path": "products", "min": 3}
TRACE = [
    _ev(1, TraceKind.started),
    _ev(3, TraceKind.progress, "A cookie consent dialog is covering the page"),
    _ev(7, TraceKind.complete),
]


def _check(vr, name: CheckName):
    return next(c for c in vr.checks if c.name is name)


def test_completed_with_null_result_is_rejected_like_the_sample():
    vr = verify(_attempt(tf_status="COMPLETED", result=None), _req(MIN3), TRACE, None)
    assert not vr.passed
    assert [c.name for c in vr.checks] == [
        CheckName.tinyfish_status,
        CheckName.result_present,
        CheckName.no_block_page,
    ]
    assert vr.summary == "Rejected: Agent reported COMPLETED but result is null"
    null_signal = next(
        s for s in vr.block_signals if s.kind is BlockSignalKind.null_result_completed
    )
    assert (null_signal.where, null_signal.event_seq) == (SignalWhere.result, 7)
    assert _check(vr, CheckName.no_block_page).passed


def test_good_result_is_verified_with_the_expected_detail():
    vr = verify(_attempt(tf_status="COMPLETED", result=PRODUCTS), _req(MIN3), TRACE, None)
    assert vr.passed
    assert vr.summary == "Verified: products has 3 items (≥ 3)"
    assert [c.name for c in vr.checks] == [
        CheckName.tinyfish_status,
        CheckName.result_present,
        CheckName.self_reported_failure,
        CheckName.expected,
        CheckName.not_all_null,
        CheckName.no_block_page,
    ]
    assert _check(vr, CheckName.result_present).detail == "result has 1 key"


def test_failed_status_is_rejected_with_the_error():
    att = _attempt(
        tf_status="FAILED", tf_error={"code": "TASK_FAILED", "message": "Could not navigate"}
    )
    vr = verify(att, _req(), TRACE, None)
    assert _check(vr, CheckName.tinyfish_status).detail == "FAILED TASK_FAILED Could not navigate"
    assert not vr.passed


@pytest.mark.parametrize(
    "result",
    [
        {"status": "failure", "reason": "Could not find any products on the page"},
        {"error": "blocked"},
        {"reason": "nothing found"},
    ],
)
def test_self_reported_failure(result):
    vr = verify(_attempt(tf_status="COMPLETED", result=result), _req(), TRACE, None)
    check = _check(vr, CheckName.self_reported_failure)
    assert not check.passed
    assert check.detail.startswith("result reports failure:")


def test_output_schema_mismatch_and_nullable():
    schema = {
        "type": "object",
        "properties": {
            "price": {"type": "number"},
            "note": {"type": "string", "nullable": True},
        },
        "required": ["price", "note"],
    }
    bad = verify(
        _attempt(tf_status="COMPLETED", result={"price": "$12", "note": None}, schema=schema),
        _req(),
        TRACE,
        None,
    )
    assert "price" in _check(bad, CheckName.output_schema).detail
    good = verify(
        _attempt(tf_status="COMPLETED", result={"price": 12, "note": None}, schema=schema),
        _req(),
        TRACE,
        None,
    )
    assert _check(good, CheckName.output_schema).passed


@pytest.mark.parametrize(
    ("expected", "passed", "detail"),
    [
        ({"type": "contains", "value": "red kettle"}, True, "found 'red kettle'"),
        ({"type": "contains", "value": "Purple"}, False, "'Purple' not in result"),
        ({"type": "regex", "value": r"\$39\.00"}, True, r"matches /\$39\.00/"),
        ({"type": "regex", "value": r"\b22\b"}, False, r"no match for /\b22\b/"),
        ({"type": "fields_present", "fields": ["products.0.name"]}, True, "all 1 fields present"),
        ({"type": "fields_present", "fields": ["products.5.name"]}, False, "missing or empty"),
        (
            {"type": "min_items", "path": "products", "min": 4},
            False,
            "products has 3 items, need 4",
        ),
        ({"type": "min_items", "path": "items", "min": 1}, False, "items not found or not a list"),
    ],
)
def test_expected_checks(expected, passed, detail):
    vr = verify(_attempt(tf_status="COMPLETED", result=PRODUCTS), _req(expected), TRACE, None)
    check = _check(vr, CheckName.expected)
    assert check.passed is passed
    assert check.detail.startswith(detail)


def test_all_empty_result_is_rejected():
    vr = verify(
        _attempt(tf_status="COMPLETED", result={"products": [], "title": None}), _req(), TRACE, None
    )
    assert not _check(vr, CheckName.not_all_null).passed


def test_access_denied_in_result_is_blocking():
    vr = verify(
        _attempt(tf_status="COMPLETED", result={"title": "Access Denied", "body": "Reference #18"}),
        _req(),
        TRACE,
        None,
    )
    assert not vr.passed
    assert _check(vr, CheckName.no_block_page).detail.startswith("access_denied in result")


def test_captcha_in_progress_only_is_evidence_not_blocking():
    trace = [*TRACE, _ev(4, TraceKind.progress, "Solving the captcha on the page")]
    vr = verify(_attempt(tf_status="COMPLETED", result=PRODUCTS), _req(MIN3), trace, None)
    assert vr.passed
    signal = next(s for s in vr.block_signals if s.kind is BlockSignalKind.captcha)
    assert (signal.where, signal.event_seq) == (SignalWhere.progress, 4)


def test_site_blocked_and_profile_hint_are_blocking():
    att = _attempt(
        tf_status="FAILED",
        tf_error={
            "code": "SITE_BLOCKED",
            "message": "blocked",
            "profile_hint_reason": "bot_challenge",
        },
    )
    vr = verify(att, _req(), TRACE, None)
    kinds = {s.kind for s in vr.block_signals}
    assert {BlockSignalKind.site_blocked_error, BlockSignalKind.profile_hint_bot_challenge} <= kinds


def _fetch(text: str | None = None, error: dict | None = None) -> dict:
    results = (
        [{"url": "u", "final_url": "u", "title": "t", "text": text}] if text is not None else []
    )
    return {"results": results, "errors": [error] if error else []}


def test_fetch_attempt_with_no_extraction_like_the_sample():
    trace = [_ev(1, TraceKind.fetch_result), _ev(2, TraceKind.extraction)]
    fetch = _fetch("# Products\n\nWe use cookies. [Accept all]\n\nLoading products…")
    vr = verify(_attempt(Rung.fetch, tf_status="OK", result=None), _req(MIN3), trace, fetch)
    assert [(c.name, c.passed, c.detail) for c in vr.checks] == [
        (CheckName.tinyfish_status, True, "Fetch returned 1 page"),
        (CheckName.result_present, False, "Extractor found no data in the Fetch text"),
        (CheckName.no_block_page, True, "no blocking page detected"),
    ]
    assert vr.block_signals == []


def test_fetch_bot_blocked_error_is_blocking():
    trace = [_ev(1, TraceKind.fetch_error)]
    fetch = _fetch(error={"url": "u", "error": "bot_blocked"})
    vr = verify(_attempt(Rung.fetch, tf_status="ERROR"), _req(), trace, fetch)
    assert _check(vr, CheckName.tinyfish_status).detail == "Fetch error: bot_blocked"
    signal = next(s for s in vr.block_signals if s.kind is BlockSignalKind.fetch_bot_blocked)
    assert (signal.where, signal.event_seq) == (SignalWhere.fetch_error, 1)


def test_fetch_403_and_login_required():
    forbidden = verify(
        _attempt(Rung.fetch, tf_status="ERROR"),
        _req(),
        [],
        _fetch(error={"url": "u", "error": "target_http_error", "status": 403}),
    )
    assert any(s.kind is BlockSignalKind.http_403 for s in forbidden.block_signals)
    login = verify(
        _attempt(Rung.fetch, tf_status="ERROR"),
        _req(),
        [],
        _fetch(error={"url": "u", "error": "login_required"}),
    )
    assert any(s.kind is BlockSignalKind.fetch_login_required for s in login.block_signals)


def test_benign_recaptcha_footer_is_not_a_captcha_signal():
    fetch = _fetch("Contact us. This site is protected by reCAPTCHA and the Google Privacy Policy.")
    vr = verify(_attempt(Rung.fetch, tf_status="OK", result={"answer": "x"}), _req(), [], fetch)
    assert not any(s.kind is BlockSignalKind.captcha for s in vr.block_signals)


def test_real_captcha_in_fetch_text_is_a_weak_signal():
    fetch = _fetch("Please verify you are human. Press & hold the button.")
    vr = verify(_attempt(Rung.fetch, tf_status="OK", result=None), _req(), [], fetch)
    signal = next(s for s in vr.block_signals if s.kind is BlockSignalKind.captcha)
    assert signal.where is SignalWhere.fetch_text


def test_helpers():
    assert get_path(PRODUCTS, "products.1.name") == (True, "Red Kettle")
    assert get_path(PRODUCTS, "products.9") == (False, None)
    assert all_empty({"a": [], "b": {"c": None}, "d": " "})
    assert not all_empty({"a": [0]})
    assert to_json_schema({"type": "string", "nullable": True, "enum": ["a"]}) == {
        "type": ["string", "null"],
        "enum": ["a", None],
    }
