"""Thin wrapper around the Anthropic SDK for strict-JSON calls (structured outputs).

`parse()` never raises: the extractor and the diagnoser always have a rules-based fallback, so a
failed, refused, unparseable or over-budget call comes back as `ParseOutcome(parsed=None, ...)`.
Every billed call is costed from `response.usage` and counted against the hard budget.
"""

import logging
from dataclasses import dataclass
from typing import Any

import anthropic
import pydantic

from app.llm.budget import ClaudeBudget, estimate_max_cost

log = logging.getLogger(__name__)

# Server-side refusal fallback: on a policy decline the API re-runs the request on a fallback
# model inside the same call. Only some models accept the "default" form.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
# `output_config.effort` is rejected by older models such as Haiku 4.5.
EFFORT_MODELS = (
    "claude-fable",
    "claude-mythos",
    "claude-opus-5",
    "claude-opus-4-5",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
)
DEFAULT_MAX_TOKENS = 2000


def supports_effort(model: str) -> bool:
    return model.startswith(EFFORT_MODELS)


def supports_fallbacks(model: str) -> bool:
    return model.startswith(FALLBACK_MODELS)


@dataclass
class ParseOutcome[T: pydantic.BaseModel]:
    parsed: T | None
    error: str | None = None
    stop_reason: str | None = None


class ClaudeClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        budget: ClaudeBudget | None = None,
        use_fallbacks: bool | None = None,
        sdk: Any = None,
    ) -> None:
        self.model = model
        self.budget = budget
        self.use_fallbacks = supports_fallbacks(model) if use_fallbacks is None else use_fallbacks
        self._client = sdk or anthropic.AsyncAnthropic(api_key=api_key, max_retries=1)

    def request_kwargs(
        self, *, system: str, user: str, output_model: type, max_tokens: int, effort: str
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_format": output_model,
        }
        if supports_effort(self.model):
            # Opus 5.5 always thinks and defaults to effort "medium": pass it explicitly.
            kwargs["output_config"] = {"effort": effort}
        return kwargs

    async def parse[T: pydantic.BaseModel](
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        purpose: str = "",
        max_tokens: int = DEFAULT_MAX_TOKENS,
        effort: str = "low",
        timeout_s: float = 45.0,
    ) -> ParseOutcome[T]:
        if self.budget is not None:
            estimate = estimate_max_cost(self.model, len(system) + len(user), max_tokens)
            if not await self.budget.can_afford(estimate):
                spent, cap = self.budget.spent_usd, self.budget.cap_usd
                return ParseOutcome(None, f"Claude budget reached (${spent:.2f} of ${cap:.2f})")

        kwargs = self.request_kwargs(
            system=system,
            user=user,
            output_model=output_model,
            max_tokens=max_tokens,
            effort=effort,
        )
        client = self._client.with_options(timeout=timeout_s)
        try:
            if self.use_fallbacks:
                try:
                    response: Any = await client.beta.messages.parse(
                        **kwargs, betas=[FALLBACK_BETA], fallbacks="default"
                    )
                except (TypeError, anthropic.BadRequestError) as e:
                    log.warning("server-side fallback unavailable, using plain parse: %s", e)
                    self.use_fallbacks = False
                    response = await client.messages.parse(**kwargs)
            else:
                response = await client.messages.parse(**kwargs)
        except anthropic.RateLimitError as e:
            return ParseOutcome(None, f"RateLimitError: {e}")
        except anthropic.APIStatusError as e:
            return ParseOutcome(None, f"{type(e).__name__} {e.status_code}: {e}")
        except anthropic.APIConnectionError as e:
            return ParseOutcome(None, f"{type(e).__name__}: {e}")
        except pydantic.ValidationError as e:
            return ParseOutcome(None, f"ValidationError: {e.error_count()} issue(s)")

        if self.budget is not None:
            cost = await self.budget.record(
                model=self.model, purpose=purpose, usage=getattr(response, "usage", None)
            )
            log.info(
                "claude %s call cost $%.4f (total $%.4f)", purpose, cost, self.budget.spent_usd
            )
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            return ParseOutcome(None, "refusal", "refusal")
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            return ParseOutcome(None, "no parsed output", stop_reason)
        return ParseOutcome(parsed, None, stop_reason)
