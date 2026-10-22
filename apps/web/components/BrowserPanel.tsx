"use client";

import { useState } from "react";

import { screenshotUrl } from "@/lib/api";
import type { AttemptView, RunViewState } from "@/lib/runState";
import type { RunMode } from "@/lib/types";

interface Props {
  liveView: RunViewState["liveView"];
  attempt: AttemptView | null;
  mode: RunMode | null;
  runId: string;
  /**
   * Where the failing-step screenshot of an attempt lives (null = there is none, show the
   * overlay without a request). Defaults to the API endpoint.
   */
  screenshotSrc?: (attemptNo: number) => string | null;
}

/** "Step k — label" for the attempt's failing step, else the verifier summary. */
export function failingCaption(attempt: AttemptView): string {
  const failing = attempt.events.find((e) => e.seq === attempt.failingSeq);
  if (!failing) return attempt.verify?.summary ?? "";
  return `${failing.step_no ? `Step ${failing.step_no}` : "Failing step"} — ${failing.label}`;
}

/** Hostnames on the reserved `.invalid` TLD come from the sample fixture, never TinyFish. */
export function isPlaceholderUrl(url: string): boolean {
  try {
    return new URL(url).hostname.endsWith(".invalid");
  } catch {
    return true;
  }
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-lg border border-slate-800 bg-slate-900">
      {children}
    </div>
  );
}

function Message({ title, detail, pulse }: { title: string; detail?: string; pulse?: boolean }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
      <p className={`text-lg font-medium text-slate-200 ${pulse ? "animate-pulse" : ""}`}>
        {title}
      </p>
      {detail && <p className="max-w-md text-sm text-slate-400">{detail}</p>}
    </div>
  );
}

/** The failing step's screenshot; falls back to an overlay when there is none. */
function FailingShot({ src, attempt }: { src: string | null; attempt: AttemptView }) {
  const [broken, setBroken] = useState(false);
  const caption = failingCaption(attempt);
  if (broken || !src) {
    return (
      <Frame>
        <Message title="Live view ended" detail={caption} />
      </Frame>
    );
  }
  return (
    <Frame>
      <figure className="h-full w-full">
        {/* A dynamic API image: next/image would need remotePatterns for no benefit here. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt={`Browser at the failing step: ${caption}`}
          className="h-full w-full object-contain"
          onError={() => setBroken(true)}
        />
        <figcaption className="absolute inset-x-0 bottom-0 border-t border-rose-500/50 bg-slate-950/85 px-3 py-2 text-rose-100">
          {caption}
        </figcaption>
      </figure>
    </Frame>
  );
}

export default function BrowserPanel({ liveView, attempt, mode, runId, screenshotSrc }: Props) {
  if (!attempt) {
    return (
      <Frame>
        <Message title="Waiting for the first attempt…" pulse />
      </Frame>
    );
  }

  if (attempt.rung === "fetch") {
    return (
      <Frame>
        <Message
          title="Rung 1 is a read-only fetch — no browser"
          detail="TinyFish Fetch returns the page text; we extract the answer from it for 0 credits."
        />
      </Frame>
    );
  }

  const view = liveView && liveView.attemptNo === attempt.attemptNo ? liveView : null;

  // After a diagnosed attempt ends, show where it failed (live and replay alike).
  if (attempt.diagnosis && !view?.active) {
    const src = screenshotSrc
      ? screenshotSrc(attempt.attemptNo)
      : screenshotUrl(runId, attempt.attemptNo);
    return <FailingShot key={`${runId}:${attempt.attemptNo}`} src={src} attempt={attempt} />;
  }

  if (!view) {
    return (
      <Frame>
        {attempt.status === "running" ? (
          <Message
            title="Waiting for live view…"
            detail="TinyFish sends it a few seconds in."
            pulse
          />
        ) : (
          <Message title="No live view for this attempt" />
        )}
      </Frame>
    );
  }

  if (view.active) {
    if (mode === "replay" || isPlaceholderUrl(view.url)) {
      return (
        <Frame>
          <Message
            title={
              mode === "replay" ? "Recorded run — live view not available" : "Sample live view"
            }
            detail="The real run streams TinyFish's browser here."
          />
        </Frame>
      );
    }
    return (
      <Frame>
        <iframe
          src={view.url}
          title={`Live browser for attempt ${attempt.attemptNo}`}
          className="h-full w-full"
          referrerPolicy="no-referrer"
          allow="fullscreen"
        />
      </Frame>
    );
  }

  return (
    <Frame>
      <Message title="Live view ended" detail={attempt.verify?.summary} />
    </Frame>
  );
}
