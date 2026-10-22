"""Claude spend tracking and a hard cap (the team's Anthropic budget is small).

Every call's real cost is computed from `response.usage` and stored in the database, so the
total survives restarts. Before a call, a worst-case estimate (input + the full max_tokens) must
fit under the cap; otherwise the call is not made and callers fall back to the rules.
"""

import asyncio

from app import db

# First-party list prices, USD per million tokens (input, output).
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
# Unknown model ids are priced like the most expensive model, so the cap stays safe.
FALLBACK_PRICE = (10.0, 50.0)
CHARS_PER_TOKEN = 3.0  # conservative (JSON-heavy prompts); real English is closer to 4


def price_for(model: str) -> tuple[float, float]:
    if model in PRICES_PER_MTOK:
        return PRICES_PER_MTOK[model]
    for prefix in sorted(PRICES_PER_MTOK, key=len, reverse=True):
        if model.startswith(prefix):
            return PRICES_PER_MTOK[prefix]
    return FALLBACK_PRICE


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    price_in, price_out = price_for(model)
    return (
        input_tokens * price_in
        + cache_write_tokens * price_in * 1.25
        + cache_read_tokens * price_in * 0.1
        + output_tokens * price_out
    ) / 1_000_000


def estimate_max_cost(model: str, prompt_chars: int, max_tokens: int) -> float:
    """Worst case for one call: the whole prompt plus every allowed output token."""
    return cost_usd(model, int(prompt_chars / CHARS_PER_TOKEN) + 50, max_tokens)


class ClaudeBudget:
    def __init__(self, cap_usd: float) -> None:
        self.cap_usd = cap_usd
        self.spent_usd = 0.0
        self.calls = 0
        self._loaded = False
        self._lock = asyncio.Lock()

    async def ensure_loaded(self) -> None:
        if not self._loaded:
            async with self._lock:
                if not self._loaded:
                    self.spent_usd, self.calls = await db.llm_spend_total()
                    self._loaded = True

    async def can_afford(self, estimate_usd: float) -> bool:
        await self.ensure_loaded()
        return self.spent_usd + estimate_usd <= self.cap_usd

    async def record(self, *, model: str, purpose: str, usage: object | None) -> float:
        """Add one billed call. `usage` is the SDK's `response.usage` (missing fields count 0)."""
        await self.ensure_loaded()

        def tokens(name: str) -> int:
            value = getattr(usage, name, 0) if usage is not None else 0
            return value if isinstance(value, int) else 0

        input_tokens, output_tokens = tokens("input_tokens"), tokens("output_tokens")
        cache_write, cache_read = (
            tokens("cache_creation_input_tokens"),
            tokens("cache_read_input_tokens"),
        )
        cost = cost_usd(model, input_tokens, output_tokens, cache_write, cache_read)
        self.spent_usd += cost
        self.calls += 1
        await db.append_llm_usage(
            model=model,
            purpose=purpose,
            input_tokens=input_tokens + cache_write + cache_read,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        return cost
