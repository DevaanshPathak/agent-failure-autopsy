"""Patch planner: turns a diagnosis into the next attempt's changes.

Phase 3 scope: rung movement only (stop, escalate, skip rungs, the repeat rule). Goal prefixes,
suffixes, tighter schemas and cache re-extraction arrive in Phase 4.
"""

from dataclasses import dataclass, field
from typing import Any

from app.models import (
    RUNG_LABEL,
    RUNG_ORDER,
    Diagnosis,
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
    "TINYFISH_FORMATS",
    "TINYFISH_SCHEMA_KEYWORDS",
    "PlanContext",
    "compose_goal",
    "next_rung_up",
    "plan",
    "tinyfish_schema_errors",
]

GOAL_MAX_CHARS = 2000

STOP_CAPTCHA = (
    "CAPTCHA detected — TinyFish cannot solve CAPTCHAs, so another attempt would only burn credits."
)
STOP_AUTH = "Login wall — this content needs an account, and logins are out of scope for this tool."


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
    if not ctx.history or ctx.from_fetch_cache:
        return False
    return ctx.history[-1].failure_class is failure_class and ctx.history_rungs[-1] is ctx.rung


def plan(
    failure_class: FailureClass, ctx: PlanContext, llm_prefix: str = "", llm_suffix: str = ""
) -> Patch:
    """Decide the next move for a diagnosed failure. `llm_prefix`/`llm_suffix` are used from
    Phase 4 on."""
    if failure_class is FailureClass.captcha:
        return Patch(stop=True, stop_reason=STOP_CAPTCHA, summary=["Stop: CAPTCHA (unrecoverable)"])
    if failure_class is FailureClass.auth_wall:
        return Patch(
            stop=True, stop_reason=STOP_AUTH, summary=["Stop: login required (unrecoverable)"]
        )

    if _is_repeat(failure_class, ctx):
        return _escalate(
            ctx.rung,
            ctx,
            f"Same failure ({failure_class.value}) twice on the top rung — "
            "stopping instead of burning credits.",
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
        return Patch(next_rung=Rung.agent_stealth, skip_rungs=skip, summary=summary)

    if failure_class is FailureClass.needs_interaction and ctx.rung is Rung.fetch:
        return _escalate(Rung.fetch, ctx)

    # popup_overlay, misread_page, needs_interaction on an agent rung: retry where we are.
    # Phase 4 adds the goal prefix/suffix, tighter schema and cache re-extraction here.
    return Patch(summary=["Retry on the same rung"])
