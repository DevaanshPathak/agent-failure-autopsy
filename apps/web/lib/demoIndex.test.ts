import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  demoIdFromRunId,
  demoRunId,
  demoStats,
  demoStreamUrl,
  orderForDisplay,
  type DemoIndex,
  type DemoRun,
} from "./demoIndex";

const INDEX = fileURLToPath(new URL("../public/demo/index.json", import.meta.url));

function run(over: Partial<DemoRun>): DemoRun {
  return {
    id: "x",
    kind: "recording",
    title: "t",
    url: "https://x.example",
    goal: "g",
    recorded_at: "2026-11-01T12:00:00.000Z",
    classes: [],
    status: "verified",
    attempts_used: 1,
    credits_used: 5,
    baseline_credits_estimate: 15,
    events: 10,
    has_screenshots: false,
    screenshot_attempts: [],
    path: "/demo/runs/x.jsonl",
    ...over,
  };
}

describe("bundled demo index", () => {
  const index = JSON.parse(readFileSync(INDEX, "utf-8")) as DemoIndex;

  it("describes the illustrative sample", () => {
    const sample = index.runs.find((r) => r.id === "sample");
    expect(sample).toMatchObject({
      kind: "sample",
      title: "Illustrative sample: cookie popup on a shop page",
      classes: ["needs_interaction", "popup_overlay"],
      status: "verified",
      credits_used: 9,
      baseline_credits_estimate: 15,
      events: 36,
      path: "/demo/runs/sample.jsonl",
    });
  });
});

describe("demoStats (same definitions as the API's compute_stats)", () => {
  const runs = [
    run({
      id: "fixed",
      classes: ["popup_overlay"],
      credits_used: 9,
      baseline_credits_estimate: 15,
    }),
    run({ id: "first", classes: [], credits_used: 4, baseline_credits_estimate: 12 }),
    run({ id: "stop", status: "unrecoverable", classes: ["captcha"], credits_used: 0 }),
    run({ id: "spent", status: "budget_exhausted", classes: ["bot_block"], credits_used: 40 }),
    run({
      id: "nobase",
      classes: ["misread_page"],
      credits_used: 3,
      baseline_credits_estimate: null,
    }),
    run({ id: "cancel", status: "cancelled", classes: ["bot_block"], credits_used: 2 }),
    run({ id: "partial", status: null, recorded_at: "2026-11-01T13:00:00.000Z" }),
  ];
  const stats = demoStats(runs);

  it("counts like the API", () => {
    expect(stats).toMatchObject({
      include_replay: true,
      runs_total: 7,
      runs_finished: 6,
      diagnosed: 4,
      fixed: 2,
      verified_first_try: 1,
      unrecoverable: 1,
      budget_exhausted: 1,
      errors: 0,
      credits_used_total: 9 + 4 + 0 + 40 + 3,
    });
    // Baseline only over counted runs that have one: fixed, first, stop, spent (15 each by default).
    expect(stats.baseline_credits_total).toBe(15 + 12 + 15 + 15);
    expect(stats.credits_saved).toBe(15 + 12 + 15 + 15 - (9 + 4 + 0 + 40));
    expect(stats.by_class).toMatchObject({
      popup_overlay: 1,
      captcha: 1,
      bot_block: 1,
      misread_page: 1,
      needs_interaction: 0,
    });
  });

  it("lists every run newest first as replay rows linking to demo runs", () => {
    expect(stats.rows[0]).toMatchObject({
      run_id: "demo-partial",
      status: "running",
      mode: "replay",
    });
    expect(stats.rows).toHaveLength(7);
  });
});

describe("demo ids and urls", () => {
  it("round-trips run ids", () => {
    expect(demoRunId("sample")).toBe("demo-sample");
    expect(demoIdFromRunId("demo-sample")).toBe("sample");
    expect(demoIdFromRunId("a1b2c3")).toBeNull();
    expect(demoStreamUrl("sample")).toBe("demo:/demo/runs/sample.jsonl");
  });

  it("puts recordings before the illustrative sample", () => {
    const ordered = orderForDisplay([
      run({ id: "sample", kind: "sample" }),
      run({ id: "old", recorded_at: "2026-11-01T10:00:00.000Z" }),
      run({ id: "new", recorded_at: "2026-11-01T14:00:00.000Z" }),
    ]);
    expect(ordered.map((r) => r.id)).toEqual(["new", "old", "sample"]);
  });
});
