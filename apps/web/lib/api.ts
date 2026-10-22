import type { Run, RunCreated, RunRequest, SiteInfo, Stats } from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);

/**
 * Static demo deployment: no API, recorded runs are played in the browser from /demo/.
 * Decided at build time in next.config.ts (NEXT_PUBLIC_DEMO_MODE).
 */
export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

/** A non-2xx API response. `detail` is FastAPI's `detail` field (a string or a list of issues). */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `API error ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail ?? detail;
    } catch {
      // Body was not JSON; keep the status text.
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const enc = encodeURIComponent;

export const getSites = () => request<SiteInfo[]>("/sites");

export const createRun = (req: RunRequest) =>
  request<RunCreated>("/runs", { method: "POST", body: JSON.stringify(req) });

export const getRun = (id: string) => request<Run>(`/runs/${enc(id)}`);

export const getStats = (includeReplay = false) =>
  request<Stats>(`/stats?include_replay=${includeReplay}`);

export async function cancelRun(id: string): Promise<void> {
  await request<unknown>(`/runs/${enc(id)}/cancel`, { method: "POST" });
}

export const streamUrl = (id: string) => `${API_BASE}/runs/${enc(id)}/stream`;

export const sampleStreamUrl = `${API_BASE}/dev/sample-stream`;

export const screenshotUrl = (id: string, attemptNo: number) =>
  `${API_BASE}/runs/${enc(id)}/attempts/${attemptNo}/screenshot`;
