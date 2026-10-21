import json
import shutil

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.models import RunStatus
from tests.conftest import SAMPLE_RUN

REPLAY_BODY = {
    "url": "https://shop.example.com/products",
    "goal": "List the first 3 products on the page with their name and price.",
    "site_id": "sample",
    "mode": "replay",
}


@pytest.fixture
def fixtures(tmp_path):
    (tmp_path / "traces").mkdir()
    shutil.copy(SAMPLE_RUN, tmp_path / "traces" / "sample.jsonl")
    return tmp_path


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr("app.replay.player.asyncio.sleep", instant)


def _events(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


async def _replay(fixtures, body=REPLAY_BODY, **settings):
    app = create_app(Settings(_env_file=None, fixtures_dir=fixtures, **settings), tinyfish=None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        created = await c.post("/runs", json=body)
        assert created.status_code == 201, created.text
        run_id = created.json()["run_id"]
        stream = await c.get(f"/runs/{run_id}/stream")
        run = (await c.get(f"/runs/{run_id}")).json()
    return run_id, _events(stream.text), run


async def test_replay_re_emits_the_recorded_run_without_a_tinyfish_key(temp_db, fixtures):
    run_id, events, run = await _replay(fixtures)
    sample = [
        json.loads(line) for line in SAMPLE_RUN.read_text(encoding="utf-8").splitlines() if line
    ]
    assert len(events) == 36
    assert [e["type"] for e in events] == [e["type"] for e in sample]
    assert {e["run_id"] for e in events} == {run_id}
    assert all(e["event"]["run_id"] == run_id for e in events if e["type"] == "trace_event")
    assert [e["seq"] for e in events] == list(range(1, 37))

    assert run["mode"] == "replay"
    assert run["status"] == RunStatus.verified
    assert (len(run["attempts"]), run["credits_used"], run["baseline_credits_estimate"]) == (
        3,
        9,
        15,
    )
    assert [a["rung"] for a in run["attempts"]] == ["fetch", "agent", "agent"]
    assert run["attempts"][1]["diagnosis"]["failure_class"] == "popup_overlay"
    assert run["attempts"][1]["num_of_steps"] == 4
    assert run["final_result"]["products"][0]["name"] == "Blue Mug"


async def test_mode_replay_is_the_default_when_configured(temp_db, fixtures):
    body = {k: v for k, v in REPLAY_BODY.items() if k != "mode"}
    _, events, run = await _replay(fixtures, body, mode="replay")
    assert run["mode"] == "replay" and events[-1]["type"] == "verdict"


async def test_a_trace_without_a_verdict_ends_with_an_error_verdict(temp_db, fixtures):
    lines = SAMPLE_RUN.read_text(encoding="utf-8").splitlines()[:10]
    (fixtures / "traces" / "sample.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _, events, run = await _replay(fixtures)
    assert events[-1]["type"] == "verdict" and events[-1]["status"] == "error"
    assert run["status"] == "error"
