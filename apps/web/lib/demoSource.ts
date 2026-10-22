import type { UiEvent } from "./types";

/** Stream URLs with this prefix are played from a bundled JSONL file instead of the API. */
export const DEMO_PREFIX = "demo:";
export const DEFAULT_MAX_GAP_MS = 1500;

export interface PlaybackOptions {
  /** >1 plays faster. Default 1. */
  speed?: number;
  /** Longest wait between two events, in ms after applying `speed`. Default 1500. */
  maxGapMs?: number;
  /** Events with `seq` <= this were already shown (resume after a remount): emit none of them. */
  after?: number;
  onStart?: () => void;
  onDone?: () => void;
  onError?: (message: string) => void;
}

export interface Playback {
  cancel(): void;
}

/** Parse a UI-event JSONL file (CRLF-safe), ordered by `seq`. Throws on a malformed line. */
export function parseJsonl(text: string): UiEvent[] {
  const events = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, i) => {
      let ev: UiEvent;
      try {
        ev = JSON.parse(line) as UiEvent;
      } catch {
        throw new Error(`line ${i + 1} is not valid JSON`);
      }
      if (typeof ev?.seq !== "number" || typeof ev?.type !== "string") {
        throw new Error(`line ${i + 1} is not a UI event`);
      }
      return ev;
    });
  return events.sort((a, b) => a.seq - b.seq);
}

/** Wait before each event: the recorded gap between `ts` values, scaled and capped. */
export function gapsMs(events: UiEvent[], speed = 1, maxGapMs = DEFAULT_MAX_GAP_MS): number[] {
  const factor = speed > 0 ? speed : 1;
  return events.map((ev, i) => {
    if (i === 0) return 0;
    const gap = (Date.parse(ev.ts) - Date.parse(events[i - 1].ts)) / factor;
    return Number.isFinite(gap) && gap > 0 ? Math.min(gap, maxGapMs) : 0;
  });
}

/** Emit events one by one with their recorded gaps. Cancel stops any further emission. */
export function playEvents(
  events: UiEvent[],
  onEvent: (ev: UiEvent) => void,
  opts: PlaybackOptions = {},
): Playback {
  const pending = events.filter((ev) => ev.seq > (opts.after ?? 0));
  const gaps = gapsMs(pending, opts.speed, opts.maxGapMs);
  let index = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let cancelled = false;

  const step = () => {
    timer = null;
    if (cancelled) return;
    onEvent(pending[index]);
    index += 1;
    if (index < pending.length) timer = setTimeout(step, gaps[index]);
    else opts.onDone?.();
  };

  if (pending.length === 0) opts.onDone?.();
  else timer = setTimeout(step, gaps[0]);

  return {
    cancel() {
      cancelled = true;
      if (timer !== null) clearTimeout(timer);
      timer = null;
    },
  };
}

/** Fetch a bundled JSONL run and play it. Cancel aborts the fetch and the playback. */
export function playDemo(
  path: string,
  onEvent: (ev: UiEvent) => void,
  opts: PlaybackOptions & { fetchImpl?: typeof fetch } = {},
): Playback {
  const controller = new AbortController();
  let playback: Playback | null = null;
  let cancelled = false;
  const doFetch = opts.fetchImpl ?? fetch;

  doFetch(path, { signal: controller.signal })
    .then(async (res) => {
      if (!res.ok) throw new Error(`recorded run not found (${res.status} for ${path})`);
      return parseJsonl(await res.text());
    })
    .then((events) => {
      if (cancelled) return;
      opts.onStart?.();
      playback = playEvents(events, onEvent, opts);
    })
    .catch((err: unknown) => {
      if (cancelled) return;
      opts.onError?.(err instanceof Error ? err.message : String(err));
    });

  return {
    cancel() {
      cancelled = true;
      controller.abort();
      playback?.cancel();
    },
  };
}

/** For a `demo:` stream URL: the file path and the optional `?speed=` factor. */
export function parseDemoUrl(url: string): { path: string; speed: number } | null {
  if (!url.startsWith(DEMO_PREFIX)) return null;
  const rest = url.slice(DEMO_PREFIX.length);
  const [path, query = ""] = rest.split("?", 2);
  const speed = Number(new URLSearchParams(query).get("speed") ?? "1");
  return { path, speed: Number.isFinite(speed) && speed > 0 ? speed : 1 };
}
