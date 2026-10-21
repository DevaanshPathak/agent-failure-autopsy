import json

import httpx
import pytest

from app.main import create_app


@pytest.fixture
async def client(temp_db):
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health_reports_status_without_keys(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert set(body) == {"status", "mode", "tinyfish_key", "anthropic_key", "db", "version"}


async def test_sample_stream_sends_every_event_with_its_seq_as_id(client):
    resp = await client.get("/dev/sample-stream", params={"delay_ms": 0})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    ids = [line[4:] for line in resp.text.splitlines() if line.startswith("id: ")]
    data = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
    assert len(data) == 36
    assert ids == [str(e["seq"]) for e in data]
    assert data[-1]["type"] == "verdict"
