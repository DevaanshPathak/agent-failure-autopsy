import { RUNG_LABEL, RUNG_ORDER } from "./format";
import type { AttemptConfig, Patch, Rung } from "./types";

/**
 * Short chips describing what the patch changes for the next attempt. `rung` is the rung the
 * diagnosed attempt ran on; `nextConfig` (once the next attempt has started) supplies the
 * proxy country.
 */
export function patchChips(patch: Patch, rung: Rung, nextConfig?: AttemptConfig | null): string[] {
  if (patch.stop) return [];
  const chips: string[] = [];
  const toRung = patch.next_rung;
  if (toRung && toRung !== rung) chips.push(`→ ${RUNG_LABEL[toRung]}`);

  const onStealth = rung === "agent_stealth";
  const wantsStealth = patch.browser_profile === "stealth" || toRung === "agent_stealth";
  if (wantsStealth && !onStealth) chips.push("lite → stealth");
  const wantsProxy = patch.proxy_enabled === true || toRung === "agent_stealth";
  if (wantsProxy && !onStealth) chips.push(`proxy off → ${nextConfig?.proxy_country || "on"}`);

  for (const skipped of patch.skip_rungs)
    chips.push(`Skip Rung ${RUNG_ORDER.indexOf(skipped) + 1}`);
  if (patch.reextract_from_fetch) chips.push("0 credits · cached Fetch");
  return chips;
}
