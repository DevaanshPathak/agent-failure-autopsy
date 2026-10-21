"use client";

import type { AttemptView, RunViewState } from "@/lib/runState";
import type { RunMode } from "@/lib/types";

interface Props {
  liveView: RunViewState["liveView"];
  attempt: AttemptView | null;
  mode: RunMode | null;
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

export default function BrowserPanel({ liveView, attempt, mode }: Props) {
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

  const failing = attempt.events.find((e) => e.seq === attempt.failingSeq);
  return (
    <Frame>
      <Message
        title="Live view ended"
        detail={
          failing
            ? `Failed at ${failing.step_no ? `step ${failing.step_no}` : failing.kind}: ${failing.label}`
            : attempt.verify?.summary
        }
      />
    </Frame>
  );
}
