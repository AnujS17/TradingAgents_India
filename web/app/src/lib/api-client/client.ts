import { getToken } from 'next-auth/jwt';

import type { components } from './types.gen';

export type RunDetail = components['schemas']['RunDetail'];
export type RunSummary = components['schemas']['RunSummary'];
export type RunHistory = components['schemas']['RunHistory'];
export type RunAccepted = components['schemas']['RunAccepted'];
export type VapidPublicKey = components['schemas']['VapidPublicKey'];
export type Verdict = components['schemas']['Verdict'];
export type Reports = components['schemas']['Reports'];
export type NewsSource = components['schemas']['NewsSource'];
export type AnalysisProfile = components['schemas']['AnalysisProfile'];
export type RunStatus = components['schemas']['RunStatus'];

const API_BASE_URL =
  typeof window === 'undefined'
    ? process.env.API_BASE_URL ?? 'http://127.0.0.1:8000'
    : process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8000';

/** The one function every exported call below routes through. Attaches
 * the signed-in user's bearer token, working in both contexts this file
 * is imported from: a Server Component (no `window`, reads the request's
 * own cookies via next-auth/jwt) and a Client Component (has `window`,
 * asks next-auth/react for the current session). */
async function getBearerToken(): Promise<string | null> {
  if (typeof window === 'undefined') {
    // Server Component / Route Handler context. NEXTAUTH_SECRET must be
    // set for this to return anything -- see .env.example.
    const { headers, cookies } = await import('next/headers');
    const token = await getToken({
      req: { headers: await headers(), cookies: await cookies() } as never,
      secret: process.env.NEXTAUTH_SECRET,
      raw: true,
    });
    return (token as unknown as string) ?? null;
  }
  const { getSession } = await import('next-auth/react');
  const session = await getSession();
  return (session as (typeof session & { accessToken?: string }) | null)?.accessToken ?? null;
}

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = await getBearerToken();
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  return fetch(`${API_BASE_URL}${path}`, { ...init, headers });
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Thrown on 429. `detail` is pre-written server copy — render it verbatim,
 * don't write custom error text for it (DEV_HANDOFF.md). */
export class RateLimitError extends Error {
  constructor(public detail: string, public retryAfterSeconds: number) {
    super(detail);
    this.name = 'RateLimitError';
  }
}

export interface AnalyzeResult {
  /** true when the server returned 200 (existing run, free). false means 202
   * (a new run was queued and money was spent). */
  cached: boolean;
  accepted: RunAccepted;
}

export interface AnalyzePayload {
  ticker: string;
  analysis_date?: string;
  profile?: AnalysisProfile;
  force?: boolean;
  refresh_data?: boolean;
  time_horizon?: string;
}

export async function analyzeRun(payload: AnalyzePayload): Promise<AnalyzeResult> {
  const res = await apiFetch('/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (res.status === 429) {
    const body = await res.json().catch(() => ({ detail: 'Rate limited.' }));
    const retryAfterSeconds = Number(res.headers.get('Retry-After') ?? '3600');
    throw new RateLimitError(body.detail ?? 'Rate limited.', retryAfterSeconds);
  }

  if (res.status !== 200 && res.status !== 202) {
    throw new ApiError(res.status, `Unexpected response (${res.status}) from POST /analyze`);
  }

  const accepted = (await res.json()) as RunAccepted;
  return { cached: res.status === 200, accepted };
}

export async function getRun(id: string): Promise<RunDetail> {
  const res = await apiFetch(`/runs/${id}`, { cache: 'no-store' });
  if (res.status === 404) throw new ApiError(404, 'Run not found');
  if (!res.ok) throw new ApiError(res.status, `Failed to fetch run ${id}`);
  return (await res.json()) as RunDetail;
}

/** Returns null on 404 — no analysis for that ticker/date/profile is a
 * normal state, not an error (DEV_HANDOFF.md: "POST /analyze to request
 * one"). */
export async function getRunByTicker(
  ticker: string,
  analysisDate: string,
  profile: AnalysisProfile = 'fast',
): Promise<RunDetail | null> {
  const url = `/runs/${encodeURIComponent(ticker)}/${analysisDate}?profile=${profile}`;
  const res = await apiFetch(url, { cache: 'no-store' });
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiError(res.status, `Failed to fetch ${ticker} ${analysisDate}`);
  return (await res.json()) as RunDetail;
}

