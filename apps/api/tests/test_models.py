import json

import pytest
from pydantic import ValidationError

from app.export_schema import EXPORTED, build_schema
from app.models import (
    DiagnosisEvent,
    ExpectedCheck,
    Patch,
    RunRequest,
    TraceUiEvent,
    UiEventAdapter,
    VerdictEvent,
)


def test_every_sample_line_is_a_valid_ui_event(sample_lines):
    events = [UiEventAdapter.validate_json(line) for line in sample_lines]
    assert len(events) == 36
    assert [e.seq for e in events] == list(range(1, 37))
    assert events[0].type == "budget"
    assert events[-1].type == "verdict"


def test_sample_events_round_trip(sample_lines):
    for line in sample_lines:
        event = UiEventAdapter.validate_json(line)
        dumped = UiEventAdapter.dump_python(event, mode="json")
        assert UiEventAdapter.validate_python(dumped) == event
        assert next(iter(dumped)) == "type"


def test_sample_tells_the_documented_story(sample_lines):
    events = [UiEventAdapter.validate_json(line) for line in sample_lines]
    diagnoses = [e.diagnosis for e in events if isinstance(e, DiagnosisEvent)]
    assert [d.failure_class for d in diagnoses] == ["needs_interaction", "popup_overlay"]
    assert [d.failing_step_seq for d in diagnoses] == [2, 4]
    for e in events:
        if isinstance(e, TraceUiEvent):
            assert e.event.attempt_no == e.attempt_no
    verdict = events[-1]
    assert isinstance(verdict, VerdictEvent)
    assert (verdict.status, verdict.credits_used, verdict.attempts_used) == ("verified", 9, 3)


def test_run_request_accepts_and_normalizes_the_sample_request():
    req = RunRequest(
        url="  https://shop.example.com/products ",
        goal="  List the first 3 products on the page with their name and price. ",
        expected={"type": "min_items", "path": "products", "min": 3},
    )
    assert req.url == "https://shop.example.com/products"
    assert req.goal.startswith("List")
    assert req.start_rung == "fetch"


@pytest.mark.parametrize(
    "overrides",
    [
        {"url": "ftp://example.com"},
        {"goal": "   "},
        {"output_schema": {"type": "object", "additionalProperties": False}},
        {"max_attempts": 0},
        {"max_credits": 501},
        {"unknown_field": 1},
    ],
)
def test_run_request_rejects_bad_input(overrides):
    body = {"url": "https://example.com", "goal": "Return the heading", **overrides}
    with pytest.raises(ValidationError):
        RunRequest.model_validate(body)


@pytest.mark.parametrize(
    "check",
    [
        {"type": "min_items", "min": 3},
        {"type": "min_items", "path": "items", "min": 0},
        {"type": "contains"},
        {"type": "regex", "value": "("},
        {"type": "fields_present", "fields": []},
    ],
)
def test_expected_check_rejects_incomplete_shapes(check):
    with pytest.raises(ValidationError):
        ExpectedCheck.model_validate(check)


def test_expected_check_accepts_each_type():
    for check in (
        {"type": "contains", "value": "Blue Mug"},
        {"type": "regex", "value": r"\b22\b"},
        {"type": "fields_present", "fields": ["title", "price.amount"]},
        {"type": "min_items", "path": "products", "min": 3},
    ):
        ExpectedCheck.model_validate(check)


def test_patch_stop_requires_a_reason():
    with pytest.raises(ValidationError):
        Patch(stop=True)


def test_verdict_status_must_be_final():
    with pytest.raises(ValidationError):
        VerdictEvent(
            seq=1,
            run_id="r",
            ts="2026-11-01T11:00:00Z",
            status="running",
            reason="x",
            attempts_used=0,
            credits_used=0,
        )


def test_export_schema_contains_every_contract():
    schema = build_schema()
    definitions = schema["definitions"]
    assert {m.__name__ for m in EXPORTED} <= set(definitions)
    assert len(definitions["UiEvent"]["oneOf"]) == 8
    assert "type" in definitions["AttemptStartedEvent"]["required"]
    json.dumps(schema)
