"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import RunView from "@/components/RunView";
import { ApiError, getRun, streamUrl } from "@/lib/api";
import { apiErrorMessages } from "@/lib/runRequest";
import type { Run } from "@/lib/types";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; run: Run }
  | { kind: "missing" }
  | { kind: "error"; message: string };

export default function RunLoader({ runId }: { runId: string }) {
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    getRun(runId)
      .then((run) => {
        if (!cancelled) setLoad({ kind: "ready", run });
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
  if (load.kind === "error") return <p className="text-rose-300">{load.message}</p>;

  const { run } = load;
  return (
    <RunView
      streamUrl={streamUrl(run.id)}
      mode={run.mode}
      runId={run.id}
      header={{ url: run.request.url, goal: run.request.goal }}
    />
  );
}
