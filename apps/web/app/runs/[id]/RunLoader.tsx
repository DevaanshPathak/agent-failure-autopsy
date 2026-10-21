"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import RunView from "@/components/RunView";
import { ApiError, cancelRun, createRun, getRun, getSites, streamUrl } from "@/lib/api";
import { apiErrorMessages } from "@/lib/runRequest";
import type { Run } from "@/lib/types";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; run: Run; hasTrace: boolean }
  | { kind: "missing" }
  | { kind: "error"; message: string };

/** Does the run's demo site have a recorded trace to fall back to? */
async function siteHasTrace(siteId: string | null): Promise<boolean> {
  if (!siteId) return false;
  try {
    return (await getSites()).some((s) => s.id === siteId && s.has_trace);
  } catch {
    return false;
  }
}

export default function RunLoader({ runId }: { runId: string }) {
  const router = useRouter();
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    getRun(runId)
      .then(async (run) => {
        const hasTrace = run.mode === "live" ? await siteHasTrace(run.request.site_id) : false;
        if (!cancelled) setLoad({ kind: "ready", run, hasTrace });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) setLoad({ kind: "missing" });
        else setLoad({ kind: "error", message: apiErrorMessages(err)[0] });
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  if (load.kind === "loading") return <p className="animate-pulse text-slate-400">Loading run…</p>;
  if (load.kind === "missing") {
    return (
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Run not found</h1>
        <Link href="/" className="text-sky-300 underline underline-offset-4">
          Start a new run
        </Link>
      </div>
    );
  }
  if (load.kind === "error") {
    return (
      <div className="space-y-2">
        <p className="text-rose-300">Can&apos;t load this run: {load.message}</p>
        <Link href="/" className="text-sky-300 underline underline-offset-4">
          Back to the run form
        </Link>
      </div>
    );
  }

  const { run, hasTrace } = load;

  // Stop the live run (frees TinyFish and the live-run slot), then replay the recording.
  async function switchToReplay() {
    try {
      await cancelRun(run.id);
    } catch (err) {
      // 409 = already finished. Anything else: the replay still matters more on stage.
      if (!(err instanceof ApiError && err.status === 409)) {
        console.warn("Could not cancel the live run before replaying", err);
      }
    }
    const created = await createRun({ ...run.request, mode: "replay" });
    router.push(`/runs/${encodeURIComponent(created.run_id)}`);
  }

  return (
    <RunView
      streamUrl={streamUrl(run.id)}
      mode={run.mode}
      runId={run.id}
      header={{ url: run.request.url, goal: run.request.goal }}
      onSwitchToReplay={run.mode === "live" && hasTrace ? switchToReplay : undefined}
    />
  );
}
