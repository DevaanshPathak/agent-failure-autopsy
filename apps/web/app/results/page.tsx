"use client";

import { useEffect, useState } from "react";

import ResultsTable from "@/components/ResultsTable";
import StatsTiles from "@/components/StatsTiles";
import { getStats } from "@/lib/api";
import { apiErrorMessages } from "@/lib/runRequest";
import type { Stats } from "@/lib/types";

const POLL_MS = 10_000;

export default function ResultsPage() {
  const [includeReplay, setIncludeReplay] = useState(false);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      getStats(includeReplay)
        .then((s) => {
          if (cancelled) return;
          setStats(s);
          setError(null);
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(apiErrorMessages(err)[0]);
        });
    void load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [includeReplay]);

  return (
    <main className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Results</h1>
          <p className="text-slate-400">
            Every run today: what failed, what we fixed, where we stopped honestly, and what it
            cost. Refreshes every 10 s.
          </p>
        </div>
        <label className="flex items-center gap-2 text-slate-200">
          <input
            type="checkbox"
            checked={includeReplay}
            onChange={(e) => setIncludeReplay(e.target.checked)}
          />
          Include recorded (replay) runs
        </label>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-amber-500/50 bg-amber-950/40 p-3 text-amber-200"
        >
          Can&apos;t load results: {error}
          {stats ? " Showing the last numbers we got." : ""}
        </div>
      )}

      <StatsTiles stats={stats} />
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Runs</h2>
        {stats ? (
          <ResultsTable rows={stats.rows ?? []} />
        ) : (
          <p className="text-slate-400">{error ? "No data." : "Loading…"}</p>
        )}
      </section>
    </main>
  );
}
