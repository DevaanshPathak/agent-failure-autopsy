"""The ladder end to end, with scripted TinyFish and Claude fakes (no network)."""

import json
from datetime import UTC, datetime

import pytest

from app import db
from app.config import Settings
from app.events import RunEventBus
from app.ladder.controller import LadderController
from app.models import FetchExtraction, Run, Rung, RunMode, RunRequest, RunStatus
from app.patch.planner import STOP_AUTH
from app.tinyfish.client import TinyFishError
from tests.conftest import SAMPLE_RUN
from tests.fakes import SAMPLE_FETCH, FakeClaude, FakeTinyFish, run_record

PRODUCTS = {
    "products": [
        {"name": "Blue Mug", "price": "$12.00"},
        {"name": "Red Kettle", "price": "$39.00"},
        {"name": "Green Teapot", "price": "$24.50"},
    ]
}
NOT_FOUND = FetchExtraction(
    found=False,
    result_json="",
    missing=["products"],
    interaction_hint=(
        "The product grid only says 'Loading products…' behind a cookie notice; "
        "it needs a real browser to load."
    ),
)
SAMPLE_REQUEST = RunRequest(
    url="https://shop.example.com/products",
    goal="List the first 3 products on the page with their name and price.",
    expected={"type": "min_items", "path": "products", "min": 3},
)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr("app.ladder.controller.asyncio.sleep", instant)


def _sse(tf_run_id: str, purposes: list[str], *, status="COMPLETED", result=None) -> list[dict]:
    events = [
        {"type": "STARTED", "run_id": tf_run_id, "timestamp": "2026-11-01T11:00:04Z"},
        {
            "type": "STREAMING_URL",
            "run_id": tf_run_id,
            "streaming_url": f"https://{tf_run_id.replace('_', '-')}.invalid/stream/0",
            "timestamp": "2026-11-01T11:00:06Z",
        },
    ]
    events += [{"type": "PROGRESS", "run_id": tf_run_id, "purpose": p} for p in purposes]
    events.append({"type": "COMPLETE", "run_id": tf_run_id, "status": status, "result": result})
    return events


def _sample_tinyfish() -> FakeTinyFish:
    return FakeTinyFish(
        fetch=[SAMPLE_FETCH],
        streams=[
            _sse(
                "tf_sample_0001",
                [
                    "Navigating to https://shop.example.com/products",
                    "A cookie consent dialog is covering the page",
                    "Looking for the product grid behind the dialog",
                    "Could not read any products; finishing",
                ],
            ),
            _sse(
                "tf_sample_0002",
                [
                    "Navigating to https://shop.example.com/products",
                    "Clicking 'Accept all' on the cookie dialog",
                    "The dialog is closed; the product grid is visible",
                    "Reading the first 3 products",
                    "Extracting names and prices",
                ],
                result=PRODUCTS,
            ),
        ],
        runs={
            "tf_sample_0001": run_record("tf_sample_0001", 4),
            "tf_sample_0002": run_record("tf_sample_0002", 5),
        },
    )


async def _execute(
    tinyfish, claude, request: RunRequest, **run_overrides
) -> tuple[Run, list[dict]]:
    run = Run(
        id="run1",
        created_at=datetime(2026, 11, 1, 11, 0, tzinfo=UTC),
        mode=RunMode.live,
        request=request,
        status=RunStatus.queued,
        max_attempts=run_overrides.pop("max_attempts", 4),
        max_credits=run_overrides.pop("max_credits", 40),
    )
    await db.insert_run(run)
    settings = Settings(_env_file=None, **run_overrides)
    await LadderController(settings, tinyfish, claude, RunEventBus()).execute(run.id)
    return await db.get_run(run.id), await db.list_ui_events(run.id)


def _types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


