import { Suspense } from "react";

import { DEMO_MODE } from "@/lib/api";
import { demoIdFromRunId } from "@/lib/demoIndex";

import DemoRunLoader, { DemoOnlyNotice } from "./DemoRunLoader";
import RunLoader from "./RunLoader";

function RunFor({ id }: { id: string }) {
  const demoId = demoIdFromRunId(id);
  if (demoId !== null) return <DemoRunLoader demoId={demoId} />;
  if (DEMO_MODE) return <DemoOnlyNotice />;
  return <RunLoader runId={id} />;
}

// With Cache Components, dynamic params are runtime data and must be read inside Suspense.
export default function RunPage({ params }: PageProps<"/runs/[id]">) {
  return (
    <Suspense fallback={<p className="animate-pulse text-slate-400">Loading run…</p>}>
      {params.then(({ id }) => (
        <RunFor id={id} />
      ))}
    </Suspense>
  );
}
