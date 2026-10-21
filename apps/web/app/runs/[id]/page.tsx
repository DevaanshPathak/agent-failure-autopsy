import { Suspense } from "react";

import RunLoader from "./RunLoader";

// With Cache Components, dynamic params are runtime data and must be read inside Suspense.
export default function RunPage({ params }: PageProps<"/runs/[id]">) {
  return (
    <Suspense fallback={<p className="animate-pulse text-slate-400">Loading run…</p>}>
      {params.then(({ id }) => (
        <RunLoader runId={id} />
      ))}
    </Suspense>
  );
}
