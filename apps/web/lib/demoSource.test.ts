import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { gapsMs, parseDemoUrl, parseJsonl, playDemo, playEvents } from "./demoSource";
import type { UiEvent } from "./types";

function ev(seq: number, ts: string, type = "budget"): UiEvent {
  return {
    type,
    seq,
    run_id: "r",
    ts,
    attempts_used: 0,
    max_attempts: 4,
    credits_used: 0,
    max_credits: 40,
  } as UiEvent;
}

const T0 = "2026-11-01T11:00:00.000Z";
const at = (ms: number) => new Date(Date.parse(T0) + ms).toISOString();

describe("parseJsonl", () => {
  it("orders by seq and copes with CRLF and blank lines", () => {
    const text = [ev(2, at(10)), ev(1, at(0)), ev(3, at(20))]
      .map((e) => JSON.stringify(e))
      .join("\r\n\r\n");
    expect(parseJsonl(text).map((e) => e.seq)).toEqual([1, 2, 3]);
  });

  it("rejects malformed lines", () => {
    expect(() => parseJsonl('{"seq":1,"type":"budget"}\nnot json')).toThrow("line 2");
    expect(() => parseJsonl('{"hello":1}')).toThrow("not a UI event");
  });
});

describe("gapsMs", () => {
  it("uses recorded gaps, scaled by speed and capped", () => {
    const events = [ev(1, at(0)), ev(2, at(400)), ev(3, at(10_400)), ev(4, at(10_300))];
    expect(gapsMs(events)).toEqual([0, 400, 1500, 0]);
    expect(gapsMs(events, 2)).toEqual([0, 200, 1500, 0]);
    expect(gapsMs(events, 1, 5000)).toEqual([0, 400, 5000, 0]);
  });
});

describe("playEvents", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  const events = [ev(1, at(0)), ev(2, at(1000)), ev(3, at(60_000))];

  it("emits in order with the recorded gaps and the 1.5 s cap", () => {
    const seen: number[] = [];
    const done = vi.fn();
    playEvents(events, (e) => seen.push(e.seq), { onDone: done });
    vi.advanceTimersByTime(0);
    expect(seen).toEqual([1]);
    vi.advanceTimersByTime(999);
    expect(seen).toEqual([1]);
    vi.advanceTimersByTime(1);
    expect(seen).toEqual([1, 2]);
    vi.advanceTimersByTime(1499);
    expect(seen).toEqual([1, 2]);
    vi.advanceTimersByTime(1);
    expect(seen).toEqual([1, 2, 3]);
    expect(done).toHaveBeenCalledOnce();
  });

  it("stops on cancel", () => {
    const seen: number[] = [];
    const done = vi.fn();
    const playback = playEvents(events, (e) => seen.push(e.seq), { onDone: done });
    vi.advanceTimersByTime(500);
    playback.cancel();
    vi.advanceTimersByTime(10_000);
    expect(seen).toEqual([1]);
    expect(done).not.toHaveBeenCalled();
  });

  it("skips events already shown when resuming", () => {
    const seen: number[] = [];
    playEvents(events, (e) => seen.push(e.seq), { after: 2 });
    vi.advanceTimersByTime(0);
    expect(seen).toEqual([3]);
  });
});

describe("playDemo", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  const body = [ev(1, at(0)), ev(2, at(100))].map((e) => JSON.stringify(e)).join("\n");
  const okFetch = vi.fn(async () => new Response(body, { status: 200 })) as unknown as typeof fetch;

  it("fetches, starts and plays the file", async () => {
    const seen: number[] = [];
    const start = vi.fn();
    playDemo("/demo/runs/x.jsonl", (e) => seen.push(e.seq), { fetchImpl: okFetch, onStart: start });
    await vi.advanceTimersByTimeAsync(200);
    expect(start).toHaveBeenCalledOnce();
    expect(seen).toEqual([1, 2]);
  });

  it("emits nothing when cancelled before the file arrives", async () => {
    const seen: number[] = [];
    const playback = playDemo("/demo/runs/x.jsonl", (e) => seen.push(e.seq), {
      fetchImpl: okFetch,
    });
    playback.cancel();
    await vi.advanceTimersByTimeAsync(500);
    expect(seen).toEqual([]);
  });

  it("reports a missing file", async () => {
    const notFound = vi.fn(
      async () => new Response("", { status: 404 }),
    ) as unknown as typeof fetch;
    const onError = vi.fn();
    playDemo("/demo/runs/missing.jsonl", () => {}, { fetchImpl: notFound, onError });
    await vi.advanceTimersByTimeAsync(0);
    expect(onError).toHaveBeenCalledWith(expect.stringContaining("404"));
  });
});

describe("parseDemoUrl", () => {
  it("splits path and speed", () => {
    expect(parseDemoUrl("demo:/demo/runs/sample.jsonl")).toEqual({
      path: "/demo/runs/sample.jsonl",
      speed: 1,
    });
    expect(parseDemoUrl("demo:/demo/runs/a.jsonl?speed=3")?.speed).toBe(3);
    expect(parseDemoUrl("http://x/runs/1/stream")).toBeNull();
  });
});
