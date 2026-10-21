import json

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.tinyfish.client import TinyFishError
from tests.fakes import FakeTinyFish, run_record, sse_run

PRODUCTS = {
    "products": [{"name": "Blue Mug", "price": "$12.00"}, {"name": "Red Kettle", "price": "$39.00"}]
}
BODY = {
    "url": "https://shop.example.com/products",
    "goal": "List the first 2 products",
    "expected": {"type": "min_items", "path": "products", "min": 2},
    "start_rung": "agent",
}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr("app.ladder.controller.asyncio.sleep", instant)


async def _client(temp_db, **app_kwargs):
    settings = app_kwargs.pop("settings", None) or _settings()
    transport = httpx.ASGITransport(app=create_app(settings, **app_kwargs))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _events(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


async def _run_and_stream(client: httpx.AsyncClient, body: dict) -> tuple[str, list[dict]]:
    created = await client.post("/runs", json=body)
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    stream = await client.get(f"/runs/{run_id}/stream")
    return run_id, _events(stream.text)


async def test_health_reports_status_without_keys(temp_db):
    async with await _client(temp_db) as client:
        body = (await client.get("/health")).json()
    assert body["status"] == "ok" and body["db"] == "ok"
    assert set(body) == {"status", "mode", "tinyfish_key", "anthropic_key", "db", "version"}


async def test_sample_stream_sends_every_event_with_its_seq_as_id(temp_db):
    async with await _client(temp_db) as client:
        resp = await client.get("/dev/sample-stream", params={"delay_ms": 0})
    assert resp.headers["content-type"].startswith("text/event-stream")
    ids = [line[4:] for line in resp.text.splitlines() if line.startswith("id: ")]
    data = _events(resp.text)
    assert len(data) == 36
    assert ids == [str(e["seq"]) for e in data]


async def test_create_run_without_tinyfish_key_is_503(temp_db):
    async with await _client(temp_db, tinyfish=None) as client:
        resp = await client.post("/runs", json=BODY)
    assert resp.status_code == 503
    assert "TINYFISH_API_KEY" in resp.json()["detail"]


async def test_replay_mode_is_not_built_yet(temp_db):
    async with await _client(temp_db, tinyfish=FakeTinyFish()) as client:
        resp = await client.post("/runs", json={**BODY, "mode": "replay"})
    assert resp.status_code == 501


async def test_invalid_request_is_422(temp_db):
    async with await _client(temp_db, tinyfish=FakeTinyFish()) as client:
        resp = await client.post("/runs", json={**BODY, "url": "ftp://x"})
    assert resp.status_code == 422


async def test_live_agent_run_streams_and_is_verified(temp_db):
    fake = FakeTinyFish(
        streams=[sse_run("tf_1", ["Navigating", "Reading products"], result=PRODUCTS)],
        runs={"tf_1": run_record("tf_1", 2)},
    )
    async with await _client(temp_db, tinyfish=fake) as client:
        run_id, events = await _run_and_stream(client, BODY)
        run = (await client.get(f"/runs/{run_id}")).json()

    types = [e["type"] for e in events]
    assert types[:3] == ["budget", "rung_change", "attempt_started"]
    assert types[-3:] == ["budget", "verify", "verdict"]
    assert "live_view" in types
    kinds = [e["event"]["kind"] for e in events if e["type"] == "trace_event"]
    assert kinds == ["started", "live_view", "progress", "progress", "complete", "run_snapshot"]
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert events[-1]["status"] == "verified"
    assert run["status"] == "verified"
    assert run["credits_used"] == 2
    assert run["attempts"][0]["tf_run_id"] == "tf_1"
    assert fake.bodies[0]["browser_profile"] == "lite"


async def test_stream_resumes_after_last_event_id(temp_db):
    fake = FakeTinyFish(
        streams=[sse_run("tf_1", ["a"], result=PRODUCTS)], runs={"tf_1": run_record("tf_1", 1)}
    )
    async with await _client(temp_db, tinyfish=fake) as client:
        run_id, events = await _run_and_stream(client, BODY)
        resumed = await client.get(f"/runs/{run_id}/stream", headers={"Last-Event-ID": "5"})
        via_query = await client.get(f"/runs/{run_id}/stream", params={"after": len(events) - 1})
    assert [e["seq"] for e in _events(resumed.text)] == list(range(6, len(events) + 1))
    assert [e["type"] for e in _events(via_query.text)] == ["verdict"]


async def test_completed_with_null_result_is_rejected(temp_db):
    fake = FakeTinyFish(streams=[sse_run("tf_1", ["A cookie dialog covers the page"], result=None)])
    async with await _client(temp_db, tinyfish=fake) as client:
        _, events = await _run_and_stream(client, BODY)
    verify = next(e for e in events if e["type"] == "verify")
    assert verify["result"]["summary"] == "Rejected: Agent reported COMPLETED but result is null"
    assert events[-1]["type"] == "verdict" and events[-1]["status"] != "verified"


async def test_credit_limit_cancels_the_tinyfish_run(temp_db):
    fake = FakeTinyFish(
        streams=[sse_run("tf_1", [f"step {i}" for i in range(10)], status="CANCELLED")]
    )
    async with await _client(temp_db, tinyfish=fake) as client:
        run_id, events = await _run_and_stream(client, {**BODY, "max_credits": 3})
        run = (await client.get(f"/runs/{run_id}")).json()
    assert fake.cancelled == ["tf_1"]
    labels = [e["event"]["label"] for e in events if e["type"] == "trace_event"]
    assert "Cancelled at the credit limit (3)" in labels
    assert run["attempts"][0]["outcome"] == "cancelled_budget"


async def test_rate_limited_start_is_retried_once(temp_db):
    fake = FakeTinyFish(
        streams=[
            TinyFishError("RATE_LIMIT_EXCEEDED", "slow down", http_status=429),
            sse_run("tf_2", ["a"], result=PRODUCTS),
        ],
        runs={"tf_2": run_record("tf_2", 1)},
    )
    async with await _client(temp_db, tinyfish=fake) as client:
        _, events = await _run_and_stream(client, BODY)
    assert len(fake.bodies) == 2
    assert events[-1]["status"] == "verified"


async def test_dropped_stream_recovers_by_polling(temp_db):
    dropped = sse_run("tf_3", ["a", "b"], result=PRODUCTS)[:-1]  # no COMPLETE
    fake = FakeTinyFish(
        streams=[dropped],
        polls={
            "tf_3": [
                {"run_id": "tf_3", "status": "RUNNING"},
                {"run_id": "tf_3", "status": "COMPLETED", "result": PRODUCTS},
            ]
        },
        runs={"tf_3": run_record("tf_3", 2)},
    )
    async with await _client(temp_db, tinyfish=fake) as client:
        _, events = await _run_and_stream(client, BODY)
    traces = [e["event"] for e in events if e["type"] == "trace_event"]
    assert any(t["label"] == "Stream dropped — polling the run status" for t in traces)
    assert any(t["kind"] == "complete" and t["source"] == "tinyfish_runs" for t in traces)
    assert events[-1]["status"] == "verified"


async def test_refused_run_ends_without_a_result(temp_db):
    fake = FakeTinyFish(
        streams=[TinyFishError("INSUFFICIENT_CREDITS", "wallet empty", http_status=402)]
    )
    async with await _client(temp_db, tinyfish=fake) as client:
        run_id, events = await _run_and_stream(client, BODY)
        run = (await client.get(f"/runs/{run_id}")).json()
    assert run["attempts"][0]["outcome"] == "error"
    assert run["attempts"][0]["tf_error"]["code"] == "INSUFFICIENT_CREDITS"
    assert events[-1]["type"] == "verdict"


async def test_sites_skip_template_entries_and_report_traces(temp_db, tmp_path):
    (tmp_path / "traces").mkdir()
    (tmp_path / "traces" / "books-22.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "sites.yaml").write_text(
        "sites:\n"
        "  - id: TODO-captcha\n    url: TODO\n    goal: TODO\n"
        "  - id: books-22\n    url: https://books.toscrape.com/x\n    goal: How many copies?\n"
        "    expected: {type: regex, value: '\\b22\\b'}\n    expected_class: misread_page\n",
        encoding="utf-8",
    )
    async with await _client(temp_db, settings=_settings(fixtures_dir=tmp_path)) as client:
        sites = (await client.get("/sites")).json()
    assert [(s["id"], s["has_trace"], s["expected_class"]) for s in sites] == [
        ("books-22", True, "misread_page")
    ]


async def test_unknown_run_is_404(temp_db):
    async with await _client(temp_db) as client:
        assert (await client.get("/runs/nope")).status_code == 404
        assert (await client.get("/runs/nope/stream")).status_code == 404
