"use client"; // Error boundaries must be Client Components

import Link from "next/link";
import { useEffect } from "react";

export default function AppError({ error, retry }: { error: unknown; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  const message = error instanceof Error ? error.message : String(error);
  return (
    <main className="max-w-2xl space-y-4 rounded-lg border border-rose-500/50 bg-rose-950/40 p-6">
      <h1 className="text-2xl font-semibold text-rose-100">Something went wrong on this page</h1>
      <p className="break-words font-mono text-sm text-rose-200">{message}</p>
      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => retry()}
          className="rounded-md bg-slate-800 px-4 py-2 font-medium hover:bg-slate-700"
        >
          Try again
        </button>
        <Link
          href="/dev"
          className="rounded-md px-4 py-2 text-sky-300 underline underline-offset-4"
        >
          Open the sample run
        </Link>
      </div>
    </main>
  );
}
