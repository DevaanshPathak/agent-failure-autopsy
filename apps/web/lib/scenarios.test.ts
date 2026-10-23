import { describe, expect, it } from "vitest";

import { groupScenarios, scenarioRequest } from "./scenarios";
import type { SiteInfo } from "./types";

function site(overrides: Partial<SiteInfo>): SiteInfo {
  return {
    id: "x",
    url: "https://example.com/",
    goal: "Return the thing.",
    expected: { type: "contains", value: "thing", fields: null, path: null, min: null },
    expected_class: "needs_interaction",
    notes: null,
    output_schema: null,
    baseline_steps: null,
    start_rung: null,
    has_trace: false,
    title: "A card",
    summary: "What happens.",
    kind: "real",
    cost_hint: "about 3 credits",
    ...overrides,
  };
}

describe("groupScenarios", () => {
  it("splits titled sites into lab and real, keeping file order", () => {
    const groups = groupScenarios([
      site({ id: "real-1" }),
      site({ id: "lab-1", kind: "lab" }),
      site({ id: "untitled", title: null }),
      site({ id: "lab-2", kind: "lab" }),
    ]);
    expect(groups.lab.map((s) => s.id)).toEqual(["lab-1", "lab-2"]);
    expect(groups.real.map((s) => s.id)).toEqual(["real-1"]);
  });

  it("is empty without titled sites", () => {
    expect(groupScenarios([site({ title: null })])).toEqual({ lab: [], real: [] });
  });
});

describe("scenarioRequest", () => {
  it("starts a live run with the site's goal, check, schema and start rung", () => {
    const schema = { type: "object", properties: { products: { type: "array" } } };
    const built = scenarioRequest(
      site({
        id: "lab-catalog",
        kind: "lab",
        url: "https://agent-failure-autopsy.vercel.app/lab/catalog.html?v=1",
        expected: { type: "min_items", value: null, fields: null, path: "products", min: 12 },
        expected_class: "misread_page",
        output_schema: schema,
        start_rung: "agent",
        has_trace: true, // a recording exists, but a card always runs live
      }),
    );
    expect(built.ok).toBe(true);
    if (!built.ok) return;
    expect(built.request).toMatchObject({
      url: "https://agent-failure-autopsy.vercel.app/lab/catalog.html?v=1",
      goal: "Return the thing.",
      site_id: "lab-catalog",
      mode: "live",
      start_rung: "agent",
      expected: { type: "min_items", path: "products", min: 12 },
      output_schema: schema,
    });
  });

  it("starts at Fetch when the site names no rung", () => {
    const built = scenarioRequest(site({}));
    expect(built.ok && built.request.start_rung).toBe("fetch");
  });
});
