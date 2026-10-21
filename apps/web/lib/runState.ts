import type {
  AttemptConfig,
  BudgetEvent,
  Diagnosis,
  Rung,
  RungChangeEvent,
  TraceEvent,
  UiEvent,
  VerdictEvent,
  VerifyResult,
} from "./types";

export type RungState = "pending" | "active" | "failed" | "passed" | "skipped";

export interface AttemptView {
  attemptNo: number;
  rung: Rung;
  config: AttemptConfig;
  startedAt: string;
  events: TraceEvent[];
  verify: VerifyResult | null;
  diagnosis: Diagnosis | null;
  failingSeq: number | null;
  status: "running" | "passed" | "failed";
  streamingUrl: string | null;
}

export interface RungView {
  state: RungState;
  attempts: number[];
  credits: number;
}

export interface RunViewState {
  lastSeq: number;
  header: { url: string; goal: string } | null;
  attempts: AttemptView[];
  currentAttempt: number | null;
  rungs: Record<Rung, RungView>;
  rungChanges: RungChangeEvent[];
  budget: BudgetEvent | null;
  liveView: { url: string; attemptNo: number; active: boolean } | null;
  verdict: VerdictEvent | null;
  done: boolean;
}

const RUNGS: Rung[] = ["fetch", "agent", "agent_stealth"];

function emptyRungs(): Record<Rung, RungView> {
  return {
    fetch: { state: "pending", attempts: [], credits: 0 },
    agent: { state: "pending", attempts: [], credits: 0 },
    agent_stealth: { state: "pending", attempts: [], credits: 0 },
  };
}

export const initialRunViewState: RunViewState = {
  lastSeq: 0,
  header: null,
  attempts: [],
  currentAttempt: null,
  rungs: emptyRungs(),
  rungChanges: [],
  budget: null,
  liveView: null,
  verdict: null,
  done: false,
};

function updateAttempt(
  attempts: AttemptView[],
  attemptNo: number,
  update: (a: AttemptView) => AttemptView,
): AttemptView[] {
  return attempts.map((a) => (a.attemptNo === attemptNo ? update(a) : a));
}

function setRung(
  rungs: Record<Rung, RungView>,
  rung: Rung,
  patch: Partial<RungView>,
): Record<Rung, RungView> {
  return { ...rungs, [rung]: { ...rungs[rung], ...patch } };
}

/** Credits per attempt: steps from the run record when present, else the PROGRESS count. */
function attemptCredits(a: AttemptView): number {
  if (a.rung === "fetch") return 0;
  const snapshot = a.events.find((e) => e.kind === "run_snapshot");
  const steps = snapshot?.raw["num_of_steps"];
  if (typeof steps === "number") return steps;
  return a.events.filter((e) => e.kind === "progress").length;
}

function recomputeCredits(
  rungs: Record<Rung, RungView>,
  attempts: AttemptView[],
): Record<Rung, RungView> {
  const next = { ...rungs };
  for (const rung of RUNGS) {
    const credits = attempts
      .filter((a) => a.rung === rung)
      .reduce((sum, a) => sum + attemptCredits(a), 0);
    next[rung] = { ...rungs[rung], credits };
  }
  return next;
}

function deactivateLiveView(
  liveView: RunViewState["liveView"],
  attemptNo?: number,
): RunViewState["liveView"] {
  if (!liveView || (attemptNo !== undefined && liveView.attemptNo !== attemptNo)) return liveView;
  return { ...liveView, active: false };
}

/** Pure reducer from UI events to view state. Events at or below `lastSeq` are ignored. */
export function reduceRun(s: RunViewState, ev: UiEvent): RunViewState {
  if (ev.seq <= s.lastSeq) return s;
  const base: RunViewState = { ...s, lastSeq: ev.seq };

  switch (ev.type) {
    case "rung_change": {
      let rungs = base.rungs;
      for (const skipped of ev.skipped) rungs = setRung(rungs, skipped, { state: "skipped" });
      rungs = setRung(rungs, ev.to_rung, { state: "active" });
      return { ...base, rungs, rungChanges: [...base.rungChanges, ev] };
    }

    case "attempt_started": {
      const attempt: AttemptView = {
        attemptNo: ev.attempt_no,
        rung: ev.rung,
        config: ev.config,
        startedAt: ev.ts,
        events: [],
        verify: null,
        diagnosis: null,
        failingSeq: null,
        status: "running",
        streamingUrl: null,
      };
      const rung = base.rungs[ev.rung];
      return {
        ...base,
        header: base.header ?? { url: ev.config.url, goal: ev.config.goal },
        attempts: [...base.attempts, attempt],
        currentAttempt: ev.attempt_no,
        rungs: setRung(base.rungs, ev.rung, {
          state: "active",
          attempts: [...rung.attempts, ev.attempt_no],
        }),
        liveView: ev.rung === "fetch" ? null : base.liveView,
      };
    }

    case "trace_event":
      return {
        ...base,
        attempts: updateAttempt(base.attempts, ev.attempt_no, (a) => ({
          ...a,
          events: [...a.events, ev.event],
        })),
      };

    case "live_view":
      return {
        ...base,
        liveView: { url: ev.streaming_url, attemptNo: ev.attempt_no, active: true },
        attempts: updateAttempt(base.attempts, ev.attempt_no, (a) => ({
          ...a,
          streamingUrl: ev.streaming_url,
        })),
      };

    case "budget":
      return { ...base, budget: ev, rungs: recomputeCredits(base.rungs, base.attempts) };

    case "verify": {
      const attempt = base.attempts.find((a) => a.attemptNo === ev.attempt_no);
      const passed = ev.result.passed;
      return {
        ...base,
        attempts: updateAttempt(base.attempts, ev.attempt_no, (a) => ({
          ...a,
          verify: ev.result,
          status: passed ? "passed" : "failed",
        })),
        rungs: attempt
          ? setRung(base.rungs, attempt.rung, { state: passed ? "passed" : "failed" })
          : base.rungs,
        liveView: deactivateLiveView(base.liveView, ev.attempt_no),
      };
    }

    case "diagnosis":
      return {
        ...base,
        attempts: updateAttempt(base.attempts, ev.attempt_no, (a) => ({
          ...a,
          diagnosis: ev.diagnosis,
          failingSeq: ev.diagnosis.failing_step_seq,
        })),
      };

    case "verdict": {
      const last = base.attempts[base.attempts.length - 1];
      return {
        ...base,
        verdict: ev,
        done: true,
        rungs:
          ev.status === "verified" && last
            ? setRung(base.rungs, last.rung, { state: "passed" })
            : base.rungs,
        liveView: deactivateLiveView(base.liveView),
      };
    }

    default:
      // An event type this build doesn't know (e.g. a newer API): keep the state, never crash.
      return base;
  }
}
