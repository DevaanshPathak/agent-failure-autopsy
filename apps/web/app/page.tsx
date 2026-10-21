import Link from "next/link";

export default function Home() {
  return (
    <main className="max-w-2xl space-y-3">
      <h1 className="text-2xl font-semibold">Run an autopsy</h1>
      <p className="text-slate-300">
        The run form (demo sites and a paste-any-URL box) arrives in Phase 2. Until then, the{" "}
        <Link href="/dev" className="text-sky-300 underline underline-offset-4">
          sample run
        </Link>{" "}
        shows the full trace stream without any API keys.
      </p>
    </main>
  );
}
