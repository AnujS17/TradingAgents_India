'use client';

import { useEffect, useRef, useState } from 'react';

// Same-origin, NOT the FastAPI base URL. EventSource cannot set request
// headers (a spec limitation), so it can never send the bearer token the
// backend's stream endpoint requires -- pointing it straight at FastAPI
// returns 401 and the live view stays blank for the whole run. The route
// handler at app/api/runs/[runId]/stream attaches the token server-side;
// see its comment for why the backend endpoint is not simply opened up.
const STREAM_BASE_PATH = '/api/runs';

interface RunEventPayload {
  seq: number;
  node_name: string;
  text_delta: string;
}

// Accumulates streamed token deltas per node while a run is in progress.
// `enabled` gates the EventSource lifecycle -- pass `status !== 'completed'
// && status !== 'failed'` from the caller so this closes itself once a run
// finishes, at which point the existing poll-based RunView takes over.
export function useRunStream(runId: string, enabled: boolean) {
  const [eventsByNode, setEventsByNode] = useState<Record<string, string>>({});
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled) {
      sourceRef.current?.close();
      sourceRef.current = null;
      return;
    }

    const source = new EventSource(`${STREAM_BASE_PATH}/${encodeURIComponent(runId)}/stream`);
    sourceRef.current = source;

    source.onmessage = (event) => {
      const payload = JSON.parse(event.data) as RunEventPayload;
      setEventsByNode((prev) => ({
        ...prev,
        [payload.node_name]: (prev[payload.node_name] ?? '') + payload.text_delta,
      }));
    };

    source.addEventListener('done', () => {
      source.close();
    });

    source.onerror = () => {
      // EventSource retries automatically with Last-Event-ID; nothing to
      // do here beyond letting the browser's native reconnect handle it.
    };

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [runId, enabled]);

  return { eventsByNode };
}