export async function getRunHistory(
  ticker: string,
  analysisDate: string,
  profile: AnalysisProfile = 'fast',
): Promise<RunHistory | null> {
  const url = `/runs/${encodeURIComponent(ticker)}/${analysisDate}/history?profile=${profile}`;
  const res = await apiFetch(url, { cache: 'no-store' });
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiError(res.status, `Failed to fetch history for ${ticker} ${analysisDate}`);
  return (await res.json()) as RunHistory;
}

/** Cooperative, not instant for a running analysis -- see the endpoint's
 * own docstring. 404 covers both "no such run" and "already finished";
 * either way there is nothing left to stop. */
export async function stopRun(id: string): Promise<RunDetail> {
  const res = await apiFetch(`/runs/${id}/stop`, { method: 'POST' });
  if (res.status === 404) {
    throw new ApiError(404, 'Run not found, or it has already finished');
  }
  if (!res.ok) throw new ApiError(res.status, `Failed to stop run ${id}`);
  return (await res.json()) as RunDetail;
}

/** Continue a failed run instead of restarting from scratch -- queues a NEW
 * run (poll it the same way as one from analyzeRun) rather than mutating the
 * failed one in place. 404 covers both "no such run" and "that run didn't
 * fail"; either way there's nothing to resume. */
export async function resumeRun(id: string): Promise<RunAccepted> {
  const res = await apiFetch(`/runs/${id}/resume`, { method: 'POST' });
  if (res.status === 404) {
    throw new ApiError(404, 'Run not found, or it did not fail');
  }
  if (res.status === 429) {
    const body = await res.json().catch(() => ({ detail: 'Rate limited.' }));
    const retryAfterSeconds = Number(res.headers.get('Retry-After') ?? '3600');
    throw new RateLimitError(body.detail ?? 'Rate limited.', retryAfterSeconds);
  }
  if (!res.ok) throw new ApiError(res.status, `Failed to resume run ${id}`);
  return (await res.json()) as RunAccepted;
}

export async function getVapidPublicKey(): Promise<string> {
  const res = await apiFetch('/push/vapid-public-key');
  if (!res.ok) throw new ApiError(res.status, 'Failed to fetch the push public key');
  const body = (await res.json()) as VapidPublicKey;
  return body.key;
}

/** Registers a browser PushSubscription for one run's completion -- pass
 * `subscription.toJSON()` directly, its shape matches the endpoint body
 * exactly. 404 means the run doesn't exist or already finished. */
export async function subscribeRun(
  id: string,
  subscription: { endpoint: string; keys: { p256dh: string; auth: string } },
): Promise<void> {
  const res = await apiFetch(`/runs/${id}/subscribe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(subscription),
  });
  if (res.status === 404) {
    throw new ApiError(404, 'Run not found, or it has already finished');
  }
  if (!res.ok) throw new ApiError(res.status, `Failed to subscribe to run ${id}`);
}

/** Fetches an export (with the bearer token already attached via apiFetch)
 * and triggers a browser download -- replaces the old plain <a href> URLs
 * (exportPdfUrl/exportExcelUrl), which couldn't carry an Authorization
 * header and would 401 for every authenticated user against these now-
 * protected routes. The endpoint's own Content-Disposition header no longer
 * does the naming work since this is a blob download, not a navigation, so
 * `download` is set explicitly here instead. */
export async function downloadExport(id: string, format: 'pdf' | 'xlsx'): Promise<void> {
  const path = format === 'pdf' ? `/runs/${id}/export.pdf` : `/runs/${id}/export.xlsx`;
  const res = await apiFetch(path);
  if (!res.ok) throw new ApiError(res.status, `Failed to export run ${id} as ${format}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `run-${id}.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function listRuns(
  params: { ticker?: string; limit?: number; offset?: number } = {},
): Promise<RunSummary[]> {
  const search = new URLSearchParams();
  if (params.ticker) search.set('ticker', params.ticker);
  if (params.limit) search.set('limit', String(params.limit));
  if (params.offset) search.set('offset', String(params.offset));
  const qs = search.toString();

  const res = await apiFetch(`/runs${qs ? `?${qs}` : ''}`, { cache: 'no-store' });
  if (!res.ok) throw new ApiError(res.status, 'Failed to list runs');
  return (await res.json()) as RunSummary[];
}
