import type { FailureClass, Rung, RunStatus } from "./types";

export const RUNG_ORDER: Rung[] = ["fetch", "agent", "agent_stealth"];

export const RUNG_LABEL: Record<Rung, string> = {
  fetch: "Rung 1 · Fetch",
  agent: "Rung 2 · Agent",
  agent_stealth: "Rung 3 · Agent + stealth + proxy",
};

export const RUNG_SHORT: Record<Rung, string> = {
  fetch: "Fetch — free",
  agent: "Agent",
  agent_stealth: "Agent + stealth + proxy",
};

export const CLASS_LABEL: Record<FailureClass, string> = {
  needs_interaction: "Needs interaction",
  popup_overlay: "Popup overlay",
  bot_block: "Bot block",
  misread_page: "Misread page",
  auth_wall: "Auth wall",
  captcha: "Captcha",
};

// Full class strings (not built from parts) so Tailwind can see them.
export const CLASS_COLOR: Record<FailureClass, string> = {
  needs_interaction: "bg-indigo-500/15 text-indigo-200 ring-1 ring-indigo-400/50",
  popup_overlay: "bg-amber-500/15 text-amber-200 ring-1 ring-amber-400/50",
  bot_block: "bg-rose-500/15 text-rose-200 ring-1 ring-rose-400/50",
  misread_page: "bg-cyan-500/15 text-cyan-200 ring-1 ring-cyan-400/50",
  auth_wall: "bg-slate-500/20 text-slate-200 ring-1 ring-slate-400/50",
  captcha: "bg-purple-500/15 text-purple-200 ring-1 ring-purple-400/50",
};

export const STATUS_LABEL: Record<RunStatus, string> = {
  queued: "QUEUED",
  running: "RUNNING",
  verified: "VERIFIED",
  unrecoverable: "UNRECOVERABLE",
  budget_exhausted: "BUDGET SPENT",
  error: "ERROR",
  cancelled: "CANCELLED",
};

export const STATUS_STYLE: Record<RunStatus, string> = {
  queued: "text-slate-300",
  running: "text-sky-300",
  verified: "text-emerald-300",
  unrecoverable: "text-rose-300",
  budget_exhausted: "text-amber-300",
  error: "text-rose-300 underline decoration-rose-500/60",
  cancelled: "text-slate-400",
};

export function fmtCredits(n: number): string {
  return `${n} cr (est.)`;
}

/** Seconds from `t0` to `ts`, e.g. "+12.4s". */
export function relTime(ts: string, t0: string): string {
  const seconds = (Date.parse(ts) - Date.parse(t0)) / 1000;
  if (!Number.isFinite(seconds)) return "";
  return `${seconds >= 0 ? "+" : ""}${seconds.toFixed(1)}s`;
}
