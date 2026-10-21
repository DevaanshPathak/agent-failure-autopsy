import { Fragment } from "react";

import { RUNG_ORDER, fmtCredits } from "@/lib/format";
import type { RungState, RunViewState } from "@/lib/runState";
import type { Rung, RungChangeEvent } from "@/lib/types";

const TITLE: Record<Rung, string> = {
  fetch: "1 · Fetch",
  agent: "2 · Agent",
  agent_stealth: "3 · Agent + stealth + proxy",
};

const SUBTITLE: Record<Rung, string> = {
  fetch: "free, read-only",
  agent: "live browser",
  agent_stealth: "anti-bot browser + proxy",
};

const STATE_STYLE: Record<RungState, string> = {
  pending: "border-slate-700 bg-slate-900/40 text-slate-400",
  active: "border-sky-400 bg-sky-950/60 text-sky-100 animate-pulse",
  failed: "border-rose-500 bg-rose-950/60 text-rose-100",
  passed: "border-emerald-500 bg-emerald-950/60 text-emerald-100",
  skipped: "border-dashed border-slate-700 bg-slate-900/20 text-slate-500",
};

const STATE_WORD: Record<RungState, string> = {
  pending: "not used",
  active: "running",
  failed: "failed",
  passed: "verified",
  skipped: "skipped",
};

interface Props {
  rungs: RunViewState["rungs"];
  rungChanges: RungChangeEvent[];
}

export default function LadderStepper({ rungs, rungChanges }: Props) {
  const last = rungChanges[rungChanges.length - 1];
  return (
    <div className="space-y-2">
      <ol className="flex items-stretch gap-2">
        {RUNG_ORDER.map((rung, i) => {
          const view = rungs[rung];
          const skipped = view.state === "skipped";
          return (
            <Fragment key={rung}>
              {i > 0 && (
                <li aria-hidden className="flex items-center text-2xl text-slate-600">
                  →
                </li>
              )}
              <li className={`flex-1 rounded-lg border-2 px-4 py-3 ${STATE_STYLE[view.state]}`}>
                <div className="flex items-baseline justify-between gap-2">
                  <span className={`text-lg font-semibold ${skipped ? "line-through" : ""}`}>
                    {TITLE[rung]}
                  </span>
                  <span className="text-sm font-medium uppercase tracking-wide">
                    {STATE_WORD[view.state]}
                  </span>
                </div>
                <div className="text-sm opacity-80">
                  {SUBTITLE[rung]} · {view.attempts.length} attempt
                  {view.attempts.length === 1 ? "" : "s"} · {fmtCredits(view.credits)}
                </div>
              </li>
            </Fragment>
          );
        })}
      </ol>
      {last && <p className="text-sm text-slate-400">{last.reason}</p>}
    </div>
  );
}
