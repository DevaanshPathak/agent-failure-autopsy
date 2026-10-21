import Link from "next/link";

export default function NotFound() {
  return (
    <main className="max-w-2xl space-y-3">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="text-slate-300">
        <Link href="/" className="text-sky-300 underline underline-offset-4">
          Start a run
        </Link>
        ,{" "}
        <Link href="/results" className="text-sky-300 underline underline-offset-4">
          see results
        </Link>{" "}
        or{" "}
        <Link href="/dev" className="text-sky-300 underline underline-offset-4">
          open the sample run
        </Link>
        .
      </p>
    </main>
  );
}