async def test_reproduces_the_sample_run(temp_db):
    claude = FakeClaude({FetchExtraction: [NOT_FOUND]})
    run, events = await _execute(_sample_tinyfish(), claude, SAMPLE_REQUEST)

    sample = [
        json.loads(line) for line in SAMPLE_RUN.read_text(encoding="utf-8").splitlines() if line
    ]
    assert _types(events) == _types(sample)
    assert [e["seq"] for e in events] == list(range(1, 37))

    diagnoses = [e["diagnosis"] for e in events if e["type"] == "diagnosis"]
    assert [(d["failure_class"], d["failing_step_seq"], d["source"]) for d in diagnoses] == [
        ("needs_interaction", 2, "rules"),
        ("popup_overlay", 4, "rules"),
    ]
    trace_labels = [e["event"]["label"] for e in events if e["type"] == "trace_event"]
    sample_labels = [e["event"]["label"] for e in sample if e["type"] == "trace_event"]
    assert trace_labels == sample_labels

    starts = [e["config"] for e in events if e["type"] == "attempt_started"]
    assert [(c["rung"], c["credit_limit"]) for c in starts] == [
        ("fetch", 0),
        ("agent", 40),
        ("agent", 36),
    ]
    assert starts[1]["patches_applied"] == ["Escalate to Rung 2 · Agent"]

    verdict = events[-1]
    assert (verdict["status"], verdict["credits_used"], verdict["attempts_used"]) == (
        "verified",
        9,
        3,
    )
    assert verdict["baseline_credits_estimate"] == 15
    assert verdict["reason"] == (
        "Verified on attempt 3 (Rung 2 · Agent) after fixing needs_interaction → popup_overlay."
    )
    assert run.status is RunStatus.verified and run.final_result == PRODUCTS
    assert claude.calls_for(FetchExtraction) and len(claude.calls) == 1  # rules decided both


async def test_auth_wall_stops_after_one_attempt(temp_db):
    login = {"results": [], "errors": [{"url": "u", "error": "login_required"}]}
    tinyfish = FakeTinyFish(fetch=[login])
    run, events = await _execute(tinyfish, FakeClaude(), SAMPLE_REQUEST)
    assert run.status is RunStatus.unrecoverable
    assert (len(run.attempts), run.credits_used) == (1, 0)
    assert run.verdict_reason == STOP_AUTH
    assert tinyfish.bodies == []  # never paid for an agent run


async def test_bot_block_at_fetch_skips_the_plain_agent_and_uses_stealth(temp_db):
    blocked = {"results": [], "errors": [{"url": "u", "error": "bot_blocked"}]}
    tinyfish = FakeTinyFish(
        fetch=[blocked],
        streams=[_sse("tf_s", ["Loading", "Reading products"], result=PRODUCTS)],
        runs={"tf_s": run_record("tf_s", 2, proxy=True)},
    )
    run, events = await _execute(tinyfish, FakeClaude(), SAMPLE_REQUEST)
    change = [e for e in events if e["type"] == "rung_change"][1]
    assert (change["from_rung"], change["to_rung"], change["skipped"]) == (
        "fetch",
        "agent_stealth",
        ["agent"],
    )
    assert tinyfish.bodies[0]["browser_profile"] == "stealth"
    assert tinyfish.bodies[0]["proxy_config"] == {"enabled": True, "country_code": "US"}
    assert run.status is RunStatus.verified


async def test_credit_limit_cancel_ends_in_budget_exhausted(temp_db):
    tinyfish = FakeTinyFish(
        streams=[_sse("tf_b", [f"step {i}" for i in range(10)], status="CANCELLED")]
    )
    request = SAMPLE_REQUEST.model_copy(update={"start_rung": Rung.agent})
    run, _ = await _execute(tinyfish, FakeClaude(), request, max_credits=5)
    assert tinyfish.cancelled == ["tf_b"]
    assert run.status is RunStatus.budget_exhausted
    assert run.verdict_reason == "Budget spent: the attempt was cancelled at the credit limit."


async def test_without_claude_rung_one_is_skipped(temp_db):
    tinyfish = FakeTinyFish(streams=[_sse("tf_n", ["Reading"], result=PRODUCTS)])
    run, events = await _execute(tinyfish, None, SAMPLE_REQUEST)
    first_change = next(e for e in events if e["type"] == "rung_change")
    assert (first_change["to_rung"], first_change["skipped"]) == ("agent", ["fetch"])
    assert tinyfish.fetched == []
    assert run.status is RunStatus.verified


