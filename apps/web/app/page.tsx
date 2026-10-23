import DemoRunPicker from "@/components/DemoRunPicker";
import HowItWorks from "@/components/HowItWorks";
import LiveBudget from "@/components/LiveBudget";
import RunForm from "@/components/RunForm";
import { DEMO_MODE } from "@/lib/api";

const INTRO =
  "A reliability layer for TinyFish web agents: it runs your goal, checks the answer itself, " +
  "names what went wrong and at which step, fixes it, and stops honestly when a fix is impossible.";

export default function Home() {
  if (DEMO_MODE) {
    return (
      <main className="space-y-8">
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold">Agent Failure Autopsy</h1>
          <p className="max-w-4xl text-lg text-slate-300">{INTRO}</p>
        </div>
        <HowItWorks />
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold">Bundled runs</h2>
          <p className="text-slate-400">
            Each one replays a full run in your browser: the ladder, every step, the verifier, the
            diagnosis with its red failing step, and the verdict.
          </p>
          <DemoRunPicker />
        </section>
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold">Run your own</h2>
          <RunForm disabledNote="Live runs need the API, which isn't part of this demo deployment." />
        </section>
      </main>
    );
  }

  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Run an autopsy</h1>
        <p className="text-slate-400">
          Pick a demo site or paste any URL with a goal. We climb Fetch → Agent → Agent + stealth,
          verify every answer ourselves, and diagnose every failure.
        </p>
      </div>
      <LiveBudget />
      <RunForm />
      <section className="space-y-3">
        <h2 className="text-2xl font-semibold">Or watch a recorded run</h2>
        <p className="text-slate-400">
          These play in your browser from files bundled with the site, so they cost nothing: no
          TinyFish credits, no Claude calls. Each shows the ladder, every step, the verifier, the
          diagnosis with its red failing step, and the verdict.
        </p>
        <DemoRunPicker />
      </section>
      <HowItWorks />
    </main>
  );
}
