import { buildRunRequest, emptyRunForm, siteToForm, type BuildResult } from "./runRequest";
import type { SiteInfo } from "./types";

/** The one-click "prepared autopsy" cards: our own test pages first, then real websites. */
export interface ScenarioGroups {
  lab: SiteInfo[];
  real: SiteInfo[];
}

/** Sites that have a card (a title in fixtures/sites.yaml), split by kind, in file order. */
export function groupScenarios(sites: SiteInfo[]): ScenarioGroups {
  const cards = sites.filter((s) => Boolean(s.title));
  return {
    lab: cards.filter((s) => s.kind === "lab"),
    real: cards.filter((s) => s.kind !== "lab"),
  };
}

/** The live run a card starts: the site's own URL, goal, check, schema and start rung. */
export function scenarioRequest(site: SiteInfo): BuildResult {
  return buildRunRequest({ ...siteToForm(site, emptyRunForm), mode: "live" });
}
