import { getToken } from 'next-auth/jwt';

// Same-origin SSE proxy for the run token stream.
//
// The browser's EventSource API cannot set request headers -- that is a
// hard limit of the spec, not an oversight here -- so it has no way to
// send the bearer token every other API call carries. FastAPI's
// GET /runs/{id}/stream requires one (api/routers/runs.py's stream_run
// takes CurrentUserDep and calls _authorize_run_access), so a direct
// EventSource to the backend gets a flat 401 and the live view stays
// blank. Verified against the running server: the exact request an
// EventSource makes returns {"detail":"Not authenticated"}.
//
// Routing it through this handler fixes both halves at once: the browser
// talks to its own origin (no cross-origin restriction to fight), and
// this handler -- ordinary server code, not a browser -- attaches the
// token before calling FastAPI.
//
// Deliberately NOT solved by dropping auth on the backend endpoint. That
// route replays from seq 0 when no Last-Event-ID is sent, and run_events
// is never pruned, so it is a full-transcript read rather than a live
// tail. Leaving it open would let anyone holding a run id read the whole
// analysis of a run they do not own, while GET /runs/{id} still answers
// 404 to that same person -- the ownership model in 0cb1bbd/329284e,
// defeated by its own side door.
//
// Also deliberately not a `?token=` query param: that puts a live
// credential into browser history and server access logs.

const API_BASE_URL = process.env.API_BASE_URL ?? 'http://127.0.0.1:8000';

// Route Handlers are uncached by default, but this one streams for
// minutes and must never be statically evaluated at build time.
export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  // Next 16: params is a Promise and must be awaited (see
  // node_modules/next/dist/docs/01-app/01-getting-started/15-route-handlers.md).
  context: { params: Promise<{ runId: string }> },
) {
  const { runId } = await context.params;

  // Same server-side branch getBearerToken() uses in lib/api-client/client.ts:
  // read the caller's own cookies and hand back the raw signed JWT that
  // api.auth.decode_token verifies. Needs NEXTAUTH_SECRET.
  const { cookies, headers } = await import('next/headers');
  const token = await getToken({
    req: { headers: await headers(), cookies: await cookies() } as never,
    secret: process.env.NEXTAUTH_SECRET,
    raw: true,
  });

  if (!token) {
    return new Response('Not authenticated', { status: 401 });
  }

  const upstreamHeaders = new Headers({
    Authorization: `Bearer ${token as unknown as string}`,
    Accept: 'text/event-stream',
  });

  // Forwarded so a reconnecting EventSource resumes where it left off
  // instead of replaying the whole run -- the backend reads this header
  // by name and the browser sets it automatically on reconnect.
  const lastEventId = request.headers.get('Last-Event-ID');
  if (lastEventId) upstreamHeaders.set('Last-Event-ID', lastEventId);

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE_URL}/runs/${encodeURIComponent(runId)}/stream`, {
      headers: upstreamHeaders,
      // Closing the EventSource aborts this request too, so the backend's
      // `await request.is_disconnected()` check ends its polling loop
      // rather than leaving it running for a client that has gone away.
      signal: request.signal,
      cache: 'no-store',
    });
  } catch (reason) {
    const message = reason instanceof Error ? reason.message : 'Upstream unreachable';
    return new Response(message, { status: 502 });
  }

  if (!upstream.ok || !upstream.body) {
    // Pass the real status through (401/404 especially) so the caller
    // sees why, rather than a generic failure.
    return new Response(await upstream.text().catch(() => ''), {
      status: upstream.status,
    });
  }

  // upstream.body is piped straight through, never buffered -- awaiting
  // the text here would defeat the entire point and deliver the run's
  // output in one lump at the end.
  return new Response(upstream.body, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream',
      // no-transform additionally stops intermediaries from re-chunking
      // or compressing the stream, which breaks SSE framing.
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      // nginx-family proxies buffer responses by default, which holds
      // events back until the buffer fills. Harmless when absent.
      'X-Accel-Buffering': 'no',
    },
  });
}
