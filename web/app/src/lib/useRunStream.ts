'use client';

import { useEffect, useRef, useState } from 'react';

const API_BASE_URL =
  typeof window === 'undefined'
    ? process.env.API_BASE_URL ?? 'http://127.0.0.1:8000'
    : process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8000';

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

    const source = new EventSource(`${API_BASE_URL}/runs/${runId}/stream`);
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
