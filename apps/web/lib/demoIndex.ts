import type { FailureClass, RunStatus, Stats, StatsRow } from "./types";

/** One bundled run, as written by scripts/sync-demo.mjs into public/demo/index.json. */
export interface DemoRun {
  id: string;
  /** "sample" = the hand-written illustrative stream; "recording" = a recorded TinyFish run. */
  kind: "sample" | "recording";
  title: string;
  url: string | null;
  goal: string | null;
  recorded_at: string | null;
  classes: FailureClass[];
  status: RunStatus | null;
  attempts_used: number;
  credits_used: number;
  baseline_credits_estimate: number | null;
  events: number;
  has_screenshots: boolean;
  screenshot_attempts: number[];
  path: string;
}

export interface DemoIndex {
  version: number;
  runs: DemoRun[];
}

export const DEMO_INDEX_URL = "/demo/index.json";
export const DEMO_RUN_PREFIX = "demo-";
export const SAMPLE_NOTE = "Hand-written example of the event stream — not a live TinyFish run";

export const demoRunId = (id: string) => `${DEMO_RUN_PREFIX}${id}`;
export const demoIdFromRunId = (runId: string): string | null =>
  runId.startsWith(DEMO_RUN_PREFIX) ? runId.slice(DEMO_RUN_PREFIX.length) : null;
export const demoStreamUrl = (id: string) => `demo:/demo/runs/${encodeURIComponent(id)}.jsonl`;
export const demoScreenshotUrl = (id: string, attemptNo: number) =>
  `/demo/runs/${encodeURIComponent(id)}/attempt-${attemptNo}.jpg`;

export async function loadDemoIndex(fetchImpl: typeof fetch = fetch): Promise<DemoIndex> {
  const res = await fetchImpl(DEMO_INDEX_URL);
  if (!res.ok) throw new Error(`demo index not found (${res.status})`);
  const data = (await res.json()) as Partial<DemoIndex>;
  return { version: data.version ?? 1, runs: Array.isArray(data.runs) ? data.runs : [] };
}

/** Recordings first (newest first), the illustrative sample last. */
export function orderForDisplay(runs: DemoRun[]): DemoRun[] {
  return [...runs].sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === "recording" ? -1 : 1;
    return (b.recorded_at ?? "").localeCompare(a.recorded_at ?? "") || a.id.localeCompare(b.id);
  });
}

const FINAL: RunStatus[] = ["verified", "unrecoverable", "budget_exhausted", "error", "cancelled"];
const CLASSES: FailureClass[] = [
  "needs_interaction",
  "popup_overlay",
  "bot_block",
  "misread_page",
  "auth_wall",
  "captcha",
];
const MAX_ROWS = 200;

/**
 * The API's /stats (apps/api/app/stats.py `compute_stats`, with replays included), computed
 * from the bundled runs so the static demo needs no backend.
 */
export function demoStats(runs: DemoRun[]): Stats {
  const finished = runs.filter((r) => r.status !== null && FINAL.includes(r.status));
  const counted = finished.filter((r) => r.status !== "cancelled");
  const withStatus = (s: RunStatus) => counted.filter((r) => r.status === s);
  const verified = withStatus("verified");
  const withBaseline = counted.filter((r) => r.baseline_credits_estimate !== null);
  const baselineTotal = withBaseline.reduce((n, r) => n + (r.baseline_credits_estimate ?? 0), 0);
  const byClass = Object.fromEntries(CLASSES.map((c) => [c, 0])) as Record<FailureClass, number>;
  for (const r of counted) for (const c of r.classes) byClass[c] = (byClass[c] ?? 0) + 1;

  const rows: StatsRow[] = [...runs]
    .sort((a, b) => (b.recorded_at ?? "").localeCompare(a.recorded_at ?? ""))
    .slice(0, MAX_ROWS)
    .map((r) => ({
      run_id: demoRunId(r.id),
      created_at: r.recorded_at ?? "",
      site_id: r.id,
      url: r.url ?? "",
      mode: "replay",
      status: r.status ?? "running",
      attempts: r.attempts_used,
      credits_used: r.credits_used,
      baseline_credits_estimate: r.baseline_credits_estimate,
      classes: r.classes,
    }));

  return {
    include_replay: true,
    runs_total: runs.length,
    runs_finished: finished.length,
    diagnosed: counted.filter((r) => r.classes.length > 0).length,
    fixed: verified.filter((r) => r.classes.length > 0).length,
    verified_first_try: verified.filter((r) => r.classes.length === 0).length,
    unrecoverable: withStatus("unrecoverable").length,
    budget_exhausted: withStatus("budget_exhausted").length,
    errors: withStatus("error").length,
    credits_used_total: counted.reduce((n, r) => n + r.credits_used, 0),
    baseline_credits_total: baselineTotal,
    credits_saved: baselineTotal - withBaseline.reduce((n, r) => n + r.credits_used, 0),
    by_class: byClass,
    rows,
  };
}
