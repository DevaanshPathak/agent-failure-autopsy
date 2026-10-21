"use client";

import BrowserPanel from "@/components/BrowserPanel";
import BudgetMeter from "@/components/BudgetMeter";
import LadderStepper from "@/components/LadderStepper";
import TraceTimeline from "@/components/TraceTimeline";
import VerdictCard from "@/components/VerdictCard";
import { useRunStream } from "@/lib/useRunStream";
import type { RunMode } from "@/lib/types";

interface Props {
  streamUrl: string;
  mode: RunMode | null;
  runId: string;
  /** Known before the stream starts (from GET /runs/{id}); the stream fills it in otherwise. */
  header?: { url: string; goal: string } | null;
  /** Show a collapsible log of every UI event (used by /dev). */
  rawLog?: boolean;
}

function ModeBadge({ mode }: { mode: RunMode | null }) {
  if (!mode) return null;
  return mode === "live" ? (
    <span className="rounded-full bg-emerald-500/15 px-2.5 py-0.5 text-sm font-semibold text-emerald-300 ring-1 ring-emerald-400/40">
      LIVE
    </span>
  ) : (
    <span className="rounded-full bg-amber-500/15 px-2.5 py-0.5 text-sm font-semibold text-amber-300 ring-1 ring-amber-400/40">
      REPLAY · recorded trace
    </span>
  );
}

export default function RunView({ streamUrl, mode, runId, header, rawLog = false }: Props) {
  const { state, events, connected, error } = useRunStream(streamUrl);
  const shown = header ?? state.header;
  const current = state.attempts.find((a) => a.attemptNo === state.currentAttempt) ?? null;

  return (
    <div className="space-y-4" data-run-id={runId}>
      <div className="flex flex-wrap items-start justify-between gap-4 rounded-lg border border-slate-800 bg-slate-900/50 p-4">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-3">
            <ModeBadge mode={mode} />
            {!connected && !state.done && (
              <span className="rounded-full bg-slate-800 px-2.5 py-0.5 text-sm text-slate-300">
                {state.lastSeq ? "Reconnecting…" : "Connecting…"}
              </span>
            )}
            {error && <span className="text-sm text-rose-300">{error}</span>}
          </div>
          <p className="truncate font-mono text-sm text-slate-400">{shown?.url ?? "…"}</p>
          <p className="text-lg text-slate-100">{shown?.goal ?? ""}</p>
        </div>
        <BudgetMeter budget={state.budget} />
      </div>

      <LadderStepper rungs={state.rungs} rungChanges={state.rungChanges} />

      <div className="grid gap-4 lg:grid-cols-12">
        <div className="space-y-4 lg:col-span-7">
          <BrowserPanel liveView={state.liveView} attempt={current} mode={mode} />
          {state.done && <VerdictCard verdict={state.verdict} />}
        </div>
        <div className="lg:col-span-5">
          <TraceTimeline attempts={state.attempts} />
        </div>
      </div>

      {rawLog && (
        <details className="rounded-lg border border-slate-800 p-3">
          <summary className="cursor-pointer text-sm text-slate-300">
            Raw UI events ({events.length})
          </summary>
          <pre className="mt-2 max-h-96 overflow-auto text-xs text-slate-400">
            {events.map((ev) => JSON.stringify(ev)).join("\n")}
          </pre>
        </details>
      )}
    </div>
  );
}
