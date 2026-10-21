"use client";

import { useState } from "react";

import RunView from "@/components/RunView";
import { sampleStreamUrl } from "@/lib/api";

export default function DevPage() {
  const [runKey, setRunKey] = useState(0);
  return (
    <main className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Sample run</h1>
          <p className="text-sm text-slate-400">
            Streams <code>fixtures/sample-run.jsonl</code> from <code>/dev/sample-stream</code>. No
            API keys needed.
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
      <RunView key={runKey} streamUrl={sampleStreamUrl} mode="replay" runId="sample" rawLog />
    </main>
  );
}
