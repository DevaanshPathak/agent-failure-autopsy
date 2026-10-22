"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  SAMPLE_NOTE,
  demoRunId,
  loadDemoIndex,
  orderForDisplay,
  type DemoRun,
} from "@/lib/demoIndex";
import { CLASS_COLOR, CLASS_LABEL, STATUS_LABEL, STATUS_STYLE, fmtCredits } from "@/lib/format";

function RunCard({ run }: { run: DemoRun }) {
  const sample = run.kind === "sample";
  return (
    <article className="flex flex-col gap-3 rounded-lg border border-slate-700 bg-slate-900/60 p-5">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span
          className={`rounded-full px-2.5 py-0.5 font-semibold ring-1 ${
            sample
              ? "bg-violet-500/15 text-violet-200 ring-violet-400/40"
              : "bg-amber-500/15 text-amber-200 ring-amber-400/40"
          }`}
        >
          {sample ? "Illustrative sample" : "Recording"}
        </span>
        {run.status && (
          <span className={`font-semibold ${STATUS_STYLE[run.status]}`}>
            {STATUS_LABEL[run.status]}
          </span>
        )}
      </div>
      <h3 className="text-xl font-semibold text-slate-50">{run.title}</h3>
      {sample && (
        <p className="rounded border border-violet-400/40 bg-violet-950/40 px-2 py-1 text-sm text-violet-100">
          {SAMPLE_NOTE}
        </p>
      )}
      {run.url && (
        <p className="truncate font-mono text-sm text-slate-400" title={run.url}>
          {run.url}
        </p>
      )}
      {run.goal && <p className="text-slate-200">{run.goal}</p>}
      {run.classes.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          {run.classes.map((c, i) => (
            <span key={`${c}-${i}`} className="flex items-center gap-1.5">
              {i > 0 && <span className="text-slate-400">→</span>}
              <span className={`rounded px-2 py-0.5 ${CLASS_COLOR[c]}`}>{CLASS_LABEL[c]}</span>
            </span>
          ))}
        </div>
      )}
      <p className="text-sm text-slate-400">
        {run.attempts_used} attempt{run.attempts_used === 1 ? "" : "s"} ·{" "}
        {fmtCredits(run.credits_used)}
        {run.baseline_credits_estimate !== null &&
          ` · naive baseline ${fmtCredits(run.baseline_credits_estimate)}`}
      </p>
      <Link
        href={`/runs/${demoRunId(run.id)}`}
        className="mt-auto self-start rounded-md bg-sky-600 px-6 py-3 text-lg font-semibold text-white hover:bg-sky-500"
      >
        ▶ Play
      </Link>
    </article>
  );
}

/** The runs bundled with the static demo, each playable in the browser. */
export default function DemoRunPicker() {
  const [runs, setRuns] = useState<DemoRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadDemoIndex()
      .then((index) => {
        if (!cancelled) setRuns(orderForDisplay(index.runs));
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <p className="text-rose-300">Can&apos;t load the bundled runs: {error}</p>;
  if (!runs) return <p className="animate-pulse text-slate-400">Loading bundled runs…</p>;
  if (runs.length === 0) return <p className="text-slate-400">No runs are bundled yet.</p>;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {runs.map((run) => (
        <RunCard key={run.id} run={run} />
      ))}
    </div>
  );
}
