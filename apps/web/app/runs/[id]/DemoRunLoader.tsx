"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import RunView from "@/components/RunView";
import {
  SAMPLE_NOTE,
  demoRunId,
  demoScreenshotUrl,
  demoStreamUrl,
  loadDemoIndex,
  type DemoRun,
} from "@/lib/demoIndex";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; run: DemoRun }
  | { kind: "missing" }
  | { kind: "error"; message: string };

function BackLink() {
  return (
    <Link href="/" className="text-sky-300 underline underline-offset-4">
      Back to the bundled runs
    </Link>
  );
}

/** A bundled run (`/runs/demo-<id>`), played in the browser without any API call. */
export default function DemoRunLoader({ demoId }: { demoId: string }) {
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    loadDemoIndex()
      .then((index) => {
        if (cancelled) return;
        const run = index.runs.find((r) => r.id === demoId);
        setLoad(run ? { kind: "ready", run } : { kind: "missing" });
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoad({ kind: "error", message: String(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [demoId]);

  if (load.kind === "loading") return <p className="animate-pulse text-slate-400">Loading run…</p>;
  if (load.kind === "missing") {
    return (
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">No bundled run called “{demoId}”</h1>
        <BackLink />
      </div>
    );
  }
  if (load.kind === "error") {
    return (
      <div className="space-y-2">
        <p className="text-rose-300">Can&apos;t load the bundled runs: {load.message}</p>
        <BackLink />
      </div>
    );
  }

  const { run } = load;
  const sample = run.kind === "sample";
  return (
    <RunView
      streamUrl={demoStreamUrl(run.id)}
      mode="replay"
      runId={demoRunId(run.id)}
      header={run.url && run.goal ? { url: run.url, goal: run.goal } : null}
      badgeLabel={sample ? "ILLUSTRATIVE SAMPLE" : undefined}
      note={sample ? SAMPLE_NOTE : undefined}
      screenshotSrc={(n) =>
        run.screenshot_attempts.includes(n) ? demoScreenshotUrl(run.id, n) : null
      }
    />
  );
}

/** Any non-bundled run id on the static demo deployment. */
export function DemoOnlyNotice() {
  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold">Only bundled runs are available here</h1>
      <p className="text-slate-300">
        This is the static demo deployment: it replays bundled runs in your browser. Live runs need
        the API, which isn&apos;t part of this deployment.
      </p>
      <BackLink />
    </div>
  );
}
