import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useRunStream } from '@/lib/useRunStream';

// Captures the URL EventSource is constructed with. The browser's real
// EventSource cannot set request headers (a spec limitation), so the ONLY
// thing keeping the live view authenticated is that this URL points at our
// own origin, where the route handler at app/api/runs/[runId]/stream can
// attach the bearer token server-side.
class FakeEventSource {
  static lastUrl: string | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  addEventListener = vi.fn();

  constructor(url: string) {
    FakeEventSource.lastUrl = url;
  }
}

describe('useRunStream', () => {
  beforeEach(() => {
    FakeEventSource.lastUrl = null;
    vi.stubGlobal('EventSource', FakeEventSource);
  });

  it('streams from our own origin, never straight at the API host', () => {
    // Regression guard for a real outage: this pointed at the FastAPI base
    // URL, whose /runs/{id}/stream requires a bearer token that EventSource
    // physically cannot send, so every live view got 401 and stayed blank
    // for the whole run while the backend happily wrote hundreds of events.
    renderHook(() => useRunStream('run-123', true));

    expect(FakeEventSource.lastUrl).toBe('/api/runs/run-123/stream');
    // An absolute URL means it is addressing another origin again --
    // the exact shape of the bug.
    expect(FakeEventSource.lastUrl).not.toMatch(/^https?:\/\//);
  });

  it('encodes the run id rather than interpolating it raw', () => {
    renderHook(() => useRunStream('a/b?c', true));

    expect(FakeEventSource.lastUrl).toBe('/api/runs/a%2Fb%3Fc/stream');
  });

  it('opens no connection at all while disabled', () => {
    renderHook(() => useRunStream('run-123', false));

    expect(FakeEventSource.lastUrl).toBeNull();
  });
});
