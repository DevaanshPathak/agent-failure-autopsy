"""Patch planner: turns a diagnosis into the next attempt's changes."""

from app.patch.schema import (
    TINYFISH_FORMATS,
    TINYFISH_SCHEMA_KEYWORDS,
    tinyfish_schema_errors,
)

__all__ = [
    "TINYFISH_FORMATS",
    "TINYFISH_SCHEMA_KEYWORDS",
    "compose_goal",
    "tinyfish_schema_errors",
]

GOAL_MAX_CHARS = 2000


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
