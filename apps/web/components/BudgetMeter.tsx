import type { BudgetEvent } from "@/lib/types";

function barColor(ratio: number): string {
  if (ratio >= 1) return "bg-rose-500";
  if (ratio >= 0.75) return "bg-amber-400";
  return "bg-sky-500";
}

function Bar({ label, used, max }: { label: string; used: number; max: number }) {
  const ratio = max > 0 ? used / max : 1;
  return (
    <div className="w-44">
      <div className="flex justify-between text-xs text-slate-400">
        <span>{label}</span>
        <span className="font-mono text-slate-200">
          {used}/{max}
        </span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div
          className={`h-full rounded-full ${barColor(ratio)}`}
          style={{ width: `${Math.min(ratio, 1) * 100}%` }}
        />
      </div>
    </div>
  );
}

export default function BudgetMeter({ budget }: { budget: BudgetEvent | null }) {
  if (!budget) return null;
  return (
    <div className="flex gap-5" aria-label="Budget">
      <Bar label="attempts" used={budget.attempts_used} max={budget.max_attempts} />
      <Bar label="credits (est.)" used={budget.credits_used} max={budget.max_credits} />
    </div>
  );
}
