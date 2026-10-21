"""Thin wrapper around the Anthropic SDK for strict-JSON calls (structured outputs).

`parse()` never raises: the extractor and the diagnoser always have a rules-based fallback, so a
failed, refused or unparseable call comes back as `ParseOutcome(parsed=None, error=...)`.
"""

import logging
from dataclasses import dataclass
from typing import Any

import anthropic
import pydantic

log = logging.getLogger(__name__)

# Server-side refusal fallback: on a policy decline the API re-runs the request on a fallback
# model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class ParseOutcome[T: pydantic.BaseModel]:
    parsed: T | None
    error: str | None = None
    stop_reason: str | None = None


class ClaudeClient:
    def __init__(self, api_key: str, model: str, *, use_fallbacks: bool = True) -> None:
        self.model = model
        self.use_fallbacks = use_fallbacks
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=1)

    async def parse[T: pydantic.BaseModel](
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        max_tokens: int = 4000,
        effort: str = "low",
        timeout_s: float = 45.0,
    ) -> ParseOutcome[T]:
        # Opus 5.5 always thinks (never send thinking: disabled); effort is the cost control and
        # defaults to medium on this model, so it is always passed explicitly.
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_format": output_model,
            "output_config": {"effort": effort},
        }
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

        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            return ParseOutcome(None, "refusal", "refusal")
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            return ParseOutcome(None, "no parsed output", stop_reason)
        return ParseOutcome(parsed, None, stop_reason)
