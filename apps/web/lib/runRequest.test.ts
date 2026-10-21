import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import { apiErrorMessages, buildRunRequest, emptyRunForm, siteToForm } from "./runRequest";
import type { SiteInfo } from "./types";

const base = { ...emptyRunForm, url: " https://example.com ", goal: " Return the heading " };

describe("buildRunRequest", () => {
  it("builds a complete request with nulls for unset optionals", () => {
    const result = buildRunRequest(base);
    expect(result).toEqual({
      ok: true,
      request: {
        url: "https://example.com",
        goal: "Return the heading",
        expected: null,
        output_schema: null,
        site_id: null,
        mode: "live",
        start_rung: "fetch",
        max_attempts: null,
        max_credits: null,
      },
    });
  });

  it("builds each expected-check type", () => {
    const minItems = buildRunRequest({
      ...base,
      expectedType: "min_items",
      expectedPath: "products",
      expectedMin: "3",
    });
    expect(minItems.ok && minItems.request.expected).toEqual({
      type: "min_items",
      value: null,
      fields: null,
      path: "products",
      min: 3,
    });
    const fields = buildRunRequest({
      ...base,
      expectedType: "fields_present",
      expectedFields: "title, price.amount,",
    });
    expect(fields.ok && fields.request.expected?.fields).toEqual(["title", "price.amount"]);
  });

  it("reports every problem at once", () => {
    const result = buildRunRequest({
      ...emptyRunForm,
      url: "ftp://x",
      expectedType: "min_items",
      expectedMin: "0",
      outputSchema: "[1]",
      maxAttempts: "2.5",
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors).toEqual([
        "URL must start with http:// or https://",
        "Goal is required",
        "Expected check: enter the path to the list",
        "Expected check: minimum items must be at least 1",
        "Output schema must be a JSON object",
        "Max attempts must be a whole number",
      ]);
    }
  });

  it("parses the output schema and limits", () => {
    const result = buildRunRequest({
      ...base,
      outputSchema: '{"type":"object"}',
      maxAttempts: "3",
      maxCredits: "20",
      startRung: "agent",
      mode: "replay",
      siteId: "books",
    });
    expect(result.ok && result.request).toMatchObject({
      output_schema: { type: "object" },
      max_attempts: 3,
      max_credits: 20,
      start_rung: "agent",
      mode: "replay",
      site_id: "books",
    });
  });
});

describe("siteToForm", () => {
  const site: SiteInfo = {
    id: "books",
    url: "https://books.toscrape.com/",
    goal: "How many copies are available?",
    expected: { type: "regex", value: "\\b22\\b", fields: null, path: null, min: null },
    expected_class: "misread_page",
    notes: null,
    output_schema: null,
    baseline_steps: null,
    start_rung: "agent",
    has_trace: false,
  };

  it("prefills every field from the site", () => {
    const form = siteToForm(site, emptyRunForm);
    expect(form).toMatchObject({
      siteId: "books",
      url: site.url,
      goal: site.goal,
      expectedType: "regex",
      expectedValue: "\\b22\\b",
      startRung: "agent",
      mode: "live",
    });
  });

  it("keeps replay only when the site has a recorded trace", () => {
    expect(siteToForm(site, { ...emptyRunForm, mode: "replay" }).mode).toBe("live");
    expect(siteToForm({ ...site, has_trace: true }, { ...emptyRunForm, mode: "replay" }).mode).toBe(
      "replay",
    );
  });
});

describe("apiErrorMessages", () => {
  it("formats FastAPI validation issues", () => {
    const err = new ApiError(422, [
      { loc: ["body", "url"], msg: "Value error, url must start with http:// or https://" },
      { loc: ["body"], msg: "bad body" },
    ]);
    expect(apiErrorMessages(err)).toEqual([
      "url: Value error, url must start with http:// or https://",
      "bad body",
    ]);
  });

  it("passes string details through", () => {
    expect(apiErrorMessages(new ApiError(503, "TINYFISH_API_KEY is not set"))).toEqual([
      "TINYFISH_API_KEY is not set",
    ]);
    expect(apiErrorMessages(new TypeError("Failed to fetch"))).toEqual([
      "Could not reach the API: Failed to fetch",
    ]);
  });
});
