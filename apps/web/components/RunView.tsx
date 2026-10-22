"use client";

import { useState } from "react";

import BrowserPanel from "@/components/BrowserPanel";
import BudgetMeter from "@/components/BudgetMeter";
import LadderStepper from "@/components/LadderStepper";
import TraceTimeline from "@/components/TraceTimeline";
import VerdictCard from "@/components/VerdictCard";
import { apiErrorMessages } from "@/lib/runRequest";
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
  /** Live run with a recorded trace: cancel it and open the replay (shown until the verdict). */
  onSwitchToReplay?: () => Promise<void>;
  /** Replaces the mode badge text (e.g. for the hand-written illustrative sample). */
  badgeLabel?: string;
  /** A visible note under the badge (e.g. "Hand-written example … not a live TinyFish run"). */
  note?: string;
  /** Screenshot source for BrowserPanel (bundled files in the static demo). */
  screenshotSrc?: (attemptNo: number) => string | null;
}

function ModeBadge({ mode, label }: { mode: RunMode | null; label?: string }) {
  if (!mode) return null;
  if (label) {
    return (
      <span className="rounded-full bg-violet-500/15 px-2.5 py-0.5 text-sm font-semibold text-violet-200 ring-1 ring-violet-400/40">
        {label}
      </span>
    );
  }
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

export default function RunView({
  streamUrl,
  mode,
  runId,
  header,
  rawLog = false,
  onSwitchToReplay,
  badgeLabel,
  note,
  screenshotSrc,
}: Props) {
  const { state, events, connected, error } = useRunStream(streamUrl);
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const shown = header ?? state.header;
  const current = state.attempts.find((a) => a.attemptNo === state.currentAttempt) ?? null;

  async function switchToReplay() {
    if (!onSwitchToReplay) return;
    setSwitching(true);
    setSwitchError(null);
    try {
      await onSwitchToReplay();
    } catch (err) {
      setSwitchError(apiErrorMessages(err)[0]);
      setSwitching(false);
    }
  }

  return (
    <div className="space-y-4" data-run-id={runId}>
      <div className="flex flex-wrap items-start justify-between gap-4 rounded-lg border border-slate-800 bg-slate-900/50 p-4">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-3">
            <ModeBadge mode={mode} label={badgeLabel} />
            {!connected && !state.done && (
              <span className="rounded-full bg-slate-800 px-2.5 py-0.5 text-sm text-slate-300">
                {state.lastSeq ? "Reconnecting…" : "Connecting…"}
              </span>
            )}
            {error && <span className="text-sm text-rose-300">{error}</span>}
          </div>
          {note && (
            <p className="rounded border border-violet-400/40 bg-violet-950/40 px-2 py-1 text-sm text-violet-100">
              {note}
            </p>
          )}
          <p className="truncate font-mono text-sm text-slate-400" title={shown?.url}>
            {shown?.url ?? "…"}
          </p>
          <p className="break-words text-lg text-slate-100">{shown?.goal ?? ""}</p>
        </div>
        <div className="flex flex-col items-end gap-3">
          <BudgetMeter budget={state.budget} />
          {onSwitchToReplay && !state.done && (
            <button
              type="button"
              onClick={() => void switchToReplay()}
              disabled={switching}
              className="rounded-md bg-amber-500/20 px-3 py-1.5 font-semibold text-amber-200 ring-1 ring-amber-400/50 hover:bg-amber-500/30 disabled:opacity-60"
            >
              {switching ? "Switching…" : "Switch to replay"}
            </button>
          )}
          {switchError && <span className="text-sm text-rose-300">{switchError}</span>}
        </div>
      </div>

      <LadderStepper rungs={state.rungs} rungChanges={state.rungChanges} />

      <div className="grid gap-4 lg:grid-cols-12">
        <div className="min-w-0 space-y-4 lg:col-span-7">
          <BrowserPanel
            liveView={state.liveView}
            attempt={current}
            mode={mode}
            runId={runId}
            screenshotSrc={screenshotSrc}
          />
          {state.done && <VerdictCard verdict={state.verdict} />}
        </div>
        <div className="min-w-0 lg:col-span-5">
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
