"""Patch planner: turns a diagnosis into the next attempt's changes.

Per class: captcha and auth walls stop; bot blocks escalate to stealth + proxy (skipping the plain
agent when Fetch already saw the wall); popups get a goal prefix that dismisses dialogs; pages
that need interaction escalate from Fetch or get an interaction suffix; misreads are first
re-extracted from the cached Fetch text for free, otherwise retried with a tighter schema and a
"copy values exactly" suffix. A class that already failed once on a rung escalates instead.
"""

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from app.models import (
    RUNG_LABEL,
    RUNG_ORDER,
    Diagnosis,
    ExpectedCheck,
    ExpectedCheckType,
    FailureClass,
    Patch,
    Rung,
    RunRequest,
)
from app.patch.schema import (
    TINYFISH_FORMATS,
    TINYFISH_SCHEMA_KEYWORDS,
    tinyfish_schema_errors,
)

__all__ = [
    "INTERACT_SUFFIX",
    "MISREAD_SUFFIX",
    "POPUP_PREFIX",
    "TINYFISH_FORMATS",
    "TINYFISH_SCHEMA_KEYWORDS",
    "PlanContext",
    "compose_goal",
    "derive_schema",
    "next_rung_up",
    "plan",
    "tinyfish_schema_errors",
]

GOAL_MAX_CHARS = 2000
LLM_TEXT_MAX_CHARS = 300

POPUP_PREFIX = (
    "Before doing anything else, close any cookie consent banner, newsletter popup or modal "
    "dialog (click 'Accept', 'Accept all', 'Close', 'X' or 'No thanks') and wait until it has "
    "disappeared."
)
INTERACT_SUFFIX = (
    "If the requested data is not visible yet, interact with the page to reveal it: use the "
    "search box, filters, tabs, 'Load more' or 'Next' buttons as needed."
)
MISREAD_SUFFIX = (
    "Return only a JSON object that matches the output schema. Copy every value exactly as shown "
    "on the visible page; do not guess, and do not return null for required fields."
)
STOP_CAPTCHA = (
    "CAPTCHA detected — TinyFish cannot solve CAPTCHAs, so another attempt would only burn credits."
)
STOP_AUTH = "Login wall — this content needs an account, and logins are out of scope for this tool."

SUMMARY_POPUP = "Goal prefix: close cookie/consent dialogs before anything else"
SUMMARY_INTERACT = "Goal suffix: interact with search/filters/'Load more' to reveal the data"
SUMMARY_REEXTRACT = "Re-extract from the cached Fetch text with a tighter schema (0 credits)"
SUMMARY_SCHEMA = "Tighter output schema"
SUMMARY_COPY_EXACT = "Goal suffix: copy values exactly from the page"


@dataclass
class PlanContext:
    rung: Rung
    request: RunRequest
    from_fetch_cache: bool = False
    current_schema: dict[str, Any] | None = None
    skipped: set[Rung] = field(default_factory=set)
    history: list[Diagnosis] = field(default_factory=list)
    history_rungs: list[Rung] = field(default_factory=list)
    fetch_text_available: bool = False
    fetch_extraction_found: bool = False
    fetch_text: str | None = None
    reextract_tried: bool = False
    proxy_country: str = "US"
    schema_entitled: bool = True


# --- Goal and rung helpers -----------------------------------------------------------------------


def compose_goal(original: str, prefixes: list[str], suffixes: list[str]) -> str:
    """Prefixes, then the user's goal, then suffixes; duplicates dropped, oldest suffixes first
    to go if the goal would exceed TinyFish-friendly length."""
    prefixes = list(dict.fromkeys(p for p in prefixes if p))
    suffixes = list(dict.fromkeys(s for s in suffixes if s and s not in prefixes))
    goal = "\n\n".join([*prefixes, original, *suffixes])
    while len(goal) > GOAL_MAX_CHARS and suffixes:
        suffixes.pop(0)
        goal = "\n\n".join([*prefixes, original, *suffixes])
    return goal


def next_rung_up(rung: Rung, skipped: set[Rung]) -> Rung | None:
    later = RUNG_ORDER[RUNG_ORDER.index(rung) + 1 :]
    return next((r for r in later if r not in skipped), None)


