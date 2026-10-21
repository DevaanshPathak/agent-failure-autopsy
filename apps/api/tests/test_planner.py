import pytest

from app.models import (
    Diagnosis,
    Evidence,
    EvidenceSource,
    ExpectedCheck,
    FailureClass,
    Patch,
    Rung,
    RunRequest,
)
from app.patch.planner import (
    INTERACT_SUFFIX,
    MISREAD_SUFFIX,
    POPUP_PREFIX,
    PlanContext,
    compose_goal,
    derive_schema,
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


def test_popup_adds_the_dismiss_prefix_and_stays():
    patch = plan(FailureClass.popup_overlay, _ctx(Rung.agent))
    assert patch.next_rung is None and not patch.stop
    assert patch.goal_prefix == POPUP_PREFIX
    assert patch.summary == [
        "Goal prefix: close cookie/consent dialogs before anything else",
        "Stay on Rung 2 · Agent",
    ]


def test_popup_uses_a_short_llm_prefix_but_not_a_long_one():
    short = plan(FailureClass.popup_overlay, _ctx(Rung.agent), llm_prefix="Click 'Got it' first.")
    assert short.goal_prefix == "Click 'Got it' first."
    long = plan(FailureClass.popup_overlay, _ctx(Rung.agent), llm_prefix="x" * 301)
    assert long.goal_prefix == POPUP_PREFIX


def test_popup_seen_by_fetch_escalates_with_the_prefix():
    patch = plan(FailureClass.popup_overlay, _ctx(Rung.fetch))
    assert (patch.next_rung, patch.goal_prefix) == (Rung.agent, POPUP_PREFIX)


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


# --- plan() (Phase 4: content patches) -----------------------------------------------------------

REGEX_22 = RunRequest(
    url="https://x.example", goal="How many copies?", expected={"type": "regex", "value": r"\b22\b"}
)


def test_needs_interaction_on_an_agent_rung_adds_the_interaction_suffix():
    patch = plan(FailureClass.needs_interaction, _ctx(Rung.agent))
    assert (patch.next_rung, patch.goal_suffix) == (None, INTERACT_SUFFIX)


def test_misread_with_the_answer_in_the_cached_page_is_re_extracted_for_free():
    ctx = PlanContext(
        rung=Rung.agent,
        request=REGEX_22,
        fetch_text_available=True,
        fetch_text="Availability: In stock (22 available)",
    )
    patch = plan(FailureClass.misread_page, ctx)
    assert (patch.next_rung, patch.reextract_from_fetch) == (Rung.fetch, True)
    assert patch.output_schema == {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    assert patch.summary == [
        "Re-extract from the cached Fetch text with a tighter schema (0 credits)"
    ]


def test_failed_re_extract_goes_back_to_the_agent_rung_with_schema_and_suffix():
    ctx = PlanContext(
        rung=Rung.fetch,
        request=REGEX_22,
        from_fetch_cache=True,
        history_rungs=[Rung.fetch, Rung.agent],
        history=[_diag(FailureClass.needs_interaction), _diag(FailureClass.misread_page)],
        fetch_text_available=True,
        reextract_tried=True,
    )
    patch = plan(FailureClass.misread_page, ctx)
    assert patch.next_rung is Rung.agent
    assert patch.goal_suffix == MISREAD_SUFFIX
    assert patch.summary[0] == "Back to Rung 2 · Agent"


def test_misread_without_cache_tightens_in_place():
    req = RunRequest(
        url="https://x.example", goal="g", expected={"type": "min_items", "path": "items", "min": 5}
    )
    patch = plan(FailureClass.misread_page, PlanContext(rung=Rung.agent, request=req))
    assert patch.next_rung is None and not patch.reextract_from_fetch
    assert patch.output_schema is None  # min_items relies on the suffix, not a guessed schema
    assert patch.goal_suffix == MISREAD_SUFFIX + " Return at least 5 items in 'items'."


def test_misread_suffix_appends_a_short_llm_hint_and_respects_schema_entitlement():
    req = RunRequest(url="https://x.example", goal="g", expected={"type": "contains", "value": "x"})
    ctx = PlanContext(rung=Rung.agent, request=req, schema_entitled=False)
    patch = plan(
        FailureClass.misread_page, ctx, llm_suffix="Use the sale price, not the list price."
    )
    assert patch.output_schema is None
    assert patch.goal_suffix.endswith(" Use the sale price, not the list price.")


def test_repeat_rule_sees_any_earlier_attempt_on_the_same_rung():
    ctx = PlanContext(
        rung=Rung.agent,
        request=REGEX_22,
        history=[_diag(FailureClass.misread_page), _diag(FailureClass.misread_page)],
        history_rungs=[Rung.agent, Rung.fetch],
    )
    assert plan(FailureClass.misread_page, ctx).next_rung is Rung.agent_stealth


def test_derive_schema_from_fields_and_from_an_existing_schema():
    fields = ExpectedCheck(type="fields_present", fields=["title", "price.amount", "items.0.name"])
    schema = derive_schema(fields, None)
    assert schema["required"] == ["title", "price", "items"]
    assert schema["properties"]["price"]["required"] == ["amount"]
    assert schema["properties"]["items"]["type"] == "array"
    assert schema["properties"]["items"]["items"]["required"] == ["name"]
    assert tinyfish_schema_errors(schema) == []

    existing = {
        "type": "object",
        "properties": {
            "tags": {"type": "array", "items": {"type": "string"}},
            "t": {"type": "string"},
        },
    }
    tightened = derive_schema(None, existing)
    assert tightened["required"] == ["tags", "t"]
    assert tightened["properties"]["tags"]["minItems"] == 1
    assert "required" not in existing  # the original is not mutated
    assert derive_schema(None, None) is None
