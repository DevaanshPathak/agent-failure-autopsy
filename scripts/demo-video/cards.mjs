// Renders the title and end cards as 1920x1080 PNGs. Usage: node cards.mjs <out-dir>
import { chromium } from "playwright-core";

const OUT = process.argv[2];
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const style = `
  * { box-sizing: border-box; margin: 0; }
  body { width: 1920px; height: 1080px; display: grid; place-items: center; overflow: hidden;
    font-family: "Segoe UI", system-ui, sans-serif; color: #f8fafc;
    background: radial-gradient(1200px 700px at 50% 35%, #0c2a4a 0%, #020617 70%); }
  .wrap { text-align: center; padding: 0 160px; }
  .kicker { font-size: 30px; letter-spacing: .18em; text-transform: uppercase; color: #7dd3fc; margin-bottom: 34px; }
  h1 { font-size: 112px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.05; }
  .sub { margin-top: 30px; font-size: 44px; color: #cbd5e1; }
  .steps { margin-top: 64px; display: flex; gap: 22px; justify-content: center; font-size: 30px; }
  .steps span { padding: 12px 26px; border-radius: 999px; border: 2px solid #334155; background: #0f172a; color: #e2e8f0; }
  .steps span.ok { border-color: #10b981; color: #6ee7b7; }
  .steps span.bad { border-color: #f43f5e; color: #fda4af; }
  .line { font-size: 52px; line-height: 1.35; color: #e2e8f0; }
  .line b { color: #f8fafc; }
  .url { margin-top: 70px; display: inline-block; font-family: Consolas, monospace; font-size: 58px; color: #38bdf8;
    padding: 18px 40px; border-radius: 16px; border: 2px solid #0ea5e9; background: rgba(14,165,233,.08); }
  .foot { margin-top: 48px; font-size: 28px; color: #94a3b8; }
`;
const title = `<div class="wrap">
  <div class="kicker">Swim with TinyFish</div>
  <h1>Agent Failure Autopsy</h1>
  <div class="sub">A reliability layer for TinyFish web agents</div>
  <div class="steps"><span>Verify</span><span class="bad">Diagnose</span><span>Fix</span><span class="ok">Stop honestly</span></div>
</div>`;
const end = `<div class="wrap">
  <div class="line"><b>Verify</b> every answer. <b>Diagnose</b> every failure.<br><b>Fix</b> what can be fixed. <b>Stop honestly</b> when it can't.</div>
  <div class="url">agent-failure-autopsy.vercel.app</div>
  <div class="foot">Built on TinyFish Fetch + Agent · diagnoses by rules first, Claude when unsure</div>
</div>`;

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
for (const [name, body] of [["title", title], ["end", end]]) {
  await page.setContent(`<!doctype html><html><head><style>${style}</style></head><body>${body}</body></html>`);
  await page.screenshot({ path: `${OUT}/card_${name}.png` });
}
await browser.close();
console.log("cards ok");
