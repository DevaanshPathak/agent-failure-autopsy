"use client";

import { useEffect, useState } from "react";

import ResultsTable from "@/components/ResultsTable";
import StatsTiles from "@/components/StatsTiles";
import { DEMO_MODE, getStats } from "@/lib/api";
import { demoIdFromRunId, demoStats, loadDemoIndex, type DemoRun } from "@/lib/demoIndex";
import { apiErrorMessages } from "@/lib/runRequest";
import type { Stats } from "@/lib/types";

const POLL_MS = 10_000;

export default function ResultsPage() {
  return DEMO_MODE ? <DemoResults /> : <LiveResults />;
}

function ErrorBanner({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-amber-500/50 bg-amber-950/40 p-3 text-amber-200"
    >
      {children}
    </div>
  );
}

/** The API's /stats, polled every 10 s. */
function LiveResults() {
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
        <ErrorBanner>
          Can&apos;t load results: {error}
          {stats ? " Showing the last numbers we got." : ""}
        </ErrorBanner>
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

/** Static demo: the same numbers, computed in the browser from the bundled runs. */
function DemoResults() {
  const [runs, setRuns] = useState<DemoRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadDemoIndex()
      .then((index) => {
        if (!cancelled) setRuns(index.runs);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const stats = runs ? demoStats(runs) : null;
  const samples = runs?.filter((r) => r.kind === "sample").length ?? 0;
  const recordings = runs?.filter((r) => r.kind === "recording").length ?? 0;
  const kindOf = new Map(runs?.map((r) => [r.id, r.kind]) ?? []);

  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Results · bundled demo runs</h1>
        <p className="text-slate-400">
          Computed in your browser from the runs bundled with this demo deployment, with the same
          definitions as the live results page. These are not live results.
        </p>
        {runs && (
          <p className="mt-1 text-sm text-slate-300">
            {recordings} recorded run{recordings === 1 ? "" : "s"}
            {samples > 0 &&
              ` + ${samples} hand-written illustrative sample${samples === 1 ? "" : "s"}`}
            .
          </p>
        )}
      </div>

      {error && <ErrorBanner>Can&apos;t load the bundled runs: {error}</ErrorBanner>}

      <StatsTiles stats={stats} />
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Bundled runs</h2>
        {stats ? (
          <ResultsTable
            rows={stats.rows}
            emptyText="No runs are bundled with this deployment."
            rowNote={(row) => {
              const id = demoIdFromRunId(row.run_id);
              return id && kindOf.get(id) === "sample"
                ? "illustrative sample · hand-written, not a live run"
                : null;
            }}
          />
        ) : (
          <p className="text-slate-400">{error ? "No data." : "Loading…"}</p>
        )}
      </section>
    </main>
  );
}
