from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.models import AttemptConfig, BrowserProfile, Rung, TraceKind, TraceSource
from app.tinyfish.client import (
    TinyFishClient,
    TinyFishError,
    build_agent_body,
    map_sse_event,
    normalize_tf_error,
    ui_copy,
)

AGENT = "https://agent.tinyfish.ai"
FETCH = "https://api.fetch.tinyfish.ai"
NOW = datetime(2026, 11, 1, 11, 0, tzinfo=UTC)


@pytest.fixture
async def client():
    c = TinyFishClient("test-key", AGENT, FETCH)
    yield c
    await c.aclose()


def _cfg(**overrides) -> AttemptConfig:
    base = dict(
        attempt_no=2,
        rung=Rung.agent,
        url="https://shop.example.com/products",
        goal="List the first 3 products",
        max_duration_seconds=150,
        credit_limit=40,
    )
    return AttemptConfig(**{**base, **overrides})


# --- HTTP ----------------------------------------------------------------------------------------


@respx.mock
async def test_agent_stream_parses_data_lines_and_skips_the_rest(client):
    body = (
        b": keep-alive comment\n\n"
        b'data: {"type":"STARTED","run_id":"r1","timestamp":"t0"}\n\n'
        b"event: message\n"
        b'data: {"type":"PROGRESS","run_id":"r1","purpose":"Clicking","timestamp":"t1"}\n\n'
        b"data: not-json\n\n"
        b'data: {"type":"COMPLETE","run_id":"r1","status":"COMPLETED","result":null}\n\n'
    )
    route = respx.post(f"{AGENT}/v1/automation/run-sse").mock(
        return_value=httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )
    )
    events = [e async for e in client.agent_stream({"url": "u", "goal": "g"})]
    assert [e["type"] for e in events] == ["STARTED", "PROGRESS", "_UNPARSEABLE", "COMPLETE"]
    sent = route.calls.last.request
    assert sent.headers["x-api-key"] == "test-key"
    assert sent.headers["accept"] == "text/event-stream"


@respx.mock
async def test_agent_stream_raises_before_yielding_on_http_error(client):
    respx.post(f"{AGENT}/v1/automation/run-sse").mock(
        return_value=httpx.Response(
            402,
            json={
                "error": {"code": "insufficient_credits", "message": "wallet empty"},
                "request_id": "req-1",
            },
        )
    )
    with pytest.raises(TinyFishError) as exc:
        async for _ in client.agent_stream({"url": "u", "goal": "g"}):
            pytest.fail("must not yield")
    assert exc.value.code == "INSUFFICIENT_CREDITS"
    assert exc.value.http_status == 402
    assert exc.value.request_id == "req-1"


@respx.mock
async def test_fetch_retries_once_on_429(client, monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("app.tinyfish.client.asyncio.sleep", fake_sleep)
    ok = {"results": [{"url": "u", "text": "# Hi"}], "errors": []}
    route = respx.post(FETCH).mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "1"}),
            httpx.Response(200, json=ok),
        ]
    )
    assert await client.fetch("https://example.com") == ok
    assert route.call_count == 2
    assert sleeps == [1.0]
    assert (
        route.calls.last.request.content == b'{"urls":["https://example.com"],"format":"markdown"}'
    )


@respx.mock
async def test_fetch_error_without_json_body(client):
    respx.post(FETCH).mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(TinyFishError) as exc:
        await client.fetch("https://example.com")
    assert exc.value.code == "HTTP_500"
    assert exc.value.message == "boom"


@respx.mock
async def test_get_run_cancel_and_screenshot(client):
    respx.get(f"{AGENT}/v1/runs/r1").mock(return_value=httpx.Response(200, json={"run_id": "r1"}))
    respx.post(f"{AGENT}/v1/runs/r1/cancel").mock(
        return_value=httpx.Response(200, json={"status": "CANCELLED"})
    )
    respx.get(f"{AGENT}/v1/runs/r1/steps/s1/screenshot").mock(
        return_value=httpx.Response(200, content=b"\xff\xd8jpeg")
    )
    assert (await client.get_run("r1"))["run_id"] == "r1"
    assert (await client.cancel("r1"))["status"] == "CANCELLED"
    assert await client.step_screenshot("r1", "s1") == b"\xff\xd8jpeg"


# --- build_agent_body ----------------------------------------------------------------------------


def test_lite_body_has_no_proxy_and_no_gated_fields():
    body = build_agent_body(_cfg())
    assert body == {
        "url": "https://shop.example.com/products",
        "goal": "List the first 3 products",
        "browser_profile": "lite",
        "agent_config": {"max_duration_seconds": 150},
    }


