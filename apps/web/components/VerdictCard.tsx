import { STATUS_LABEL, STATUS_STYLE, fmtCredits } from "@/lib/format";
import type { VerdictEvent } from "@/lib/types";

export default function VerdictCard({ verdict }: { verdict: VerdictEvent | null }) {
  if (!verdict) return null;
  return (
    <section className="space-y-2 rounded-lg border border-slate-700 bg-slate-900/60 p-5">
      <div className={`text-4xl font-bold tracking-tight ${STATUS_STYLE[verdict.status]}`}>
        {STATUS_LABEL[verdict.status]}
      </div>
      <p className="text-lg text-slate-200">{verdict.reason}</p>
      <p className="text-sm text-slate-400">
        {verdict.attempts_used} attempt{verdict.attempts_used === 1 ? "" : "s"} ·{" "}
        {fmtCredits(verdict.credits_used)}
      </p>
      {verdict.final_result && (
        <pre className="max-h-60 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-300">
          {JSON.stringify(verdict.final_result, null, 2)}
        </pre>
      )}
    </section>
  );
}
