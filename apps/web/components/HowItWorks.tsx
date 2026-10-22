const STEPS = [
  "You give a URL, a plain-English goal and, optionally, a check the answer must pass.",
  "Rung 1 reads the page with TinyFish Fetch (free). Rung 2 runs the TinyFish agent in a live browser. Rung 3 adds a stealth browser and a proxy. A run climbs only as far as it needs to.",
  "After every attempt an independent verifier checks the result against your check, the output schema and block signals. It never trusts the agent's own “COMPLETED”.",
  "A failed attempt is diagnosed (rules first, Claude when the rules are unsure): the failure class, the step where it failed, the evidence, and a patch for the next attempt.",
  "A hard budget caps attempts and credits, and login walls and captchas stop at once with an honest reason.",
];

export default function HowItWorks() {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
      <h2 className="text-lg font-semibold">How it works</h2>
      <ol className="mt-2 list-inside list-decimal space-y-1.5 text-slate-200">
        {STEPS.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
    </section>
  );
}
