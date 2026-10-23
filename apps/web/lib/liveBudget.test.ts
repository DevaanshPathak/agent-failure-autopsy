import { describe, expect, it } from "vitest";

import { budgetLeft, fmtUsd, liveBudgetSummary } from "./liveBudget";
import type { Health } from "./types";

const health: Health = {
  status: "ok",
  mode: "live",
  version: "0.1.0",
  db: "ok",
  tinyfish_key: true,
  anthropic_key: true,
  claude_model: "claude-test",
  claude_ready: true,
  claude_calls: 3,
  claude_spent_usd: 0.4213,
  claude_budget_usd: 5,
  live_run_active: false,
  live_credits_used: 120,
  live_credit_cap: 500,
};

describe("budgetLeft", () => {
  it("is the cap minus what was used", () => {
    expect(budgetLeft(health)).toBe(380);
  });

  it("never goes below zero", () => {
    expect(budgetLeft({ live_credit_cap: 100, live_credits_used: 130 })).toBe(0);
  });

  it("is null without a shared cap", () => {
    expect(budgetLeft({ live_credit_cap: null, live_credits_used: 50 })).toBeNull();
  });
});

describe("fmtUsd", () => {
  it("shows dollars with cents", () => {
    expect(fmtUsd(0.4213)).toBe("$0.42");
    expect(fmtUsd(5)).toBe("$5.00");
  });

  it("shows nonsense as $0.00", () => {
    expect(fmtUsd(Number.NaN)).toBe("$0.00");
    expect(fmtUsd(-1)).toBe("$0.00");
  });
});

describe("liveBudgetSummary", () => {
  it("summarises a hosted demo's shared budget", () => {
    expect(liveBudgetSummary({ ...health, live_run_active: true })).toEqual({
      creditsLeft: 380,
      creditCap: 500,
      claude: { spent: "$0.42", budget: "$5.00" },
      liveRunActive: true,
    });
  });

  it("leaves Claude out when it isn't configured", () => {
    expect(liveBudgetSummary({ ...health, claude_ready: false })?.claude).toBeNull();
  });

  it("is null in local dev (no shared cap)", () => {
    expect(liveBudgetSummary({ ...health, live_credit_cap: null })).toBeNull();
  });
});