async def test_hard_tinyfish_refusal_ends_with_an_error_verdict(temp_db):
    tinyfish = FakeTinyFish(
        streams=[TinyFishError("INSUFFICIENT_CREDITS", "wallet empty", http_status=402)]
    )
    request = SAMPLE_REQUEST.model_copy(update={"start_rung": Rung.agent})
    run, _ = await _execute(tinyfish, FakeClaude(), request)
    assert run.status is RunStatus.error
    assert run.verdict_reason == "TinyFish refused the request: INSUFFICIENT_CREDITS — wallet empty"


async def test_output_schema_without_entitlement_is_retried_without_it(temp_db):
    schema = {
        "type": "object",
        "properties": {"products": {"type": "array", "items": {"type": "string"}}},
    }
    tinyfish = FakeTinyFish(
        streams=[
            TinyFishError(
                "FORBIDDEN", "output_schema provided without the output-schema entitlement"
            ),
            _sse("tf_o", ["Reading"], result=PRODUCTS),
        ]
    )
    request = SAMPLE_REQUEST.model_copy(update={"start_rung": Rung.agent, "output_schema": schema})
    run, _ = await _execute(tinyfish, FakeClaude(), request)
    assert "output_schema" in tinyfish.bodies[0]
    assert "output_schema" not in tinyfish.bodies[1]
    assert run.status is RunStatus.verified and len(run.attempts) == 2


async def test_running_out_of_attempts_is_budget_exhausted(temp_db):
    nothing = lambda tid: _sse(tid, ["Reading the page"], result=None)  # noqa: E731
    tinyfish = FakeTinyFish(streams=[nothing("a"), nothing("b")])
    request = SAMPLE_REQUEST.model_copy(update={"start_rung": Rung.agent})
    run, _ = await _execute(tinyfish, None, request, max_attempts=2)
    assert run.status is RunStatus.budget_exhausted
    assert run.verdict_reason.startswith("Budget spent: 2/2 attempts used")


async def test_low_remaining_credits_stop_before_paying(temp_db):
    tinyfish = FakeTinyFish(streams=[_sse("tf_l", ["a", "b", "c"], result=None)])
    request = SAMPLE_REQUEST.model_copy(update={"start_rung": Rung.agent})
    run, _ = await _execute(tinyfish, None, request, max_credits=5)
    assert len(tinyfish.bodies) == 1  # 3 credits spent, 2 left < AGENT_MIN_CREDITS (3)
    assert run.status is RunStatus.budget_exhausted
    assert "not enough credits left" in run.verdict_reason


async def test_stealth_attempt_warns_when_tinyfish_did_not_apply_the_proxy(temp_db):
    tinyfish = FakeTinyFish(
        streams=[_sse("tf_p", ["Reading"], result=PRODUCTS)],
        runs={"tf_p": run_record("tf_p", 1, proxy=False)},
    )
    request = SAMPLE_REQUEST.model_copy(update={"start_rung": Rung.agent_stealth})
    run, events = await _execute(tinyfish, None, request)
    labels = [e["event"]["label"] for e in events if e["type"] == "trace_event"]
    assert "Warning: TinyFish reports the proxy was not applied" in labels
    assert tinyfish.bodies[0]["browser_profile"] == "stealth"
    assert run.attempts[0].config.proxy_country == "US"


def _comparable(event: dict) -> dict:
    """Drop what legitimately differs between a live run and the fixture (times, ids, raw)."""
    e = {k: v for k, v in event.items() if k not in ("ts", "run_id")}
    if e["type"] == "trace_event":
        ev = e["event"]
        e["event"] = {
            k: ev[k]
            for k in ("seq", "kind", "source", "step_no", "label", "tf_run_id", "attempt_no")
        }
    return e


async def test_sample_run_matches_the_fixture_field_by_field(temp_db):
    claude = FakeClaude({FetchExtraction: [NOT_FOUND]})
    _, events = await _execute(_sample_tinyfish(), claude, SAMPLE_REQUEST)
    sample = [
        json.loads(line) for line in SAMPLE_RUN.read_text(encoding="utf-8").splitlines() if line
    ]
    for got, want in zip(events, sample, strict=True):
        assert _comparable(got) == _comparable(want), want["seq"]