def _usable_llm_text(text: str) -> str:
    text = (text or "").strip()
    return text if 0 < len(text) <= LLM_TEXT_MAX_CHARS else ""


# --- Schema derivation ---------------------------------------------------------------------------


def _tighten(node: Any) -> None:
    if not isinstance(node, dict):
        return
    props = node.get("properties")
    if isinstance(props, dict):
        node["required"] = list(props)
        for sub in props.values():
            _tighten(sub)
    if node.get("type") == "array":
        node.setdefault("minItems", 1)
        _tighten(node.get("items"))
    for branch in node.get("anyOf") or []:
        _tighten(branch)


def _schema_for_paths(paths: list[list[str]]) -> dict[str, Any]:
    groups: dict[str, list[list[str]]] = {}
    for segments in paths:
        groups.setdefault(segments[0], []).append(segments[1:])
    properties: dict[str, Any] = {}
    for key, rests in groups.items():
        nested = [r for r in rests if r]
        if not nested:
            properties[key] = {"type": "string"}
        elif all(r[0].isdigit() for r in nested):
            inner = [r[1:] for r in nested if r[1:]]
            items = _schema_for_paths(inner) if inner else {"type": "string"}
            min_items = max(int(r[0]) for r in nested) + 1
            properties[key] = {"type": "array", "items": items, "minItems": min_items}
        else:
            properties[key] = _schema_for_paths(nested)
    return {"type": "object", "properties": properties, "required": list(properties)}


def derive_schema(
    expected: ExpectedCheck | None, existing: dict[str, Any] | None
) -> dict[str, Any] | None:
    """A stricter TinyFish output_schema: tighten the existing one, or build one from the
    expected check. Never returns a schema TinyFish would reject."""
    schema: dict[str, Any] | None = None
    if existing:
        schema = copy.deepcopy(existing)
        _tighten(schema)
    elif expected is not None and expected.type is ExpectedCheckType.fields_present:
        paths = [[s for s in f.split(".") if s] for f in expected.fields or []]
        paths = [p for p in paths if p]
        schema = _schema_for_paths(paths) if paths else None
    elif expected is not None and expected.type in (
        ExpectedCheckType.contains,
        ExpectedCheckType.regex,
    ):
        schema = {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        }
    if schema is not None and tinyfish_schema_errors(schema):
        return None
    return schema


# --- Planning ------------------------------------------------------------------------------------


def _escalate(rung: Rung, ctx: PlanContext, reason: str | None = None) -> Patch:
    target = next_rung_up(rung, ctx.skipped)
    if target is None:
        return Patch(
            stop=True,
            stop_reason=reason
            or "No higher rung left to try — stopping instead of burning credits.",
            summary=["Stop: no higher rung left"],
        )
    return Patch(next_rung=target, summary=[f"Escalate to {RUNG_LABEL[target]}"])


def _is_repeat(failure_class: FailureClass, ctx: PlanContext) -> bool:
    """The class already failed on this rung, so its patch was tried there. Cache re-extracts
    are never repeats: they are a different, free path."""
    if ctx.from_fetch_cache:
        return False
    return any(
        d.failure_class is failure_class and r is ctx.rung
        for d, r in zip(ctx.history, ctx.history_rungs, strict=False)
    )


def _expected_matches_text(expected: ExpectedCheck | None, text: str | None) -> bool:
    if expected is None or not text:
        return False
    if expected.type is ExpectedCheckType.contains:
        return bool(expected.value) and expected.value.lower() in text.lower()
    if expected.type is ExpectedCheckType.regex:
        return bool(expected.value) and re.search(expected.value, text, re.I) is not None
    return False


def _misread_tightening(
    ctx: PlanContext, llm_suffix: str
) -> tuple[dict[str, Any] | None, str, list[str]]:
    """(schema, suffix, summary) for a retry after a misread."""
    schema = (
        derive_schema(ctx.request.expected, ctx.current_schema) if ctx.schema_entitled else None
    )
    suffix = MISREAD_SUFFIX
    expected = ctx.request.expected
    if expected is not None and expected.type is ExpectedCheckType.min_items:
        suffix += f" Return at least {expected.min} items in '{expected.path}'."
    if llm := _usable_llm_text(llm_suffix):
        suffix += " " + llm
    summary = ([SUMMARY_SCHEMA] if schema else []) + [SUMMARY_COPY_EXACT]
    return schema, suffix, summary


