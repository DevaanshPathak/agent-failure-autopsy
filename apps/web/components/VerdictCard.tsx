import { STATUS_LABEL, STATUS_STYLE, fmtCredits } from "@/lib/format";
import type { RunStatus, VerdictEvent } from "@/lib/types";

const CARD_STYLE: Partial<Record<RunStatus, string>> = {
  verified: "border-emerald-500/60 bg-emerald-950/40",
  unrecoverable: "border-rose-500/60 bg-rose-950/40",
  budget_exhausted: "border-amber-500/60 bg-amber-950/30",
  error: "border-rose-500/60 border-dashed bg-slate-900/60",
  cancelled: "border-slate-600 bg-slate-900/60",
};

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="text-lg font-semibold text-slate-100">{value}</div>
    </div>
  );
}

export default function VerdictCard({ verdict }: { verdict: VerdictEvent | null }) {
  if (!verdict) return null;
  const baseline = verdict.baseline_credits_estimate;
  const saved = baseline !== null ? baseline - verdict.credits_used : null;
  return (
    <section
      className={`space-y-3 rounded-lg border-2 p-5 ${CARD_STYLE[verdict.status] ?? "border-slate-700"}`}
    >
      <div className={`text-5xl font-extrabold tracking-tight ${STATUS_STYLE[verdict.status]}`}>
        {STATUS_LABEL[verdict.status]}
      </div>
      <p className="text-lg text-slate-100">{verdict.reason}</p>
      <div className="flex flex-wrap gap-8">
        <Stat label="Attempts" value={String(verdict.attempts_used)} />
        <Stat label="Credits used" value={fmtCredits(verdict.credits_used)} />
        {baseline !== null && (
          <Stat label="Naive baseline (3× stealth)" value={fmtCredits(baseline)} />
        )}
        {saved !== null && saved > 0 && <Stat label="Saved" value={fmtCredits(saved)} />}
      </div>
      {verdict.final_result && (
        <pre className="max-h-60 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-300">
          {JSON.stringify(verdict.final_result, null, 2)}
        </pre>
      )}
    </section>
  );
}
