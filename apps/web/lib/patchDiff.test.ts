import { describe, expect, it } from "vitest";

import { patchChips } from "./patchDiff";
import type { AttemptConfig, Patch } from "./types";

const empty: Patch = {
  next_rung: null,
  skip_rungs: [],
  goal_prefix: null,
  goal_suffix: null,
  output_schema: null,
  browser_profile: null,
  proxy_enabled: null,
  reextract_from_fetch: false,
  stop: false,
  stop_reason: null,
  summary: [],
};

const stealthConfig = { proxy_country: "US" } as AttemptConfig;

describe("patchChips", () => {
  it("describes a bot-block escalation from Fetch", () => {
    const patch: Patch = {
      ...empty,
      next_rung: "agent_stealth",
      skip_rungs: ["agent"],
      browser_profile: "stealth",
      proxy_enabled: true,
    };
    expect(patchChips(patch, "fetch", stealthConfig)).toEqual([
      "→ Rung 3 · Agent + stealth + proxy",
      "lite → stealth",
      "proxy off → US",
      "Skip Rung 2",
    ]);
    expect(patchChips(patch, "agent", null)).toContain("proxy off → on");
  });

  it("has no chips for a same-rung goal patch", () => {
    expect(patchChips({ ...empty, goal_prefix: "Close the cookie banner" }, "agent")).toEqual([]);
  });

  it("marks a cached re-extraction as free", () => {
    expect(
      patchChips({ ...empty, next_rung: "fetch", reextract_from_fetch: true }, "agent"),
    ).toEqual(["→ Rung 1 · Fetch", "0 credits · cached Fetch"]);
  });

  it("shows nothing for a stop", () => {
    expect(
      patchChips({ ...empty, stop: true, stop_reason: "CAPTCHA", next_rung: "agent" }, "fetch"),
    ).toEqual([]);
  });

  it("does not claim a stealth switch when already on stealth", () => {
    expect(patchChips({ ...empty, next_rung: "agent_stealth" }, "agent_stealth")).toEqual([]);
  });
});
