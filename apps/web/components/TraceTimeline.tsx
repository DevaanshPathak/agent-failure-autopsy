"use client";

import { useEffect, useRef, useState } from "react";

import { KIND_ICON, RUNG_LABEL, relTime } from "@/lib/format";
import type { AttemptView } from "@/lib/runState";
import type { TraceEvent } from "@/lib/types";

interface Props {
  attempts: AttemptView[];
}

const STICK_PX = 80;

export function rowId(attemptNo: number, seq: number): string {
  return `ev-${attemptNo}-${seq}`;
}

function TraceRow({ ev, attempt }: { ev: TraceEvent; attempt: AttemptView }) {
  const [open, setOpen] = useState(false);
  const failing = ev.seq === attempt.failingSeq;
  return (
    <li
      id={rowId(attempt.attemptNo, ev.seq)}
      className={`rounded px-2 py-1.5 ${
        failing ? "border-l-4 border-rose-500 bg-rose-950" : "bg-slate-900/70"
      }`}
    >
      <div className="flex items-baseline gap-3">
        <span className="w-4 shrink-0 text-center text-slate-500" aria-hidden>
          {KIND_ICON[ev.kind]}
        </span>
        <span className="w-16 shrink-0 font-mono text-xs text-slate-500">
          {relTime(ev.ts, attempt.startedAt)}
        </span>
        <span className="w-16 shrink-0 text-sm text-slate-400">
          {ev.step_no ? `Step ${ev.step_no}` : ""}
        </span>
        <span className="flex-1 text-slate-100">{ev.label}</span>
        {failing && (
          <span className="shrink-0 text-sm font-medium text-rose-300">✕ failed here</span>
        )}
        <button
          type="button"
          className="shrink-0 text-xs text-slate-500 hover:text-slate-300"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
        >
          raw
        </button>
      </div>
      {open && (
        <pre className="mt-1.5 max-h-64 overflow-auto rounded bg-slate-950 p-2 text-xs text-slate-400">
          {JSON.stringify(ev.raw, null, 2)}
        </pre>
      )}
    </li>
  );
}

function VerifyRow({ attempt }: { attempt: AttemptView }) {
  const v = attempt.verify;
  if (!v) return null;
  return (
    <li
      className={`rounded px-3 py-2 font-medium ${
        v.passed ? "bg-emerald-950/70 text-emerald-200" : "bg-rose-950/70 text-rose-200"
      }`}
    >
      {v.passed ? "✓ " : "✕ "}
      {v.summary}
    </li>
  );
}

export default function TraceTimeline({ attempts }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const eventCount = attempts.reduce((n, a) => n + a.events.length + (a.verify ? 1 : 0), 0);

  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [eventCount]);

  return (
    <div
      ref={scroller}
      className="max-h-[70vh] space-y-4 overflow-y-auto pr-1"
      onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_PX;
      }}
    >
      {attempts.length === 0 && <p className="text-slate-500">No events yet.</p>}
      {attempts.map((attempt) => (
        <section key={attempt.attemptNo}>
          <h3 className="mb-1.5 text-sm font-semibold text-slate-300">
            Attempt {attempt.attemptNo} · {RUNG_LABEL[attempt.rung]}
          </h3>
          <ol className="space-y-1">
            {attempt.events
              .filter((ev) => ev.kind !== "heartbeat")
              .map((ev) => (
                <TraceRow key={ev.seq} ev={ev} attempt={attempt} />
              ))}
            <VerifyRow attempt={attempt} />
          </ol>
        </section>
      ))}
    </div>
  );
}
