import Link from "next/link";

import { CLASS_COLOR, CLASS_LABEL, STATUS_LABEL, STATUS_STYLE } from "@/lib/format";
import type { StatsRow } from "@/lib/types";

function time(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default function ResultsTable({ rows }: { rows: StatsRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-slate-700 p-6 text-center text-slate-400">
        No runs yet. Start one from the Run page.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800">
      <table className="w-full min-w-[56rem] text-left text-sm">
        <thead className="bg-slate-900 text-slate-300">
          <tr>
            {[
              "Time",
              "Site / URL",
              "Classes",
              "Status",
              "Attempts",
              "Credits",
              "Baseline",
              "Mode",
              "",
            ].map((h) => (
              <th key={h} scope="col" className="px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.map((r) => (
            <tr key={r.run_id} className="hover:bg-slate-900/60">
              <td className="whitespace-nowrap px-3 py-2 font-mono tabular-nums text-slate-300">
                {time(r.created_at)}
              </td>
              <td className="max-w-[20rem] px-3 py-2">
                <div className="font-medium text-slate-100">{r.site_id ?? "custom"}</div>
                <div className="truncate font-mono text-sm text-slate-400" title={r.url}>
                  {r.url}
                </div>
              </td>
              <td className="px-3 py-2">
                <div className="flex flex-wrap gap-1">
                  {r.classes.length === 0 && <span className="text-slate-400">—</span>}
                  {r.classes.map((c, i) => (
                    <span
                      key={`${c}-${i}`}
                      className={`rounded px-1.5 py-0.5 text-sm ${CLASS_COLOR[c]}`}
                    >
                      {CLASS_LABEL[c]}
                    </span>
                  ))}
                </div>
              </td>
              <td className={`whitespace-nowrap px-3 py-2 font-semibold ${STATUS_STYLE[r.status]}`}>
                {STATUS_LABEL[r.status]}
              </td>
              <td className="px-3 py-2 tabular-nums text-slate-200">{r.attempts}</td>
              <td className="px-3 py-2 tabular-nums text-slate-200">{r.credits_used}</td>
              <td className="px-3 py-2 tabular-nums text-slate-300">
                {r.baseline_credits_estimate ?? "—"}
              </td>
              <td className="px-3 py-2">
                <span className={r.mode === "replay" ? "text-amber-300" : "text-emerald-300"}>
                  {r.mode === "replay" ? "replay" : "live"}
                </span>
              </td>
              <td className="px-3 py-2">
                <Link
                  href={`/runs/${encodeURIComponent(r.run_id)}`}
                  className="text-sky-300 underline underline-offset-4 hover:text-sky-200"
                >
                  open
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
