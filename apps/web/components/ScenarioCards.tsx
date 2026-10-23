"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { createRun, getSites } from "@/lib/api";
import { CLASS_COLOR, CLASS_LABEL, RUNG_LABEL } from "@/lib/format";
import { apiErrorMessages } from "@/lib/runRequest";
import { groupScenarios, scenarioRequest, type ScenarioGroups } from "@/lib/scenarios";
import type { SiteInfo } from "@/lib/types";

interface CardProps {
  site: SiteInfo;
  starting: string | null;
  error: string | undefined;
  onRun: (site: SiteInfo) => void;
}

function ScenarioCard({ site, starting, error, onRun }: CardProps) {
  const lab = site.kind === "lab";
  return (
    <article className="flex flex-col gap-3 rounded-lg border border-slate-700 bg-slate-900/60 p-5">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span
          className={`rounded-full px-2.5 py-0.5 font-semibold ring-1 ${
            lab
              ? "bg-sky-500/15 text-sky-200 ring-sky-400/40"
              : "bg-emerald-500/15 text-emerald-200 ring-emerald-400/40"
          }`}
        >
          {lab ? "Test page" : "Real website"}
        </span>
        {site.expected_class && (
          <span className={`rounded px-2 py-0.5 ${CLASS_COLOR[site.expected_class]}`}>
            {CLASS_LABEL[site.expected_class]}
          </span>
        )}
      </div>
      <h4 className="text-lg font-semibold text-slate-50">{site.title}</h4>
      {site.summary && <p className="text-sm text-slate-300">{site.summary}</p>}
      <p className="text-sm text-slate-400">
        Starts at {RUNG_LABEL[site.start_rung ?? "fetch"]}
        {site.cost_hint && ` · ${site.cost_hint}`}
      </p>
      {error && (
        <p
          role="alert"
          className="rounded border border-rose-500/50 bg-rose-950/60 px-2 py-1 text-sm text-rose-200"
        >
          {error}
        </p>
      )}
      <div className="mt-auto flex flex-wrap items-center gap-4 pt-1">
        <button
          type="button"
          disabled={starting !== null}
          onClick={() => onRun(site)}
          className="rounded-md bg-sky-600 px-5 py-2.5 font-semibold text-white hover:bg-sky-500 disabled:opacity-60"
        >
          {starting === site.id ? "Starting…" : "▶ Run live"}
        </button>
        <a
          href={site.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-sky-300 hover:underline"
        >
          View the page ↗
        </a>
      </div>
    </article>
  );
}

/**
 * One-click live runs on sites prepared in advance (fixtures/sites.yaml entries with a title):
 * our own test pages built to fail, then real websites. Each click spends the shared budget.
 */
export default function ScenarioCards() {
  const router = useRouter();
  const [groups, setGroups] = useState<ScenarioGroups | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    getSites()
      .then((sites) => {
        if (!cancelled) setGroups(groupScenarios(Array.isArray(sites) ? sites : []));
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(apiErrorMessages(err)[0] ?? String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function run(site: SiteInfo) {
    const built = scenarioRequest(site);
    if (!built.ok) {
      setErrors({ [site.id]: built.errors.join(" ") });
      return;
    }
    setStarting(site.id);
    setErrors({});
    try {
      const created = await createRun(built.request);
      router.push(`/runs/${encodeURIComponent(created.run_id)}`);
    } catch (err) {
      setErrors({ [site.id]: apiErrorMessages(err).join(" ") });
      setStarting(null);
    }
  }

  if (loadError) {
    return <p className="text-amber-200">Prepared autopsies are unavailable: {loadError}</p>;
  }
  if (!groups) return <p className="animate-pulse text-slate-400">Loading prepared autopsies…</p>;
  if (groups.lab.length === 0 && groups.real.length === 0) return null;

  const sections = [
    {
      key: "lab",
      title: "Test pages built to fail",
      blurb: "Our own pages, each built to trip one failure on purpose. All data on them is fictional.",
      sites: groups.lab,
    },
    {
      key: "real",
      title: "Real websites",
      blurb: "Public sites (scraping sandboxes where possible) with the same failures in the wild. Less predictable: real sites change.",
      sites: groups.real,
    },
  ].filter((s) => s.sites.length > 0);

  return (
    <section className="space-y-5">
      <div className="space-y-1">
        <h2 className="text-2xl font-semibold">Prepared autopsies</h2>
        <p className="text-slate-400">
          One click starts a live run on a site prepared in advance. It calls TinyFish and Claude
          for real, so it spends the shared budget.
        </p>
      </div>
      {sections.map((section) => (
        <div key={section.key} className="space-y-3">
          <div>
            <h3 className="text-lg font-semibold text-slate-100">{section.title}</h3>
            <p className="text-sm text-slate-400">{section.blurb}</p>
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {section.sites.map((site) => (
              <ScenarioCard
                key={site.id}
                site={site}
                starting={starting}
                error={errors[site.id]}
                onRun={run}
              />
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}
