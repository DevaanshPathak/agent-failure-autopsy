#!/usr/bin/env node
// Bundle recorded runs into apps/web/public/demo/ for the static demo deployment.
//
//   npm run demo:sync     write public/demo/index.json and public/demo/runs/*
//   npm run demo:check    exit 1 if the bundled files differ from the fixtures (CI drift check)
//
// Sources (repo root): fixtures/sample-run.jsonl (hand-written illustrative sample) and
// fixtures/traces/<id>.jsonl recordings, with optional fixtures/traces/<id>/attempt-<n>.jpg.
// Output is deterministic: sorted ids and keys, LF line endings, no timestamps of its own.

import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const flag = (name) =>
  process.argv.find((a) => a.startsWith(`--${name}=`))?.slice(name.length + 3) || null;
// --fixtures=DIR / --out=DIR exist for testing the script against scratch copies.
const FIXTURES = resolve(flag("fixtures") ?? join(WEB_ROOT, "..", "..", "fixtures"));
const OUT = resolve(flag("out") ?? join(WEB_ROOT, "public", "demo"));
const SAMPLE_TITLE = "Illustrative sample: cookie popup on a shop page";
const ID_RE = /^[a-z0-9][a-z0-9_-]*$/i;
const SHOT_RE = /^attempt-(\d+)\.jpg$/;

function readEvents(path) {
  const lines = readFileSync(path, "utf8")
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  const events = lines.map((line, i) => {
    try {
      return JSON.parse(line);
    } catch (err) {
      throw new Error(`${relative(WEB_ROOT, path)}:${i + 1}: invalid JSON (${err.message})`);
    }
  });
  return { text: lines.join("\n") + "\n", events };
}

function summarize(id, kind, events, screenshotAttempts) {
  const started = events.find((e) => e.type === "attempt_started");
  const verdict = events.findLast((e) => e.type === "verdict") ?? null;
  const budget = events.findLast((e) => e.type === "budget") ?? null;
  return {
    id,
    kind,
    title: kind === "sample" ? SAMPLE_TITLE : `Recorded run: ${id}`,
    url: started?.config?.url ?? null,
    goal: started?.config?.goal ?? null,
    recorded_at: events[0]?.ts ?? null,
    classes: events.filter((e) => e.type === "diagnosis").map((e) => e.diagnosis.failure_class),
    status: verdict?.status ?? null,
    attempts_used: verdict?.attempts_used ?? budget?.attempts_used ?? 0,
    credits_used: verdict?.credits_used ?? budget?.credits_used ?? 0,
    baseline_credits_estimate: verdict?.baseline_credits_estimate ?? null,
    events: events.length,
    has_screenshots: screenshotAttempts.length > 0,
    screenshot_attempts: screenshotAttempts,
    path: `/demo/runs/${id}.jsonl`,
  };
}

/** JSON with object keys sorted at every level, 2-space indent, trailing newline. */
function stableJson(value) {
  const sort = (v) =>
    Array.isArray(v)
      ? v.map(sort)
      : v && typeof v === "object"
        ? Object.fromEntries(
            Object.keys(v)
              .sort()
              .map((k) => [k, sort(v[k])]),
          )
        : v;
  return JSON.stringify(sort(value), null, 2) + "\n";
}

/** Every output file as relative path -> Buffer. */
function buildOutputs() {
  const files = new Map();
  const runs = [];

  const add = (id, kind, source, shotDir) => {
    if (!ID_RE.test(id)) {
      console.warn(`skipping ${relative(WEB_ROOT, source)}: "${id}" is not a safe run id`);
      return;
    }
    const { text, events } = readEvents(source);
    files.set(`runs/${id}.jsonl`, Buffer.from(text, "utf8"));
    const shots = [];
    if (shotDir && existsSync(shotDir)) {
      for (const name of readdirSync(shotDir).sort()) {
        const m = SHOT_RE.exec(name);
        if (!m) continue;
        shots.push(Number(m[1]));
        files.set(`runs/${id}/${name}`, readFileSync(join(shotDir, name)));
      }
    }
    runs.push(
      summarize(
        id,
        kind,
        events,
        shots.sort((a, b) => a - b),
      ),
    );
  };

  add("sample", "sample", join(FIXTURES, "sample-run.jsonl"), null);
  const traces = join(FIXTURES, "traces");
  if (existsSync(traces)) {
    for (const name of readdirSync(traces).sort()) {
      if (!name.endsWith(".jsonl")) continue;
      const id = name.slice(0, -".jsonl".length);
      if (id === "sample") {
        console.warn("skipping fixtures/traces/sample.jsonl: the id 'sample' is reserved");
        continue;
      }
      add(id, "recording", join(traces, name), join(traces, id));
    }
  }

  runs.sort((a, b) => a.id.localeCompare(b.id));
  files.set("index.json", Buffer.from(stableJson({ version: 1, runs }), "utf8"));
  return files;
}

function listExisting(dir, prefix = "") {
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true }).flatMap((d) =>
    d.isDirectory()
      ? listExisting(join(dir, d.name), `${prefix}${d.name}/`)
      : [`${prefix}${d.name}`],
  );
}

const normalize = (rel, buf) =>
  rel.endsWith(".jpg") ? buf : buf.toString("utf8").replace(/\r\n/g, "\n");

function check(files) {
  const problems = [];
  const existing = new Set(listExisting(OUT));
  for (const [rel, want] of files) {
    const path = join(OUT, rel);
    if (!existing.has(rel)) problems.push(`missing public/demo/${rel}`);
    else if (String(normalize(rel, readFileSync(path))) !== String(normalize(rel, want))) {
      if (!(rel.endsWith(".jpg") && readFileSync(path).equals(want))) {
        problems.push(`stale public/demo/${rel}`);
      }
    }
    existing.delete(rel);
  }
  for (const rel of existing) problems.push(`unexpected public/demo/${rel}`);
  return problems;
}

function write(files) {
  rmSync(join(OUT, "runs"), { recursive: true, force: true });
  rmSync(join(OUT, "index.json"), { force: true });
  for (const [rel, buf] of files) {
    const path = join(OUT, rel);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, buf);
  }
}

const files = buildOutputs();
if (process.argv.includes("--check")) {
  const problems = check(files);
  if (problems.length) {
    console.error(
      `public/demo is out of date (run npm run demo:sync):\n  ${problems.join("\n  ")}`,
    );
    process.exit(1);
  }
  console.log(`public/demo is up to date (${files.size} files)`);
} else {
  write(files);
  const runs = JSON.parse(files.get("index.json").toString("utf8")).runs;
  console.log(
    `wrote public/demo: ${runs.length} run(s): ${runs.map((r) => `${r.id} (${r.kind})`).join(", ")}`,
  );
}
