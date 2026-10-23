"use client";

import { useEffect, useState } from "react";

import { getHealth } from "@/lib/api";
import { liveBudgetSummary, type LiveBudgetSummary } from "@/lib/liveBudget";

const REFRESH_MS = 15_000;

/**
 * The shared spend budget of a hosted live demo (from GET /health). Renders nothing in local dev
 * (no shared cap) or when /health can't be reached.
 */
export default function LiveBudget() {
  const [budget, setBudget] = useState<LiveBudgetSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      if (document.hidden) return;
      getHealth()
        .then((health) => {
          if (!cancelled) setBudget(liveBudgetSummary(health));
        })
        .catch(() => {
          if (!cancelled) setBudget(null);
        });
    };
    refresh();
    const timer = window.setInterval(refresh, REFRESH_MS);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);

  if (!budget) return null;
  const { creditsLeft, creditCap, claude, liveRunActive } = budget;
  return (
    <section
      aria-label="Shared live-run budget"
      className="max-w-3xl space-y-2 rounded-lg border border-amber-500/30 bg-amber-950/30 px-4 py-3 text-amber-100"
    >
      <p>
        Live runs call TinyFish{claude ? " and Claude" : ""} for real and spend a budget shared by
        everyone using this demo.
      </p>
      <p className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
        <span>
          <span className="font-mono font-semibold text-amber-50">{creditsLeft}</span> of{" "}
          <span className="font-mono">{creditCap}</span> TinyFish credits left
        </span>
        {claude && (
          <span>
            Claude: <span className="font-mono font-semibold text-amber-50">{claude.spent}</span> of{" "}
            <span className="font-mono">{claude.budget}</span> spent
          </span>
        )}
      </p>
      {liveRunActive && (
        <p className="text-sm font-medium text-amber-200">
          A live run is in progress — yours can start when it finishes.
        </p>
      )}
      {creditsLeft === 0 && (
        <p className="text-sm font-medium text-amber-200">
          The shared budget is used up, so live runs are off. The recorded runs below still play.
        </p>
      )}
    </section>
  );
}