def test_stealth_body_sends_stealth_and_proxy_only_enabled_and_country():
    cfg = _cfg(
        rung=Rung.agent_stealth,
        browser_profile=BrowserProfile.stealth,
        proxy_enabled=True,
        proxy_country="US",
        output_schema={"type": "object", "properties": {"a": {"type": "string"}}},
    )
    body = build_agent_body(cfg)
    assert body["browser_profile"] == "stealth"
    assert body["proxy_config"] == {"enabled": True, "country_code": "US"}
    assert body["output_schema"]["type"] == "object"
    assert "max_steps" not in body["agent_config"] and "mode" not in body["agent_config"]
    assert "capture_config" not in body


# --- map_sse_event -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "kind", "label"),
    [
        ({"type": "STARTED", "run_id": "r1", "timestamp": "t"}, TraceKind.started, "Agent started"),
        (
            {"type": "STREAMING_URL", "streaming_url": "https://x"},
            TraceKind.live_view,
            "Live view ready",
        ),
        (
            {"type": "PROGRESS", "purpose": " Clicking submit "},
            TraceKind.progress,
            "Clicking submit",
        ),
        ({"type": "PROGRESS"}, TraceKind.progress, "(no purpose)"),
        ({"type": "HEARTBEAT", "timestamp": "t"}, TraceKind.heartbeat, "heartbeat"),
        ({"type": "COMPLETE", "status": "FAILED"}, TraceKind.complete, "Agent finished: FAILED"),
        (
            {"type": "TF_API_RESULT", "tinyfish_api": "fetch"},
            TraceKind.tf_api_result,
            "Agent used TinyFish fetch",
        ),
        ({"type": "_UNPARSEABLE", "line": "x"}, TraceKind.unknown, "Unparseable stream line"),
        ({"type": "SOMETHING_NEW"}, TraceKind.unknown, "Unknown event SOMETHING_NEW"),
    ],
)
def test_map_sse_event(raw, kind, label):
    ev = map_sse_event(raw, run_id="run", attempt_no=2, seq=5, step_no=3, now=NOW)
    assert (ev.kind, ev.label, ev.source) == (kind, label, TraceSource.tinyfish_sse)
    assert ev.raw == raw
    assert ev.step_no == (3 if kind is TraceKind.progress else None)


def test_map_sse_event_keeps_tinyfish_ids():
    ev = map_sse_event(
        {"type": "STARTED", "run_id": "tf_1", "timestamp": "2026-11-01T11:00:04Z"},
        run_id="run",
        attempt_no=1,
        seq=1,
        step_no=None,
        now=NOW,
    )
    assert (ev.tf_run_id, ev.tf_timestamp) == ("tf_1", "2026-11-01T11:00:04Z")


# --- normalize_tf_error --------------------------------------------------------------------------


def test_normalize_string_error_with_top_level_help():
    err = normalize_tf_error(
        {"type": "COMPLETE", "error": "Site blocked", "help_url": "h", "help_message": "m"}
    )
    assert err["message"] == "Site blocked"
    assert err["code"] is None
    assert (err["help_url"], err["help_message"]) == ("h", "m")


def test_normalize_object_error_uppercases_code_and_reads_nested_hint():
    err = normalize_tf_error(
        {
            "status": "FAILED",
            "error": {
                "code": "site_blocked",
                "message": "Target site blocked the automation.",
                "category": "AGENT_FAILURE",
                "retry_after": None,
                "profile_hint": {"message": "m", "setup_url": "/s", "reason": "bot_challenge"},
            },
        }
    )
    assert err["code"] == "SITE_BLOCKED"
    assert err["category"] == "AGENT_FAILURE"
    assert err["profile_hint_reason"] == "bot_challenge"


def test_normalize_top_level_profile_hint_and_no_error():
    assert normalize_tf_error({"status": "COMPLETED", "result": {"a": 1}}) is None
    err = normalize_tf_error({"profile_hint": {"reason": "auth_wall"}})
    assert err["profile_hint_reason"] == "auth_wall"


# --- ui_copy -------------------------------------------------------------------------------------


def test_ui_copy_truncates_long_strings_without_touching_the_original():
    long_text = "x" * 2500
    ev = map_sse_event(
        {"type": "COMPLETE", "result": {"text": long_text, "items": [long_text]}},
        run_id="run",
        attempt_no=1,
        seq=1,
        step_no=None,
        now=NOW,
    )
    copy = ui_copy(ev)
    assert copy.raw["result"]["text"].endswith("…[truncated 500 chars]")
    assert len(copy.raw["result"]["items"][0]) < 2100
    assert ev.raw["result"]["text"] == long_text
