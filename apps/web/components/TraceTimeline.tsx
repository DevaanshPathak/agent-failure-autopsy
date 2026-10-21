"use client";

import { useEffect, useRef, useState } from "react";

import DiagnosisCard from "@/components/DiagnosisCard";
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

/** Chips describing how an attempt was configured (browser, proxy, cache, patches). */
export function attemptChips(a: AttemptView): string[] {
  const chips: string[] = [];
  if (a.rung !== "fetch") chips.push(a.config.browser_profile);
  if (a.config.proxy_enabled) chips.push(`proxy ${a.config.proxy_country ?? ""}`.trim());
  if (a.config.from_fetch_cache) chips.push("cached Fetch · 0 credits");
  return [...chips, ...a.config.patches_applied];
}

function Chip({ text }: { text: string }) {
  return (
    <span
      title={text}
      className="max-w-[18rem] truncate rounded bg-slate-800 px-1.5 py-0.5 text-sm text-slate-200"
    >
      {text}
    </span>
  );
}

function TraceRow({ ev, attempt }: { ev: TraceEvent; attempt: AttemptView }) {
  const [open, setOpen] = useState(false);
  const failing = ev.seq === attempt.failingSeq;
  return (
    <li
      id={rowId(attempt.attemptNo, ev.seq)}
      className={`scroll-mt-4 rounded px-2 py-1.5 ${
        failing ? "animate-fail-flash border-l-4 border-rose-500 bg-rose-950" : "bg-slate-900/70"
      }`}
    >
      <div className="flex items-baseline gap-3">
        <span className="w-4 shrink-0 text-center text-slate-400" aria-hidden>
          {KIND_ICON[ev.kind]}
        </span>
        <span className="w-[4.5rem] shrink-0 font-mono text-sm text-slate-400">
          {relTime(ev.ts, attempt.startedAt)}
        </span>
        <span className="min-w-0 flex-1 break-words text-slate-100">
          {ev.step_no ? (
            <span className="mr-2 text-sm font-medium text-slate-400">Step {ev.step_no}</span>
          ) : null}
          {ev.label}
        </span>
        {failing && (
          <span className="shrink-0 text-sm font-medium text-rose-300">✕ failed here</span>
        )}
        <button
          type="button"
          className="shrink-0 text-sm text-slate-400 hover:text-slate-200"
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
  const [open, setOpen] = useState(false);
  const v = attempt.verify;
  if (!v) return null;
  return (
    <li
      className={`rounded px-3 py-2 ${
        v.passed ? "bg-emerald-950/70 text-emerald-200" : "bg-rose-950/70 text-rose-200"
      }`}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="w-full text-left font-medium"
      >
        {v.passed ? "✓ " : "✕ "}
        {v.summary}
        <span className="ml-2 text-sm font-normal opacity-80">{open ? "hide" : "details"}</span>
      </button>
      {open && (
        <div className="mt-2 space-y-2 text-sm">
          <ul className="space-y-0.5">
            {v.checks.map((c) => (
              <li key={c.name} className={c.passed ? "text-emerald-200" : "text-rose-200"}>
                {c.passed ? "✓" : "✕"} <span className="font-mono">{c.name}</span>: {c.detail}
              </li>
            ))}
          </ul>
          {v.block_signals.length > 0 && (
            <div>
              <div className="text-sm font-semibold uppercase tracking-wide opacity-80">
                Block signals
              </div>
              <ul className="space-y-0.5">
                {v.block_signals.map((s, i) => (
                  <li key={i} className="text-slate-200">
                    <span className="font-mono">{s.kind}</span> in {s.where}: “{s.evidence}”
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

const STATUS_ICON: Record<AttemptView["status"], string> = {
  running: "…",
  passed: "✓",
  failed: "✕",
};

export default function TraceTimeline({ attempts }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const pendingJump = useRef<{ attemptNo: number; seq: number } | null>(null);
  const seenFailing = useRef(new Set<string>());
  /** While a failing step is being shown, following the newest event waits (ms timestamp). */
  const holdUntil = useRef(0);
  /** Scroll events before this time come from our own scrolling, not the user. */
  const programmaticUntil = useRef(0);
  const [overrides, setOverrides] = useState<Record<number, boolean>>({});

  const latest = attempts.length ? attempts[attempts.length - 1].attemptNo : null;
  const isOpen = (n: number) => overrides[n] ?? n === latest;
  const eventCount = attempts.reduce((n, a) => n + a.events.length + (a.verify ? 1 : 0), 0);
  const failingRows = attempts
    .filter((a) => a.failingSeq !== null && isOpen(a.attemptNo))
    .map((a) => rowId(a.attemptNo, a.failingSeq as number))
    .join("|");

  // Follow the newest event unless the user scrolled up; wait while a failing step is shown.
  useEffect(() => {
    const el = scroller.current;
    if (!el || !stick.current) return;
    const toBottom = () => {
      programmaticUntil.current = performance.now() + 300;
      el.scrollTop = el.scrollHeight;
    };
    const wait = holdUntil.current - performance.now();
    if (wait <= 0) {
      toBottom();
      return;
    }
    const timer = window.setTimeout(() => {
      if (stick.current) toBottom();
    }, wait);
    return () => window.clearTimeout(timer);
  }, [eventCount]);

  // When a diagnosis arrives, bring its (red, flashing) failing step into view once.
  useEffect(() => {
    for (const id of failingRows ? failingRows.split("|") : []) {
      if (seenFailing.current.has(id)) continue;
      seenFailing.current.add(id);
      holdUntil.current = performance.now() + 2500;
      programmaticUntil.current = performance.now() + 1000;
      document.getElementById(id)?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [failingRows]);

  // Runs after every render: performs a requested jump once its group is expanded.
  useEffect(() => {
    const jump = pendingJump.current;
    if (!jump) return;
    pendingJump.current = null;
    document
      .getElementById(rowId(jump.attemptNo, jump.seq))
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
  });

  function jumpTo(attemptNo: number, seq: number) {
    stick.current = false;
    pendingJump.current = { attemptNo, seq };
    setOverrides((o) => ({ ...o, [attemptNo]: true }));
  }

  return (
    <div
      ref={scroller}
      className="max-h-[70vh] space-y-4 overflow-y-auto pr-1"
      onScroll={(e) => {
        if (performance.now() < programmaticUntil.current) return;
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_PX;
      }}
    >
      {attempts.length === 0 && <p className="text-slate-400">No events yet.</p>}
      {attempts.map((attempt) => {
        const open = isOpen(attempt.attemptNo);
        const failing = attempt.events.find((e) => e.seq === attempt.failingSeq);
        return (
          <section
            key={attempt.attemptNo}
            className="rounded-lg border border-slate-800 bg-slate-950/40 p-2"
          >
            <button
              type="button"
              onClick={() => setOverrides((o) => ({ ...o, [attempt.attemptNo]: !open }))}
              aria-expanded={open}
              className="mb-1.5 flex w-full flex-wrap items-center gap-2 text-left"
            >
              <span className="text-sm font-semibold text-slate-200">
                {STATUS_ICON[attempt.status]} Attempt {attempt.attemptNo} ·{" "}
                {RUNG_LABEL[attempt.rung]}
              </span>
              {attemptChips(attempt).map((chip) => (
                <Chip key={chip} text={chip} />
              ))}
              <span className="ml-auto text-sm text-slate-400">{open ? "collapse" : "expand"}</span>
            </button>
            <ol className="space-y-1">
              {open &&
                attempt.events
                  .filter((ev) => ev.kind !== "heartbeat")
                  .map((ev) => <TraceRow key={ev.seq} ev={ev} attempt={attempt} />)}
              <VerifyRow attempt={attempt} />
            </ol>
            {/* The diagnosis stays visible when the attempt collapses: it is the story. */}
            {attempt.diagnosis && (
              <div className="mt-2">
                <DiagnosisCard
                  diagnosis={attempt.diagnosis}
                  failingStepNo={failing?.step_no ?? null}
                  onJumpToStep={(seq) => jumpTo(attempt.attemptNo, seq)}
                  rung={attempt.rung}
                  nextConfig={
                    attempts.find((a) => a.attemptNo === attempt.attemptNo + 1)?.config ?? null
                  }
                />
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
