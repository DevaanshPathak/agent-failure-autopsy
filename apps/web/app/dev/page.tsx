"use client";

import { useState } from "react";

import { sampleStreamUrl } from "@/lib/api";
import {
  CLASS_COLOR,
  CLASS_LABEL,
  RUNG_LABEL,
  RUNG_ORDER,
  STATUS_LABEL,
  STATUS_STYLE,
  fmtCredits,
  relTime,
} from "@/lib/format";
import type { RungState } from "@/lib/runState";
import { useRunStream } from "@/lib/useRunStream";

const RUNG_STATE_STYLE: Record<RungState, string> = {
  pending: "border-slate-700 text-slate-400",
  active: "border-sky-400 text-sky-200",
  failed: "border-rose-500 text-rose-200",
  passed: "border-emerald-500 text-emerald-200",
  skipped: "border-slate-700 text-slate-500 line-through",
};

export default function DevPage() {
  const [runKey, setRunKey] = useState(0);
  return (
    <main className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Sample run</h1>
          <p className="text-sm text-slate-400">
            Streams <code>fixtures/sample-run.jsonl</code> from <code>/dev/sample-stream</code>. No
            API keys needed. Temporary view until the run components land in Phases 2–4.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setRunKey((k) => k + 1)}
          className="rounded-md bg-slate-800 px-3 py-1.5 text-sm hover:bg-slate-700"
        >
          Restart sample
        </button>
      </div>
      <SampleRun key={runKey} />
    </main>
  );
}

function SampleRun() {
  const { state, events, connected, error } = useRunStream(sampleStreamUrl);
  const { budget, verdict } = state;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span
          className={`rounded-full px-2.5 py-0.5 ${
            connected ? "bg-emerald-500/15 text-emerald-300" : "bg-slate-800 text-slate-400"
          }`}
        >
          {connected ? "streaming" : state.done ? "finished" : "connecting…"}
        </span>
        <span className="text-slate-400">{events.length} events</span>
        {budget && (
          <span className="text-slate-300">
            attempts {budget.attempts_used}/{budget.max_attempts} · credits {budget.credits_used}/
            {budget.max_credits} (est.)
          </span>
        )}
        {error && <span className="text-rose-300">{error}</span>}
      </div>

      {state.header && (
        <div className="rounded-lg border border-slate-800 p-3 text-sm">
          <div className="font-mono text-slate-300">{state.header.url}</div>
          <div className="text-slate-100">{state.header.goal}</div>
        </div>
      )}

      <ol className="grid grid-cols-3 gap-2">
        {RUNG_ORDER.map((rung) => {
          const view = state.rungs[rung];
          return (
            <li key={rung} className={`rounded-lg border-2 p-3 ${RUNG_STATE_STYLE[view.state]}`}>
              <div className="font-medium">{RUNG_LABEL[rung]}</div>
              <div className="text-sm">
                {view.state} · {view.attempts.length} attempts · {fmtCredits(view.credits)}
              </div>
            </li>
          );
        })}
      </ol>

      {state.attempts.map((attempt) => (
        <section key={attempt.attemptNo} className="rounded-lg border border-slate-800 p-3">
          <h2 className="font-medium">
            Attempt {attempt.attemptNo} · {RUNG_LABEL[attempt.rung]} · {attempt.status}
          </h2>
          <ul className="mt-2 space-y-1 text-sm">
            {attempt.events.map((ev) => (
              <li
                key={ev.seq}
                className={`flex gap-3 rounded px-2 py-1 ${
                  ev.seq === attempt.failingSeq
                    ? "border-l-4 border-rose-500 bg-rose-950"
                    : "bg-slate-900"
                }`}
              >
                <span className="w-14 shrink-0 font-mono text-slate-500">
                  {relTime(ev.ts, attempt.startedAt)}
                </span>
                <span className="w-24 shrink-0 text-slate-400">
                  {ev.step_no ? `Step ${ev.step_no}` : ev.kind}
                </span>
                <span>{ev.label}</span>
                {ev.seq === attempt.failingSeq && (
                  <span className="ml-auto text-rose-300">✕ failed here</span>
                )}
              </li>
            ))}
          </ul>
          {attempt.verify && (
            <p
              className={`mt-2 text-sm ${
                attempt.verify.passed ? "text-emerald-300" : "text-rose-300"
              }`}
            >
              {attempt.verify.passed ? "✓ " : "✕ "}
              {attempt.verify.summary}
            </p>
          )}
          {attempt.diagnosis && (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
              <span
                className={`rounded px-2 py-0.5 ${CLASS_COLOR[attempt.diagnosis.failure_class]}`}
              >
                {CLASS_LABEL[attempt.diagnosis.failure_class]}
              </span>
              <span className="text-slate-300">{attempt.diagnosis.explanation}</span>
            </div>
          )}
        </section>
      ))}

      {verdict && (
        <section className="rounded-lg border border-slate-700 p-4">
          <div className={`text-3xl font-bold ${STATUS_STYLE[verdict.status]}`}>
            {STATUS_LABEL[verdict.status]}
          </div>
          <p className="text-slate-300">{verdict.reason}</p>
          <p className="text-sm text-slate-400">
            {verdict.attempts_used} attempts · {fmtCredits(verdict.credits_used)}
            {verdict.baseline_credits_estimate !== null &&
              ` · naive baseline ${fmtCredits(verdict.baseline_credits_estimate)}`}
          </p>
        </section>
      )}

      <details className="rounded-lg border border-slate-800 p-3">
        <summary className="cursor-pointer text-sm text-slate-300">Raw UI events</summary>
        <pre className="mt-2 max-h-96 overflow-auto text-xs text-slate-400">
          {events.map((ev) => JSON.stringify(ev)).join("\n")}
        </pre>
      </details>
    </div>
  );
}
