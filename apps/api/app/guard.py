"""Spend guards for a public deployment (docs/deploy.md).

Anyone who can reach a public API spends its keys, so live runs are limited across every visitor:
a number at a time, a cap per hour, and a total TinyFish credit cap. They are counted in the
database, so they hold across serverless instances and restarts. With a credit cap set, a request
can't raise its own limits above the defaults either.
"""

from dataclasses import dataclass
from datetime import timedelta

from app import db
from app.config import Settings
from app.events import utcnow
from app.models import RunRequest

WATCH_INSTEAD = "or watch a bundled run on the home page"


class LiveRunRefused(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class LiveAllowance:
    max_attempts: int
    max_credits: int


@dataclass(frozen=True)
class LiveUsage:
    active: int
    last_hour: int
    credits_used: int


async def live_usage(settings: Settings) -> LiveUsage:
    now = utcnow()
    active, last_hour, used = await db.live_usage(
        now - timedelta(seconds=settings.stale_run_s),
        now - timedelta(hours=1),
        settings.live_budget_since,
    )
    return LiveUsage(active, last_hour, used)


async def allow_live_run(settings: Settings, req: RunRequest) -> LiveAllowance:
    """The limits this live run gets, or LiveRunRefused (429 busy, 503 budget spent)."""
    usage = await live_usage(settings)
    if usage.active >= settings.max_concurrent_live_runs:
        raise LiveRunRefused(
            429, f"Another live run is in progress. Try again in a minute, {WATCH_INSTEAD}."
        )
    per_hour = settings.live_runs_per_hour
    if per_hour is not None and usage.last_hour >= per_hour:
        raise LiveRunRefused(
            429,
            f"This demo's limit of {per_hour} live runs per hour is reached: try later, "
            f"{WATCH_INSTEAD}.",
        )

    max_attempts = req.max_attempts or settings.max_attempts
    max_credits = req.max_credits if req.max_credits is not None else settings.max_credits
    cap = settings.live_credit_cap
    if cap is not None:
        left = cap - usage.credits_used
        if left < settings.agent_min_credits:
            raise LiveRunRefused(
                503,
                f"This demo's TinyFish credit budget ({cap} credits) is used up: replay a "
                f"recorded run, {WATCH_INSTEAD}.",
            )
        max_attempts = min(max_attempts, settings.max_attempts)
        max_credits = min(max_credits, settings.max_credits, left)
    return LiveAllowance(max_attempts=max_attempts, max_credits=max_credits)
