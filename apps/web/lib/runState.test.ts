import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { initialRunViewState, reduceRun, type RunViewState } from "./runState";
import type { UiEvent } from "./types";

const SAMPLE = fileURLToPath(new URL("../../../fixtures/sample-run.jsonl", import.meta.url));

function sampleEvents(): UiEvent[] {
  return readFileSync(SAMPLE, "utf-8")
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as UiEvent);
}

function reduceAll(events: UiEvent[]): RunViewState {
  return events.reduce(reduceRun, initialRunViewState);
}

describe("reduceRun over the sample run", () => {
  const events = sampleEvents();
  const state = reduceAll(events);

  it("reads all 36 events", () => {
    expect(events).toHaveLength(36);
    expect(state.lastSeq).toBe(36);
  });

  it("builds three attempts with their verification outcome", () => {
    expect(state.attempts.map((a) => [a.attemptNo, a.rung, a.status])).toEqual([
      [1, "fetch", "failed"],
      [2, "agent", "failed"],
      [3, "agent", "passed"],
    ]);
    expect(state.header?.url).toBe("https://shop.example.com/products");
  });

  it("marks the ladder: fetch failed, agent passed, stealth never used", () => {
    expect(state.rungs.fetch.state).toBe("failed");
    expect(state.rungs.agent.state).toBe("passed");
    expect(state.rungs.agent_stealth.state).toBe("pending");
    expect(state.rungs.agent.attempts).toEqual([2, 3]);
    expect(state.rungs.agent.credits).toBe(9);
    expect(state.rungs.fetch.credits).toBe(0);
  });

  it("records the failing steps the diagnoses point at", () => {
    expect(state.attempts.map((a) => a.failingSeq)).toEqual([2, 4, null]);
    expect(state.attempts[1].diagnosis?.failure_class).toBe("popup_overlay");
  });

  it("ends verified and done, with the live view switched off", () => {
    expect(state.done).toBe(true);
    expect(state.verdict?.status).toBe("verified");
    expect(state.verdict?.credits_used).toBe(9);
    expect(state.liveView).toMatchObject({ attemptNo: 3, active: false });
    expect(state.budget?.credits_used).toBe(9);
  });

  it("ignores repeated events (reconnect replay)", () => {
    const once = reduceAll(events.slice(0, 20));
    const again = events.slice(0, 20).reduce(reduceRun, once);
    expect(again).toBe(once);
    expect(reduceAll([...events, ...events])).toEqual(state);
  });

  it("does not mutate the initial state", () => {
    expect(initialRunViewState.attempts).toHaveLength(0);
    expect(initialRunViewState.rungs.agent.attempts).toHaveLength(0);
  });
});
