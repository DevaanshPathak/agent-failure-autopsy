import pytest

from app.models import (
    Diagnosis,
    Evidence,
    EvidenceSource,
    FailureClass,
    Patch,
    Rung,
    RunRequest,
)
from app.patch.planner import (
    PlanContext,
    compose_goal,
    next_rung_up,
    plan,
    tinyfish_schema_errors,
)

DOCS_EXAMPLE = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "price": {"type": "number", "minimum": 0},
        "published_at": {"type": "string", "format": "date-time", "nullable": True},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
    },
    "required": ["title", "price"],
    "propertyOrdering": ["title", "price", "published_at", "tags"],
}


def test_docs_example_schema_is_valid():
    assert tinyfish_schema_errors(DOCS_EXAMPLE) == []


def test_list_schema_with_any_of_field_is_valid():
    schema = {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "url": {"type": "string"}},
                    "required": ["name", "url"],
                },
            },
            "price": {"anyOf": [{"type": "number"}, {"type": "string", "enum": ["free"]}]},
        },
        "required": ["results"],
    }
    assert tinyfish_schema_errors(schema) == []


@pytest.mark.parametrize(
    ("schema", "needle"),
    [
        ({"type": "object", "additionalProperties": False}, "additionalProperties"),
        ({"type": "object", "properties": {"a": {"oneOf": []}}}, "oneOf"),
        ({"type": "object", "properties": {"a": {"const": "x"}}}, "const"),
        ({"type": "object", "properties": {"a": {"type": ["string", "null"]}}}, "type arrays"),
        ({"type": "object", "properties": {"a": {"type": "number", "enum": ["1"]}}}, "enum"),
        ({"type": "object", "properties": {"a": {"type": "string", "format": "uri"}}}, "format"),
        ({"type": "object", "properties": {"a": {"type": "string", "minItems": 1}}}, "minItems"),
        ({"type": "object", "required": ["missing"], "properties": {}}, "required fields"),
        ({"type": "array", "items": {"type": "string"}}, "top-level"),
        ({"anyOf": [{"type": "object"}]}, "top-level"),
        ({"type": "object", "properties": {"a": True}}, "boolean schema"),
    ],
)
def test_rejected_schemas_name_the_problem(schema, needle):
    errors = tinyfish_schema_errors(schema)
    assert errors, schema
    assert any(needle in e for e in errors), errors


def test_depth_limit():
    node: dict = {"type": "string"}
    for _ in range(11):
        node = {"type": "object", "properties": {"x": node}}
    assert any("depth" in e for e in tinyfish_schema_errors(node))


# --- plan() (Phase 3: rung movement) -------------------------------------------------------------

REQ = RunRequest(url="https://x.example", goal="Get the price")


def _ctx(rung: Rung, **kw) -> PlanContext:
    return PlanContext(rung=rung, request=REQ, **kw)


def _diag(cls: FailureClass) -> Diagnosis:
    return Diagnosis(
        attempt_no=1,
        failure_class=cls,
        recoverable=True,
        confidence=0.9,
        evidence=[Evidence(source=EvidenceSource.verifier, quote="x")],
        explanation="x",
        patch=Patch(),
        source="rules",
    )


@pytest.mark.parametrize("cls", [FailureClass.captcha, FailureClass.auth_wall])
def test_unrecoverable_classes_stop(cls):
    patch = plan(cls, _ctx(Rung.agent))
    assert patch.stop and patch.stop_reason


def test_bot_block_from_fetch_skips_the_plain_agent():
    patch = plan(FailureClass.bot_block, _ctx(Rung.fetch, proxy_country="US"))
    assert patch.next_rung is Rung.agent_stealth
    assert patch.skip_rungs == [Rung.agent]
    assert patch.summary == [
        "Escalate to rung 3: stealth browser + US proxy",
        "Skip rung 2: Fetch already hit a bot wall",
    ]


def test_bot_block_from_agent_escalates_without_skipping():
    patch = plan(FailureClass.bot_block, _ctx(Rung.agent))
    assert (patch.next_rung, patch.skip_rungs) == (Rung.agent_stealth, [])


def test_bot_block_on_stealth_stops_honestly():
    patch = plan(FailureClass.bot_block, _ctx(Rung.agent_stealth, proxy_country="US"))
    assert patch.stop
    assert "stealth browser and a US proxy" in patch.stop_reason


def test_needs_interaction_on_fetch_escalates_to_the_next_open_rung():
    assert plan(FailureClass.needs_interaction, _ctx(Rung.fetch)).summary == [
        "Escalate to Rung 2 · Agent"
    ]
    skipped = plan(FailureClass.needs_interaction, _ctx(Rung.fetch, skipped={Rung.agent}))
    assert skipped.next_rung is Rung.agent_stealth


def test_popup_retries_on_the_same_rung():
    patch = plan(FailureClass.popup_overlay, _ctx(Rung.agent))
    assert patch.next_rung is None and not patch.stop


def test_repeat_rule_escalates_then_stops_at_the_top():
    again = _ctx(
        Rung.agent, history=[_diag(FailureClass.popup_overlay)], history_rungs=[Rung.agent]
    )
    assert plan(FailureClass.popup_overlay, again).next_rung is Rung.agent_stealth
    top = _ctx(
        Rung.agent_stealth,
        history=[_diag(FailureClass.misread_page)],
        history_rungs=[Rung.agent_stealth],
    )
    patch = plan(FailureClass.misread_page, top)
    assert patch.stop and "twice on the top rung" in patch.stop_reason


def test_repeat_rule_ignores_a_different_previous_class_or_rung():
    ctx = _ctx(
        Rung.agent, history=[_diag(FailureClass.needs_interaction)], history_rungs=[Rung.fetch]
    )
    assert plan(FailureClass.popup_overlay, ctx).next_rung is None


def test_compose_goal_dedupes_and_caps_length():
    assert compose_goal("G", ["P", "P"], ["S", "P"]) == "P\n\nG\n\nS"
    long = compose_goal("G", [], ["a" * 1500, "b" * 600])
    assert len(long) <= 2000 and long.endswith("b" * 600)


def test_next_rung_up():
    assert next_rung_up(Rung.fetch, set()) is Rung.agent
    assert next_rung_up(Rung.fetch, {Rung.agent}) is Rung.agent_stealth
    assert next_rung_up(Rung.agent_stealth, set()) is None