def _plan_misread(ctx: PlanContext, llm_suffix: str) -> Patch:
    schema, suffix, summary = _misread_tightening(ctx, llm_suffix)

    if ctx.rung is Rung.fetch and ctx.from_fetch_cache:
        # (b) the free re-extract failed too: back to the agent rung we came from.
        agent_rungs = [r for r in ctx.history_rungs if r is not Rung.fetch]
        target = agent_rungs[-1] if agent_rungs else next_rung_up(Rung.fetch, ctx.skipped)
        if target is None:
            return _escalate(Rung.fetch, ctx)
        return Patch(
            next_rung=target,
            output_schema=schema,
            goal_suffix=suffix,
            summary=[f"Back to {RUNG_LABEL[target]}", *summary],
        )

    data_in_cache = ctx.fetch_extraction_found or _expected_matches_text(
        ctx.request.expected, ctx.fetch_text
    )
    if (
        ctx.fetch_text_available
        and not ctx.reextract_tried
        and (ctx.rung is Rung.fetch or data_in_cache)
    ):
        # (a) the data is in the page text we already have: re-read it for free.
        return Patch(
            next_rung=Rung.fetch if ctx.rung is not Rung.fetch else None,
            reextract_from_fetch=True,
            output_schema=derive_schema(ctx.request.expected, ctx.current_schema),
            summary=[SUMMARY_REEXTRACT],
        )

    if ctx.rung is Rung.fetch:
        return _escalate(Rung.fetch, ctx)
    # (c) tighten in place.
    return Patch(output_schema=schema, goal_suffix=suffix, summary=summary)


def plan(
    failure_class: FailureClass, ctx: PlanContext, llm_prefix: str = "", llm_suffix: str = ""
) -> Patch:
    """Decide the next move for a diagnosed failure. Claude's suggested prefix/suffix (only
    passed when Claude made the diagnosis) is used when it is short enough."""
    if failure_class is FailureClass.captcha:
        return Patch(stop=True, stop_reason=STOP_CAPTCHA, summary=["Stop: CAPTCHA (unrecoverable)"])
    if failure_class is FailureClass.auth_wall:
        return Patch(
            stop=True, stop_reason=STOP_AUTH, summary=["Stop: login required (unrecoverable)"]
        )

    if failure_class is FailureClass.bot_block:
        if ctx.rung is Rung.agent_stealth:
            return Patch(
                stop=True,
                stop_reason=(
                    f"Still blocked with a stealth browser and a {ctx.proxy_country} proxy "
                    "— stopping honestly."
                ),
                summary=["Stop: still blocked on rung 3"],
            )
        skip = [Rung.agent] if ctx.rung is Rung.fetch else []
        summary = [f"Escalate to rung 3: stealth browser + {ctx.proxy_country} proxy"]
        if skip:
            summary.append("Skip rung 2: Fetch already hit a bot wall")
        return Patch(
            next_rung=Rung.agent_stealth,
            skip_rungs=skip,
            browser_profile="stealth",
            proxy_enabled=True,
            summary=summary,
        )

    if _is_repeat(failure_class, ctx):
        return _escalate(
            ctx.rung,
            ctx,
            f"Same failure ({failure_class.value}) twice on the top rung — "
            "stopping instead of burning credits.",
        )

    if failure_class is FailureClass.popup_overlay:
        prefix = _usable_llm_text(llm_prefix) or POPUP_PREFIX
        if ctx.rung is Rung.fetch:
            target = next_rung_up(Rung.fetch, ctx.skipped)
            if target is None:
                return _escalate(Rung.fetch, ctx)
            return Patch(
                next_rung=target,
                goal_prefix=prefix,
                summary=[SUMMARY_POPUP, f"Escalate to {RUNG_LABEL[target]}"],
            )
        return Patch(goal_prefix=prefix, summary=[SUMMARY_POPUP, f"Stay on {RUNG_LABEL[ctx.rung]}"])

    if failure_class is FailureClass.needs_interaction:
        if ctx.rung is Rung.fetch:
            return _escalate(Rung.fetch, ctx)
        return Patch(goal_suffix=INTERACT_SUFFIX, summary=[SUMMARY_INTERACT])

    return _plan_misread(ctx, llm_suffix)
