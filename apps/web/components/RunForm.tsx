"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, createRun, getSites } from "@/lib/api";
import { CLASS_LABEL, RUNG_LABEL, RUNG_ORDER } from "@/lib/format";
import {
  apiErrorMessages,
  buildRunRequest,
  emptyRunForm,
  siteToForm,
  type RunFormState,
} from "@/lib/runRequest";
import type { ExpectedCheckType, SiteInfo } from "@/lib/types";

const CUSTOM = "__custom__";

const EXPECTED_TYPES: { value: ExpectedCheckType | ""; label: string }[] = [
  { value: "", label: "None" },
  { value: "contains", label: "Result contains text" },
  { value: "regex", label: "Result matches a regex" },
  { value: "fields_present", label: "Fields are present" },
  { value: "min_items", label: "List has at least N items" },
];

const inputClass =
  "w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:border-sky-500 focus:outline-none";
const labelClass = "block text-sm font-medium text-slate-300";

export default function RunForm() {
  const router = useRouter();
  const [sites, setSites] = useState<SiteInfo[]>([]);
  const [sitesError, setSitesError] = useState<string | null>(null);
  const [form, setForm] = useState<RunFormState>(emptyRunForm);
  const [errors, setErrors] = useState<string[]>([]);
  const [status, setStatus] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getSites()
      .then((list) => {
        if (!cancelled) setSites(list);
      })
      .catch((err: unknown) => {
        if (!cancelled) setSitesError(apiErrorMessages(err)[0]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const site = sites.find((s) => s.id === form.siteId) ?? null;
  const update = (patch: Partial<RunFormState>) => setForm((f) => ({ ...f, ...patch }));

  function chooseSite(id: string) {
    const chosen = sites.find((s) => s.id === id);
    if (chosen) setForm((f) => siteToForm(chosen, f));
    else update({ siteId: null });
  }

  async function submit(mode = form.mode) {
    const built = buildRunRequest({ ...form, mode });
    if (!built.ok) {
      setErrors(built.errors);
      setStatus(null);
      return;
    }
    setSubmitting(true);
    setErrors([]);
    setStatus(null);
    try {
      const created = await createRun(built.request);
      router.push(`/runs/${encodeURIComponent(created.run_id)}`);
    } catch (err) {
      setErrors(apiErrorMessages(err));
      setStatus(err instanceof ApiError ? err.status : null);
      setSubmitting(false);
    }
  }

  const canReplay = Boolean(site?.has_trace);

  return (
    <form
      className="max-w-3xl space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className="space-y-1.5">
        <label htmlFor="site" className={labelClass}>
          Demo site
        </label>
        <select
          id="site"
          className={inputClass}
          value={form.siteId ?? CUSTOM}
          onChange={(e) => chooseSite(e.target.value)}
        >
          <option value={CUSTOM}>Custom URL…</option>
          {sites.map((s) => (
            <option key={s.id} value={s.id}>
              {s.id}
              {s.expected_class ? ` · shows ${CLASS_LABEL[s.expected_class]}` : ""}
              {s.has_trace ? " · ● recorded" : ""}
            </option>
          ))}
        </select>
        {sitesError && (
          <p className="text-sm text-amber-300">Demo sites unavailable: {sitesError}</p>
        )}
        {site?.notes && <p className="text-sm text-slate-400">{site.notes}</p>}
      </div>

      <div className="space-y-1.5">
        <label htmlFor="url" className={labelClass}>
          URL
        </label>
        <input
          id="url"
          type="url"
          required
          placeholder="https://example.com/products"
          className={inputClass}
          value={form.url}
          onChange={(e) => update({ url: e.target.value })}
        />
      </div>

      <div className="space-y-1.5">
        <label htmlFor="goal" className={labelClass}>
          Goal
        </label>
        <textarea
          id="goal"
          required
          rows={3}
          placeholder="List the first 3 products with their name and price."
          className={inputClass}
          value={form.goal}
          onChange={(e) => update({ goal: e.target.value })}
        />
      </div>

      <fieldset className="space-y-2 rounded-lg border border-slate-800 p-4">
        <legend className="px-1 text-sm font-medium text-slate-300">Expected-output check</legend>
        <select
          aria-label="Expected check type"
          className={inputClass}
          value={form.expectedType}
          onChange={(e) => update({ expectedType: e.target.value as ExpectedCheckType | "" })}
        >
          {EXPECTED_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        {(form.expectedType === "contains" || form.expectedType === "regex") && (
          <input
            aria-label={form.expectedType === "regex" ? "Regex" : "Text"}
            placeholder={form.expectedType === "regex" ? "\\b22\\b" : "Blue Mug"}
            className={`${inputClass} font-mono`}
            value={form.expectedValue}
            onChange={(e) => update({ expectedValue: e.target.value })}
          />
        )}
        {form.expectedType === "fields_present" && (
          <input
            aria-label="Field paths"
            placeholder="title, price.amount, products.0.name"
            className={`${inputClass} font-mono`}
            value={form.expectedFields}
            onChange={(e) => update({ expectedFields: e.target.value })}
          />
        )}
        {form.expectedType === "min_items" && (
          <div className="flex gap-2">
            <input
              aria-label="List path"
              placeholder="products"
              className={`${inputClass} font-mono`}
              value={form.expectedPath}
              onChange={(e) => update({ expectedPath: e.target.value })}
            />
            <input
              aria-label="Minimum items"
              type="number"
              min={1}
              placeholder="3"
              className={`${inputClass} w-32`}
              value={form.expectedMin}
              onChange={(e) => update({ expectedMin: e.target.value })}
            />
          </div>
        )}
        {!form.expectedType && (
          <p className="text-sm text-amber-300/90">
            Without an expected check the verifier can only catch empty, null, blocked or
            self-reported failures.
          </p>
        )}
      </fieldset>

      <details className="rounded-lg border border-slate-800 p-4">
        <summary className="cursor-pointer text-sm font-medium text-slate-300">Advanced</summary>
        <div className="mt-3 space-y-3">
          <div className="space-y-1.5">
            <label htmlFor="schema" className={labelClass}>
              TinyFish output schema (JSON, optional)
            </label>
            <textarea
              id="schema"
              rows={5}
              placeholder='{"type": "object", "properties": {"title": {"type": "string"}}}'
              className={`${inputClass} font-mono text-sm`}
              value={form.outputSchema}
              onChange={(e) => update({ outputSchema: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <label htmlFor="start-rung" className={labelClass}>
                Start rung
              </label>
              <select
                id="start-rung"
                className={inputClass}
                value={form.startRung}
                onChange={(e) => update({ startRung: e.target.value as RunFormState["startRung"] })}
              >
                {RUNG_ORDER.map((r) => (
                  <option key={r} value={r}>
                    {RUNG_LABEL[r]}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="max-attempts" className={labelClass}>
                Max attempts
              </label>
              <input
                id="max-attempts"
                type="number"
                min={1}
                max={8}
                placeholder="4"
                className={inputClass}
                value={form.maxAttempts}
                onChange={(e) => update({ maxAttempts: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="max-credits" className={labelClass}>
                Max credits
              </label>
              <input
                id="max-credits"
                type="number"
                min={0}
                max={500}
                placeholder="40"
                className={inputClass}
                value={form.maxCredits}
                onChange={(e) => update({ maxCredits: e.target.value })}
              />
            </div>
          </div>
        </div>
      </details>

      <fieldset className="flex items-center gap-6">
        <legend className="sr-only">Mode</legend>
        {(["live", "replay"] as const).map((mode) => (
          <label
            key={mode}
            className={`flex items-center gap-2 ${
              mode === "replay" && !canReplay ? "text-slate-500" : "text-slate-200"
            }`}
          >
            <input
              type="radio"
              name="mode"
              value={mode}
              checked={form.mode === mode}
              disabled={mode === "replay" && !canReplay}
              onChange={() => update({ mode })}
            />
            {mode === "live" ? "Live (calls TinyFish)" : "Replay recorded trace"}
          </label>
        ))}
      </fieldset>

      {errors.length > 0 && (
        <div
          role="alert"
          className="space-y-2 rounded-lg border border-rose-500/50 bg-rose-950/60 p-3"
        >
          <ul className="list-inside list-disc text-sm text-rose-200">
            {errors.map((msg) => (
              <li key={msg}>{msg}</li>
            ))}
          </ul>
          {status === 503 && canReplay && form.mode !== "replay" && (
            <button
              type="button"
              className="rounded-md bg-amber-500/20 px-3 py-1.5 text-sm text-amber-200 hover:bg-amber-500/30"
              onClick={() => {
                update({ mode: "replay" });
                void submit("replay");
              }}
            >
              Switch to replay
            </button>
          )}
        </div>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="rounded-md bg-sky-600 px-5 py-2.5 font-semibold text-white hover:bg-sky-500 disabled:opacity-60"
      >
        {submitting ? "Starting…" : "Run"}
      </button>
    </form>
  );
}
