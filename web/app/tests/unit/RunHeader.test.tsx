import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { RunHeader } from '@/components/research/RunHeader';
import type { RunDetail } from '@/lib/api-client/client';

// A non-completed run renders RunStatusBanner, which calls useRouter() for
// the Resume button -- needs the App Router context mocked the same way
// RunStatusBanner.test.tsx does, or render() throws "expected app router to
// be mounted" before this file's own assertions ever run.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

function completedRun(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: 'run-1',
    ticker: 'SIEMENS.NS',
    analysis_date: '2026-08-12',
    profile: 'fast',
    status: 'completed',
    created_at: '2026-08-12T14:26:16.574344',
    completed_at: '2026-08-12T14:30:58.027178',
    error: null,
    cached: false,
    run_count: 1,
    verdict_is_contested: false,
    news_sources: [],
    reports: { final_decision: '**Rating**: Buy' },
    ...overrides,
  } as RunDetail;
}

// PDF/Excel export now lives in TheCall.tsx, next to the Complete badge --
// see TheCall.test.tsx. RunHeader itself no longer knows about exports.
describe('RunHeader', () => {
  it('shows the ticker, analysis date, and the completion stats', () => {
    render(<RunHeader run={completedRun()} />);

    expect(screen.getByRole('heading', { name: 'SIEMENS.NS' })).toBeInTheDocument();
    expect(screen.getByText(/12 August 2026/)).toBeInTheDocument();
    expect(screen.getByText('Run time')).toBeInTheDocument();
    expect(screen.getByText('Written')).toBeInTheDocument();
    expect(screen.getByText('Reports')).toBeInTheDocument();
  });

  it('renders the status banner instead of completion stats for a run still in progress', () => {
    render(<RunHeader run={completedRun({ status: 'running', reports: null })} />);

    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.queryByText('Analysis complete')).not.toBeInTheDocument();
  });
});
