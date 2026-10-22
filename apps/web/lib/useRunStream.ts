import { useEffect, useReducer, useRef, useState } from "react";

import { parseDemoUrl, playDemo } from "./demoSource";
import { initialRunViewState, reduceRun, type RunViewState } from "./runState";
import type { UiEvent } from "./types";

export interface RunStream {
  state: RunViewState;
  /** Every accepted event in order (duplicates from reconnects are dropped). */
  events: UiEvent[];
  connected: boolean;
  error: string | null;
}

interface StreamState {
  view: RunViewState;
  events: UiEvent[];
}

const initialStreamState: StreamState = { view: initialRunViewState, events: [] };

function reduceStream(s: StreamState, event: UiEvent): StreamState {
  const view = reduceRun(s.view, event);
  return view === s.view ? s : { view, events: [...s.events, event] };
}

function withAfter(url: string, after: number): string {
  if (after <= 0) return url;
  return `${url}${url.includes("?") ? "&" : "?"}after=${after}`;
}

/**
 * Subscribe to a run's UI event stream (SSE) and reduce it into view state. A `demo:<path>`
 * URL plays a bundled JSONL recording in the browser instead (static demo deployment).
 *
 * EventSource reconnects by itself and sends `Last-Event-ID`. When the effect re-runs (for
 * example when Next.js hides and re-shows the route), the new connection resumes with
 * `?after=<lastSeq>`; the reducer drops anything already seen either way.
 */
export function useRunStream(url: string | null): RunStream {
  const [stream, dispatch] = useReducer(reduceStream, initialStreamState);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const progress = useRef({ lastSeq: 0, done: false });

  useEffect(() => {
    progress.current = { lastSeq: stream.view.lastSeq, done: stream.view.done };
  }, [stream.view.lastSeq, stream.view.done]);

  useEffect(() => {
    if (!url || progress.current.done) return;

    // `demo:<path>`: play a bundled recording in the browser (static demo, no API).
    const demo = parseDemoUrl(url);
    if (demo) {
      const playback = playDemo(
        demo.path,
        (event) => {
          dispatch(event);
          if (event.type === "verdict") setConnected(false);
        },
        {
          speed: demo.speed,
          after: progress.current.lastSeq,
          onStart: () => {
            setConnected(true);
            setError(null);
          },
          onDone: () => setConnected(false),
          onError: (message) => {
            setConnected(false);
            setError(`Can't play this recorded run: ${message}`);
          },
        },
      );
      return () => playback.cancel();
    }

    const es = new EventSource(withAfter(url, progress.current.lastSeq));

    es.onopen = () => {
      setConnected(true);
      setError(null);
    };
    es.onmessage = (message: MessageEvent<string>) => {
      let event: UiEvent;
      try {
        event = JSON.parse(message.data) as UiEvent;
      } catch {
        setError("Received an unreadable event from the API");
        return;
      }
      if (typeof event?.seq !== "number" || typeof event?.type !== "string") {
        setError("Received a malformed event from the API");
        return;
      }
      dispatch(event);
      if (event.type === "verdict") {
        es.close();
        setConnected(false);
      }
    };
    es.onerror = () => {
      setConnected(false);
      if (es.readyState === EventSource.CLOSED) setError("The event stream closed");
      else if (progress.current.lastSeq === 0) setError("Can't reach the API yet — retrying…");
    };

    return () => es.close();
  }, [url]);

  return { state: stream.view, events: stream.events, connected, error };
}
