import { useEffect, useReducer, useRef, useState } from "react";

import { initialRunViewState, reduceRun, type RunViewState } from "./runState";
import type { UiEvent } from "./types";

export interface RunStream {
  state: RunViewState;
  connected: boolean;
  error: string | null;
}

function withAfter(url: string, after: number): string {
  if (after <= 0) return url;
  return `${url}${url.includes("?") ? "&" : "?"}after=${after}`;
}

/**
 * Subscribe to a run's UI event stream (SSE) and reduce it into view state.
 *
 * EventSource reconnects by itself and sends `Last-Event-ID`. When the effect re-runs (for
 * example when Next.js hides and re-shows the route), the new connection resumes with
 * `?after=<lastSeq>`; the reducer drops anything already seen either way.
 */
export function useRunStream(url: string | null): RunStream {
  const [state, dispatch] = useReducer(reduceRun, initialRunViewState);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const progress = useRef({ lastSeq: 0, done: false });

  useEffect(() => {
    progress.current = { lastSeq: state.lastSeq, done: state.done };
  }, [state.lastSeq, state.done]);

  useEffect(() => {
    if (!url || progress.current.done) return;
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
      dispatch(event);
      if (event.type === "verdict") {
        es.close();
        setConnected(false);
      }
    };
    es.onerror = () => {
      setConnected(false);
      if (es.readyState === EventSource.CLOSED) setError("The event stream closed");
    };

    return () => es.close();
  }, [url]);

  return { state, connected, error };
}
