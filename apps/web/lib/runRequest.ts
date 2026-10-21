import { ApiError } from "./api";
import type {
  ExpectedCheck,
  ExpectedCheckType,
  Rung,
  RunMode,
  RunRequest,
  SiteInfo,
} from "./types";

/** Everything the run form edits, as strings where the user types free text. */
export interface RunFormState {
  siteId: string | null;
  url: string;
  goal: string;
  expectedType: ExpectedCheckType | "";
  expectedValue: string;
  expectedFields: string;
  expectedPath: string;
  expectedMin: string;
  outputSchema: string;
  startRung: Rung;
  maxAttempts: string;
  maxCredits: string;
  mode: RunMode;
}

export const emptyRunForm: RunFormState = {
  siteId: null,
  url: "",
  goal: "",
  expectedType: "",
  expectedValue: "",
  expectedFields: "",
  expectedPath: "",
  expectedMin: "",
  outputSchema: "",
  startRung: "fetch",
  maxAttempts: "",
  maxCredits: "",
  mode: "live",
};

/** Prefill the form from a demo site (keeps the chosen mode only if the site can replay). */
export function siteToForm(site: SiteInfo, prev: RunFormState): RunFormState {
  const e = site.expected;
  return {
    ...prev,
    siteId: site.id,
    url: site.url,
    goal: site.goal,
    expectedType: e?.type ?? "",
    expectedValue: e?.value ?? "",
    expectedFields: e?.fields?.join(", ") ?? "",
    expectedPath: e?.path ?? "",
    expectedMin: e?.min != null ? String(e.min) : "",
    outputSchema: site.output_schema ? JSON.stringify(site.output_schema, null, 2) : "",
    startRung: site.start_rung ?? "fetch",
    mode: prev.mode === "replay" && site.has_trace ? "replay" : "live",
  };
}

function optionalInt(raw: string, label: string, errors: string[]): number | null {
  const s = raw.trim();
  if (!s) return null;
  const n = Number(s);
  if (!Number.isInteger(n)) {
    errors.push(`${label} must be a whole number`);
    return null;
  }
  return n;
}

function buildExpected(f: RunFormState, errors: string[]): ExpectedCheck | null {
  if (!f.expectedType) return null;
  const check: ExpectedCheck = {
    type: f.expectedType,
    value: null,
    fields: null,
    path: null,
    min: null,
  };
  switch (f.expectedType) {
    case "contains":
    case "regex":
      if (!f.expectedValue.trim())
        errors.push("Expected check: enter the text or pattern to look for");
      check.value = f.expectedValue.trim();
      break;
    case "fields_present": {
      const fields = f.expectedFields
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      if (!fields.length) errors.push("Expected check: list at least one field path");
      check.fields = fields;
      break;
    }
    case "min_items": {
      if (!f.expectedPath.trim()) errors.push("Expected check: enter the path to the list");
      check.path = f.expectedPath.trim();
      const min = optionalInt(f.expectedMin, "Minimum items", errors);
      if (min === null || min < 1) errors.push("Expected check: minimum items must be at least 1");
      check.min = min;
      break;
    }
  }
  return check;
}

export type BuildResult = { ok: true; request: RunRequest } | { ok: false; errors: string[] };

/** Turn form state into a complete `RunRequest`, or the list of problems to show. */
export function buildRunRequest(f: RunFormState): BuildResult {
  const errors: string[] = [];
  const url = f.url.trim();
  if (!url) errors.push("URL is required");
  else if (!/^https?:\/\//i.test(url)) errors.push("URL must start with http:// or https://");
  const goal = f.goal.trim();
  if (!goal) errors.push("Goal is required");

  const expected = buildExpected(f, errors);

  let outputSchema: Record<string, unknown> | null = null;
  if (f.outputSchema.trim()) {
    try {
      const parsed: unknown = JSON.parse(f.outputSchema);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        outputSchema = parsed as Record<string, unknown>;
      } else {
        errors.push("Output schema must be a JSON object");
      }
    } catch {
      errors.push("Output schema is not valid JSON");
    }
  }

  const maxAttempts = optionalInt(f.maxAttempts, "Max attempts", errors);
  const maxCredits = optionalInt(f.maxCredits, "Max credits", errors);

  if (errors.length) return { ok: false, errors };
  return {
    ok: true,
    request: {
      url,
      goal,
      expected,
      output_schema: outputSchema,
      site_id: f.siteId,
      mode: f.mode,
      start_rung: f.startRung,
      max_attempts: maxAttempts,
      max_credits: maxCredits,
    },
  };
}

interface ValidationIssue {
  loc?: unknown[];
  msg?: string;
}

/** Human-readable lines for an API error (FastAPI 422 issue lists or a plain detail string). */
export function apiErrorMessages(err: unknown): string[] {
  if (err instanceof ApiError) {
    if (Array.isArray(err.detail)) {
      return (err.detail as ValidationIssue[]).map((issue) => {
        const where = (issue.loc ?? []).filter((p) => p !== "body").join(".");
        return where ? `${where}: ${issue.msg ?? "invalid"}` : (issue.msg ?? "invalid");
      });
    }
    if (typeof err.detail === "string") return [err.detail];
    return [`API error ${err.status}`];
  }
  if (err instanceof Error) return [`Could not reach the API: ${err.message}`];
  return ["Unknown error"];
}
