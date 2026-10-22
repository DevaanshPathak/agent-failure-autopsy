from types import SimpleNamespace

import pytest

from app.llm.budget import ClaudeBudget, cost_usd, estimate_max_cost, price_for
from app.llm.claude import ClaudeClient
from app.models import FetchExtraction

FOUND = FetchExtraction(found=True, result_json='{"a": 1}', missing=[], interaction_hint="")


class FakeSDK:
    """Stands in for anthropic.AsyncAnthropic: records calls, returns one canned response."""

    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, dict]] = []
        self.messages = SimpleNamespace(parse=self._parse("plain"))
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse("beta")))

    def with_options(self, **_kwargs):
        return self

    def _parse(self, kind):
        async def parse(**kwargs):
            self.calls.append((kind, kwargs))
            return self.response

        return parse


def _response(input_tokens=1000, output_tokens=500, parsed=FOUND):
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    return SimpleNamespace(usage=usage, stop_reason="end_turn", parsed_output=parsed)


def test_prices_and_costs():
    assert price_for("claude-opus-5-5") == (4.0, 20.0)
    assert price_for("claude-haiku-4-5-20251001") == (1.0, 5.0)
    assert price_for("some-future-model") == (10.0, 50.0)  # unknown -> priced high, cap stays safe
    assert cost_usd("claude-opus-5-5", 1_000_000, 0) == pytest.approx(4.0)
    assert cost_usd("claude-haiku-4-5", 1000, 1000) == pytest.approx(0.006)
    assert estimate_max_cost("claude-sonnet-5-5", 3000, 2000) == pytest.approx(
        (1050 * 2 + 2000 * 10) / 1e6
    )


async def test_spend_is_recorded_and_survives_a_restart(temp_db):
    budget = ClaudeBudget(4.0)
    client = ClaudeClient("k", "claude-opus-5-5", budget=budget, sdk=FakeSDK(_response()))
    out = await client.parse(system="s", user="u", output_model=FetchExtraction, purpose="extract")
    assert out.parsed == FOUND
    assert budget.calls == 1
    assert budget.spent_usd == pytest.approx((1000 * 4 + 500 * 20) / 1e6)

    restarted = ClaudeBudget(4.0)
    await restarted.ensure_loaded()
    assert (restarted.calls, round(restarted.spent_usd, 6)) == (1, round(budget.spent_usd, 6))


async def test_over_budget_calls_are_never_sent(temp_db):
    sdk = FakeSDK(_response())
    client = ClaudeClient("k", "claude-opus-5-5", budget=ClaudeBudget(0.01), sdk=sdk)
    out = await client.parse(system="s", user="x" * 30_000, output_model=FetchExtraction)
    assert out.parsed is None
    assert out.error.startswith("Claude budget reached")
    assert sdk.calls == []


async def test_request_shape_depends_on_the_model(temp_db):
    opus_sdk, haiku_sdk = FakeSDK(_response()), FakeSDK(_response())
    await ClaudeClient("k", "claude-opus-5-5", sdk=opus_sdk).parse(
        system="s", user="u", output_model=FetchExtraction
    )
    await ClaudeClient("k", "claude-haiku-4-5", sdk=haiku_sdk).parse(
        system="s", user="u", output_model=FetchExtraction
    )
    kind, kwargs = opus_sdk.calls[0]
    assert kind == "beta" and kwargs["fallbacks"] == "default"
    assert kwargs["output_config"] == {"effort": "low"} and kwargs["max_tokens"] == 2000
    kind, kwargs = haiku_sdk.calls[0]
    assert kind == "plain"
    assert "output_config" not in kwargs and "fallbacks" not in kwargs


async def test_refusals_still_count_against_the_budget(temp_db):
    budget = ClaudeBudget(4.0)
    refused = SimpleNamespace(
        **{**vars(_response()), "stop_reason": "refusal", "parsed_output": None}
    )
    out = await ClaudeClient("k", "claude-sonnet-5-5", budget=budget, sdk=FakeSDK(refused)).parse(
        system="s", user="u", output_model=FetchExtraction
    )
    assert out.error == "refusal" and budget.calls == 1
