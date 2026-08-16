import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = 8010;
const PROGRESSIVE_ID = 'run-progressive';

const completedFixture = JSON.parse(
  readFileSync(path.join(__dirname, 'fixtures', 'completed.json'), 'utf-8'),
);
const contestedHistoryFixture = JSON.parse(
  readFileSync(path.join(__dirname, 'fixtures', 'contested-history.json'), 'utf-8'),
);

const runs = new Map<string, Record<string, unknown>>();
runs.set('run-completed', completedFixture);
runs.set('run-failed', {
  id: 'run-failed',
  ticker: 'FAILCO.NS',
  analysis_date: '2026-08-16',
  profile: 'fast',
  status: 'failed',
  created_at: new Date().toISOString(),
  completed_at: new Date().toISOString(),
  error: 'The market data provider timed out after 3 retries.',
  cached: false,
  verdict: null,
  reports: null,
  run_count: 1,
  verdict_is_contested: false,
});

// A run that answers queued -> running -> completed across successive polls,
// so the E2E test can assert the UI actually reflects live status changes.
let progressivePollCount = 0;
function progressiveRun() {
  progressivePollCount += 1;
  if (progressivePollCount === 1) {
    return { ...completedFixture, id: PROGRESSIVE_ID, status: 'queued', verdict: null, reports: null, completed_at: null };
  }
  if (progressivePollCount === 2) {
    return { ...completedFixture, id: PROGRESSIVE_ID, status: 'running', verdict: null, reports: null, completed_at: null };
  }
  return { ...completedFixture, id: PROGRESSIVE_ID };
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', `http://localhost:${PORT}`);
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  // Browsers preflight cross-origin POSTs with a JSON body (the Next.js
  // dev server on :3100 calling this mock on :8010 counts as cross-origin).
  // Without a 2xx response to OPTIONS here, the real POST never leaves the
  // browser and fetch() rejects before the app ever sees a status code.
  if (req.method === 'OPTIONS') {
    res.statusCode = 204;
    res.end();
    return;
  }

  if (req.method === 'POST' && url.pathname === '/analyze') {
    const chunks: Buffer[] = [];
    for await (const chunk of req) chunks.push(chunk as Buffer);
    const body = JSON.parse(Buffer.concat(chunks).toString('utf-8') || '{}');

    if (body.ticker === 'RATELIMIT') {
      res.statusCode = 429;
      res.setHeader('Retry-After', '3600');
      res.end(
        JSON.stringify({
          detail:
            'You have requested 10 analyses today, which is the limit of 10. Previously completed analyses are still available to read.',
        }),
      );
      return;
    }

    if (body.ticker === 'PROGRESS') {
      progressivePollCount = 0;
      res.statusCode = 202;
      res.end(
        JSON.stringify({ id: PROGRESSIVE_ID, status: 'queued', poll_url: `/runs/${PROGRESSIVE_ID}`, estimated_seconds: 8 }),
      );
      return;
    }

    res.statusCode = 202;
    res.end(JSON.stringify({ id: 'run-completed', status: 'queued', poll_url: '/runs/run-completed', estimated_seconds: 240 }));
    return;
  }

  const historyMatch = url.pathname.match(/^\/runs\/([^/]+)\/([^/]+)\/history$/);
  if (req.method === 'GET' && historyMatch) {
    res.end(JSON.stringify(contestedHistoryFixture));
    return;
  }

  const runIdMatch = url.pathname.match(/^\/runs\/([^/]+)$/);
  if (req.method === 'GET' && runIdMatch) {
    const id = runIdMatch[1];
    if (id === PROGRESSIVE_ID) {
      res.end(JSON.stringify(progressiveRun()));
      return;
    }
    // Fall back to matching a fixture's own internal `id` field: /runs
    // (below) echoes each stored fixture's internal `id`, not the Map key
    // it's filed under, so a link built from that listing (e.g.
    // RecentRuns) must still resolve here or it 404s as a dead link.
    const run = runs.get(id) ?? [...runs.values()].find((entry) => entry.id === id);
    if (!run) {
      res.statusCode = 404;
      res.end(JSON.stringify({ detail: 'Run not found' }));
      return;
    }
    res.end(JSON.stringify(run));
    return;
  }

  const byTickerMatch = url.pathname.match(/^\/runs\/([^/]+)\/([^/]+)$/);
  if (req.method === 'GET' && byTickerMatch) {
    const [, ticker] = byTickerMatch;
    const run = [...runs.values()].find((entry) => entry.ticker === ticker);
    if (!run) {
      res.statusCode = 404;
      res.end(JSON.stringify({ detail: 'No analysis for that ticker and date.' }));
      return;
    }
    res.end(JSON.stringify(run));
    return;
  }

  if (req.method === 'GET' && url.pathname === '/runs') {
    const summaries = [...runs.values()].map(
      ({ id, ticker, analysis_date, profile, status, created_at, completed_at, error, cached }) => ({
        id,
        ticker,
        analysis_date,
        profile,
        status,
        created_at,
        completed_at,
        error,
        cached,
      }),
    );
    res.end(JSON.stringify(summaries));
    return;
  }

  res.statusCode = 404;
  res.end(JSON.stringify({ detail: 'Not found' }));
});

server.listen(PORT, () => {
  console.log(`Mock API listening on http://127.0.0.1:${PORT}`);
});
