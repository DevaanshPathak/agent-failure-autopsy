import { CLASS_COLOR, CLASS_LABEL } from "@/lib/format";
import { patchChips } from "@/lib/patchDiff";
import type { AttemptConfig, Diagnosis, DiagnosisSource, EvidenceSource, Rung } from "@/lib/types";

const SOURCE_LABEL: Record<DiagnosisSource, string> = {
  rules: "rules",
  llm: "Claude",
  rules_fallback: "rules fallback",
};

const EVIDENCE_LABEL: Record<EvidenceSource, string> = {
  trace: "trace",
  result: "result",
  fetch_text: "page text",
  verifier: "verifier",
  tinyfish_error: "TinyFish error",
};

interface Props {
  diagnosis: Diagnosis;
  /** Scroll the timeline to a trace event of this attempt. */
  onJumpToStep?: (seq: number) => void;
  /** Step number of the failing event, when it is a progress step. */
  failingStepNo?: number | null;
  /** Rung the diagnosed attempt ran on (for the patch diff). */
  rung: Rung;
  /** Config of the attempt this patch produced, once it has started. */
  nextConfig?: AttemptConfig | null;
}

function AddedLine({ text }: { text: string }) {
  return (
    <div className="flex gap-2 rounded bg-emerald-950/60 px-2 py-1 font-mono text-sm text-emerald-200">
      <span aria-hidden className="select-none text-emerald-400">
        +
      </span>
      <span className="min-w-0 break-words">{text}</span>
    </div>
  );
}

export default function DiagnosisCard({
  diagnosis: d,
  onJumpToStep,
  failingStepNo,
  rung,
  nextConfig,
}: Props) {
  const { patch } = d;
  const chips = patchChips(patch, rung, nextConfig);
  return (
    <section className="space-y-3 rounded-lg border border-slate-700 bg-slate-900/80 p-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className={`rounded px-2 py-0.5 font-semibold ${CLASS_COLOR[d.failure_class]}`}>
          {CLASS_LABEL[d.failure_class]}
        </span>
        <span
          className={`rounded px-2 py-0.5 ${
            d.recoverable ? "bg-emerald-500/15 text-emerald-300" : "bg-rose-500/15 text-rose-300"
          }`}
        >
          {d.recoverable ? "recoverable" : "unrecoverable"}
        </span>
        <span className="text-slate-400">{Math.round(d.confidence * 100)}% confident</span>
        <span className="rounded bg-slate-800 px-2 py-0.5 text-slate-300">
          {SOURCE_LABEL[d.source]}
        </span>
      </div>

      <p className="text-lg leading-snug text-slate-100">{d.explanation}</p>

      {d.failing_step_seq !== null && d.failing_step_label && (
        <button
          type="button"
          onClick={() => onJumpToStep?.(d.failing_step_seq as number)}
          className="block text-left text-rose-300 underline decoration-rose-500/50 underline-offset-4 hover:text-rose-200"
        >
          Failing step{failingStepNo ? ` ${failingStepNo}` : ""}: {d.failing_step_label}
        </button>
      )}

      {d.evidence.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Evidence</h4>
          {d.evidence.map((e, i) => (
            <blockquote
              key={i}
              className="border-l-2 border-slate-600 pl-3 font-mono text-sm text-slate-200"
            >
              <span className="mr-2 font-sans text-xs uppercase text-slate-400">
                {EVIDENCE_LABEL[e.source]}
              </span>
              {e.event_seq !== null && onJumpToStep ? (
                <button
                  type="button"
                  onClick={() => onJumpToStep(e.event_seq as number)}
                  title="Show this step in the timeline"
                  className="text-left underline decoration-slate-500 decoration-dotted underline-offset-4 hover:text-white"
                >
                  “{e.quote}”
                </button>
              ) : (
                <>“{e.quote}”</>
              )}
            </blockquote>
          ))}
        </div>
      )}

      {patch.stop ? (
        <div className="rounded-md border border-rose-500/50 bg-rose-950/60 p-3 text-rose-100">
          <span className="font-semibold">Stop: </span>
          {patch.stop_reason}
        </div>
      ) : (
        <div className="space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Next attempt
          </h4>
          {chips.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {chips.map((chip) => (
                <span
                  key={chip}
                  className="rounded bg-sky-500/15 px-2 py-0.5 text-sm font-medium text-sky-200 ring-1 ring-sky-400/40"
                >
                  {chip}
                </span>
              ))}
            </div>
          )}
          {patch.goal_prefix && <AddedLine text={patch.goal_prefix} />}
          {patch.goal_suffix && <AddedLine text={patch.goal_suffix} />}
          {patch.output_schema && (
            <details className="rounded border border-slate-700 px-2 py-1">
              <summary className="cursor-pointer text-sm text-slate-300">
                Tighter output schema
              </summary>
              <pre className="mt-1 max-h-48 overflow-auto text-xs text-slate-300">
                {JSON.stringify(patch.output_schema, null, 2)}
              </pre>
            </details>
          )}
          {patch.summary.length > 0 && (
            <ul className="list-inside list-disc text-slate-200">
              {patch.summary.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
