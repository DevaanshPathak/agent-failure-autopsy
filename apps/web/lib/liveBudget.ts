import type { Health } from "./types";

/** The shared live-run budget of a hosted demo, as the home page shows it. */
export interface LiveBudgetSummary {
  creditsLeft: number;
  creditCap: number;
  /** Claude's spend against its budget ("$x"), or null when Claude isn't configured. */
  claude: { spent: string; budget: string } | null;
  /** A live run is in progress; only one runs at a time across all visitors. */
  liveRunActive: boolean;
}

/** TinyFish credits left under the shared cap (floor 0), or null when there is no shared cap. */
export function budgetLeft(health: Pick<Health, "live_credit_cap" | "live_credits_used">) {
  if (health.live_credit_cap === null) return null;
  return Math.max(0, health.live_credit_cap - health.live_credits_used);
}

/** Dollars with cents, e.g. "$0.42" (matches the API's own budget messages). */
export function fmtUsd(n: number): string {
  return `$${(Number.isFinite(n) ? Math.max(0, n) : 0).toFixed(2)}`;
}

/** What to show about the shared budget, or null when there is none (local dev). */
export function liveBudgetSummary(health: Health): LiveBudgetSummary | null {
  const creditsLeft = budgetLeft(health);
  if (creditsLeft === null || health.live_credit_cap === null) return null;
  return {
    creditsLeft,
    creditCap: health.live_credit_cap,
    claude: health.claude_ready
      ? { spent: fmtUsd(health.claude_spent_usd), budget: fmtUsd(health.claude_budget_usd) }
      : null,
    liveRunActive: health.live_run_active,
  };
}
