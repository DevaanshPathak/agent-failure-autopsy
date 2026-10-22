from datetime import UTC, datetime

from app.config import Settings
from app.events import Emitter, RunEventBus
from app.extract.fetch_extract import build_user_message, extract_from_fetch
from app.ladder.controller import LadderController, RunState
from app.llm.claude import ParseOutcome
from app.models import FetchExtraction, Run, Rung, RunMode, RunRequest, RunStatus, TraceKind
from tests.fakes import SAMPLE_FETCH, SAMPLE_PAGE, FakeClaude, FakeTinyFish

NOT_FOUND = FetchExtraction(
    found=False,
    result_json="",
    missing=["products"],
    interaction_hint="The product grid only says 'Loading products…'; it needs a real browser.",
)
FOUND = FetchExtraction(
    found=True, result_json='{"title": "Acme"}', missing=[], interaction_hint=""
)


def test_user_message_marks_truncation_explicitly():
    page = {**SAMPLE_PAGE, "text": "x" * 120}
    msg = build_user_message(goal="g", output_schema=None, expected=None, page=page, max_chars=100)
    assert "[truncated: 20 chars omitted]" in msg
    assert "<<<PAGE" in msg and "PAGE>>>" in msg
    assert "OUTPUT SCHEMA: none" in msg


async def test_extract_found_not_found_and_errors():
    kw = dict(goal="g", output_schema=None, expected=None, page=SAMPLE_PAGE, max_chars=1000)
    result, extraction, err = await extract_from_fetch(FakeClaude({FetchExtraction: [FOUND]}), **kw)
    assert (result, err) == ({"title": "Acme"}, None)

    result, extraction, err = await extract_from_fetch(
        FakeClaude({FetchExtraction: [NOT_FOUND]}), **kw
    )
    assert result is None and extraction is NOT_FOUND and err is None

    bad = FetchExtraction(found=True, result_json="[1, 2]", missing=[], interaction_hint="")
    result, _, err = await extract_from_fetch(FakeClaude({FetchExtraction: [bad]}), **kw)
    assert result is None and err == "result_json was not a JSON object"

    refused = ParseOutcome(None, "refusal", "refusal")
    result, extraction, err = await extract_from_fetch(
        FakeClaude({FetchExtraction: [refused]}), **kw
    )
    assert (result, extraction, err) == (None, None, "refusal")


def _state(controller: LadderController) -> RunState:
    run = Run(
        id="r1",
        created_at=datetime(2026, 11, 1, 11, 0, tzinfo=UTC),
        mode=RunMode.live,
        request=RunRequest(url="https://shop.example.com/products", goal="List products"),
        status=RunStatus.running,
        max_attempts=4,
        max_credits=40,
    )
    return RunState(run=run, em=Emitter("r1", controller.bus), rung=Rung.fetch, schema=None)


def _controller(tinyfish, claude) -> LadderController:
    return LadderController(Settings(_env_file=None), tinyfish, claude, RunEventBus())


async def test_fetch_attempt_labels_match_the_sample(temp_db):
    ctrl = _controller(
        FakeTinyFish(fetch=[SAMPLE_FETCH]), FakeClaude({FetchExtraction: [NOT_FOUND]})
    )
    st = _state(ctrl)
    attempt, trace, fetch_used = await ctrl.run_fetch_attempt(st, ctrl.build_config(st, 1))
    assert [(e.kind, e.label) for e in trace] == [
        (
            TraceKind.fetch_result,
            "Fetched https://shop.example.com/products (Acme Shop — Products)",
        ),
        (TraceKind.extraction, "Extractor: products not in the page text"),
    ]
    assert (attempt.tf_status, attempt.result, attempt.credits_estimated) == ("OK", None, 0)
    assert fetch_used is SAMPLE_FETCH and st.extraction is NOT_FOUND
    assert st.fetch_text.endswith("Loading products…")


async def test_cached_fetch_attempt_makes_no_tinyfish_call(temp_db):
    tinyfish = FakeTinyFish(fetch=[SAMPLE_FETCH])
    ctrl = _controller(tinyfish, FakeClaude({FetchExtraction: [NOT_FOUND, FOUND]}))
    st = _state(ctrl)
    await ctrl.run_fetch_attempt(st, ctrl.build_config(st, 1))
    st.from_fetch_cache = True
    attempt, trace, _ = await ctrl.run_fetch_attempt(st, ctrl.build_config(st, 2))
    assert tinyfish.fetched == ["https://shop.example.com/products"]
    assert trace[0].label == "Using cached Fetch text (0 credits)"
    assert attempt.result == {"title": "Acme"}


async def test_fetch_error_is_recorded(temp_db):
    blocked = {"results": [], "errors": [{"url": "u", "error": "bot_blocked"}]}
    claude = FakeClaude()
    ctrl = _controller(FakeTinyFish(fetch=[blocked]), claude)
    st = _state(ctrl)
    attempt, trace, fetch_used = await ctrl.run_fetch_attempt(st, ctrl.build_config(st, 1))
    assert [(e.kind, e.label) for e in trace] == [
        (TraceKind.fetch_error, "Fetch error: bot_blocked")
    ]
    assert attempt.tf_status == "ERROR" and fetch_used is blocked
    assert claude.calls == []


async def test_expected_value_missing_from_the_page_skips_claude():
    from app.models import ExpectedCheck

    claude = FakeClaude({FetchExtraction: [FOUND]})
    result, extraction, err = await extract_from_fetch(
        claude,
        goal="g",
        output_schema=None,
        expected=ExpectedCheck(type="regex", value=r"\b22\b"),
        page=SAMPLE_PAGE,
        max_chars=1000,
    )
    assert (result, err) == (None, None)
    assert extraction.found is False and extraction.missing == [r"expected '\b22\b'"]
    assert claude.calls == []  # free: no Claude call
