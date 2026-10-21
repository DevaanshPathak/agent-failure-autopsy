import RunForm from "@/components/RunForm";

export default function Home() {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Run an autopsy</h1>
        <p className="text-slate-400">
          Pick a demo site or paste any URL with a goal. We climb Fetch → Agent → Agent + stealth,
          verify every answer ourselves, and diagnose every failure.
        </p>
      </div>
      <RunForm />
    </main>
  );
}
