import { CLASS_COLOR, CLASS_LABEL } from "@/lib/format";
import type { Diagnosis, DiagnosisSource, EvidenceSource } from "@/lib/types";

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
}

export default function DiagnosisCard({ diagnosis: d, onJumpToStep, failingStepNo }: Props) {
  const { patch } = d;
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
              <span className="mr-2 font-sans text-xs uppercase text-slate-500">
                {EVIDENCE_LABEL[e.source]}
              </span>
              {e.event_seq !== null && onJumpToStep ? (
                <button
                  type="button"
                  onClick={() => onJumpToStep(e.event_seq as number)}
                  className="text-left hover:text-white"
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
        patch.summary.length > 0 && (
          <div className="space-y-1">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              Next attempt
            </h4>
            <ul className="list-inside list-disc text-slate-200">
              {patch.summary.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        )
      )}
    </section>
  );
}
