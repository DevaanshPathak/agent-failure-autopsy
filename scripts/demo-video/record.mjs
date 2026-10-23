// Records the demo: drives the live site in Chrome and saves every screencast frame with its
// timestamp, plus scene marks. Usage: node record.mjs <out-dir>
import fs from "node:fs";
import { chromium } from "playwright-core";

const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const BASE = "https://agent-failure-autopsy.vercel.app";
const OUT = process.argv[2];
fs.mkdirSync(`${OUT}/frames`, { recursive: true });

// A visible cursor (headless screencasts have none) with a ring on click.
const CURSOR = `
(() => {
  const install = () => {
    if (document.getElementById("__cursor")) return;
    const c = document.createElement("div");
    c.id = "__cursor";
    c.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2l16 9.5-7 1.6-3.6 6.9z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, { position: "fixed", left: "0", top: "0", zIndex: 2147483647, pointerEvents: "none",
      transform: "translate(" + (window.__cx ?? 760) + "px," + (window.__cy ?? 420) + "px)", filter: "drop-shadow(0 2px 3px rgba(0,0,0,.5))" });
    document.body.appendChild(c);
    addEventListener("mousemove", (e) => {
      window.__cx = e.clientX; window.__cy = e.clientY;
      c.style.transform = "translate(" + e.clientX + "px," + e.clientY + "px)";
    }, true);
    addEventListener("mousedown", (e) => {
      const r = document.createElement("div");
      Object.assign(r.style, { position: "fixed", left: e.clientX - 18 + "px", top: e.clientY - 18 + "px", width: "36px", height: "36px",
        borderRadius: "50%", border: "3px solid #38bdf8", zIndex: 2147483646, pointerEvents: "none", transition: "all .45s ease-out", opacity: "1" });
      document.body.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = "scale(1.8)"; r.style.opacity = "0"; });
      setTimeout(() => r.remove(), 600);
    }, true);
  };
  if (document.body) install(); else addEventListener("DOMContentLoaded", install);
})();`;

const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ["--hide-scrollbars"] });
const context = await browser.newContext({ viewport: { width: 1536, height: 864 }, deviceScaleFactor: 1.25 });
await context.addInitScript(CURSOR);
const page = await context.newPage();
const cdp = await context.newCDPSession(page);

const frames = [];
let n = 0;
cdp.on("Page.screencastFrame", async ({ data, metadata, sessionId }) => {
  const file = `f${String(n++).padStart(6, "0")}.jpg`;
  fs.writeFileSync(`${OUT}/frames/${file}`, Buffer.from(data, "base64"));
  frames.push({ file, ts: metadata.timestamp ?? Date.now() / 1000 });
  cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
});
const screencast = () =>
  cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 }).catch(() => {});

const marks = [];
const mark = (name) => {
  marks.push({ name, ts: Date.now() / 1000 });
  console.log(new Date().toISOString().slice(11, 19), "mark", name);
};
const sleep = (ms) => page.waitForTimeout(ms);
let cursor = { x: 760, y: 420 };
async function moveTo(x, y, steps = 30) {
  await page.mouse.move(x, y, { steps });
  cursor = { x, y };
}
async function moveToLocator(loc) {
  await loc.scrollIntoViewIfNeeded();
  const box = await loc.boundingBox();
  await moveTo(box.x + box.width / 2, box.y + box.height / 2);
}
async function smoothScrollTo(y, ms = 1400) {
  await page.evaluate(
    ([target, dur]) =>
      new Promise((done) => {
        const start = scrollY;
        const t0 = performance.now();
        const step = (t) => {
          const k = Math.min(1, (t - t0) / dur);
          scrollTo(0, start + (target - start) * (k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2));
          k < 1 ? requestAnimationFrame(step) : done();
        };
        requestAnimationFrame(step);
      }),
    [y, ms],
  );
}
async function scrollToLocator(loc, offset = 90, ms = 1400) {
  const top = await loc.evaluate((el, off) => el.getBoundingClientRect().top + scrollY - off, offset);
  await smoothScrollTo(Math.max(0, top), ms);
}
async function goHome() {
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /Run live/ }).first().waitFor({ timeout: 30000 });
  await sleep(600);
}

/** Click a card's Run live; if the live slot is busy (429), wait and try again. */
async function runCard(title) {
  const card = page.locator("article", { has: page.getByRole("heading", { name: title }) });
  const button = card.getByRole("button", { name: /Run live/ });
  await scrollToLocator(card, 140, 1200);
  await sleep(500);
  for (let tryNo = 1; tryNo <= 12; tryNo++) {
    await moveToLocator(button);
    await sleep(350);
    await page.mouse.down();
    await page.mouse.up();
    try {
      await page.waitForURL(/\/runs\/[a-f0-9]+/, { timeout: 15000 });
      return;
    } catch {
      console.log("  start refused, retrying:", await card.locator("[role=alert]").textContent().catch(() => "?"));
      await sleep(10000);
    }
  }
  throw new Error(`could not start ${title}`);
}

async function followRun(maxMs = 300000) {
  const verdict = page.locator("section.border-2 .text-5xl");
  await verdict.waitFor({ timeout: maxMs });
  await sleep(1200);
  const section = page.locator("section.border-2").first();
  await scrollToLocator(section, 200, 1600);
  await sleep(4500);
  return (await verdict.textContent())?.trim();
}

await page.goto(BASE + "/", { waitUntil: "networkidle" });
await screencast();
await page.getByRole("button", { name: /Run live/ }).first().waitFor({ timeout: 30000 });
await moveTo(1100, 300, 1);
await sleep(1500);

// 1. Intro: the home page, slowly drifting down to the budget panel.
mark("intro");
await moveTo(700, 260, 40);
await sleep(5000);
await moveTo(420, 330, 40);
await sleep(9000);

// 2. The prepared autopsy cards.
mark("cards");
await scrollToLocator(page.getByRole("heading", { name: "Prepared autopsies" }), 40, 1800);
await sleep(800);
for (const title of ["Chart that loads on click", "Shop behind a cookie wall", "Catalog that shows half"]) {
  await moveToLocator(page.getByRole("heading", { name: title }));
  await sleep(1600);
}
await sleep(6000);

// 3. A fixable failure: chart that loads on click.
mark("run1");
await runCard("Chart that loads on click");
await screencast();
console.log("  run1:", await followRun());
mark("run1-done");

// 4. An honest stop at a login wall.
await goHome();
await screencast();
mark("run2");
await runCard("Account behind a login");
await screencast();
console.log("  run2:", await followRun());
mark("run2-done");

// 5. Bot block: escalate to stealth + proxy, then stop.
await goHome();
await screencast();
mark("run3");
await runCard("Page that blocks bots");
await screencast();
console.log("  run3:", await followRun());
mark("run3-done");

// 6. Results.
await page.goto(BASE + "/results", { waitUntil: "networkidle" });
await screencast();
mark("results");
await sleep(5000);
await moveTo(500, 520, 40);
await sleep(4000);
await smoothScrollTo(420, 2200);
await sleep(8000);
mark("results-done");

// 7. Close on the home page.
await page.goto(BASE + "/", { waitUntil: "networkidle" });
await screencast();
mark("end");
await sleep(9000);
mark("stop");

await cdp.send("Page.stopScreencast");
fs.writeFileSync(`${OUT}/frames.json`, JSON.stringify(frames));
fs.writeFileSync(`${OUT}/marks.json`, JSON.stringify(marks, null, 1));
await browser.close();
console.log("frames:", frames.length);
