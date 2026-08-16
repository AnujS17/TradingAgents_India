import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RunHistoryPanel } from '@/components/RunHistoryPanel';
import type { RunHistory } from '@/lib/api-client/client';

const contestedHistory: RunHistory = {
  ticker: 'SIEMENS.NS',
  analysis_date: '2026-08-12',
  profile: 'fast',
  run_count: 3,
  ratings: ['Hold', 'Underweight', 'Underweight'],
  verdict_is_contested: true,
  runs: [
    {
      id: 'run-3',
      ticker: 'SIEMENS.NS',
      analysis_date: '2026-08-12',
      profile: 'fast',
      status: 'completed',
      created_at: '2026-08-14 10:00:00.000000',
      completed_at: '2026-08-14 10:05:00.000000',
      error: null,
      cached: false,
    },
    {
      id: 'run-2',
      ticker: 'SIEMENS.NS',
      analysis_date: '2026-08-12',
      profile: 'fast',
      status: 'completed',
      created_at: '2026-08-13 10:00:00.000000',
      completed_at: '2026-08-13 10:05:00.000000',
      error: null,
      cached: false,
    },
    {
      id: 'run-1',
      ticker: 'SIEMENS.NS',
      analysis_date: '2026-08-12',
      profile: 'fast',
      status: 'completed',
      created_at: '2026-08-12 14:26:16.574344',
      completed_at: '2026-08-12 14:30:58.027178',
      error: null,
      cached: false,
    },
  ],
};

describe('RunHistoryPanel', () => {
  it('renders nothing for a single, uncontested run', () => {
    const { container } = render(
      <RunHistoryPanel
        runCount={1}
        isContested={false}
        history={{ ...contestedHistory, run_count: 1, ratings: ['Underweight'], verdict_is_contested: false, runs: [] }}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('surfaces a contested split instead of hiding it behind the latest run', () => {
    render(<RunHistoryPanel runCount={3} isContested history={contestedHistory} />);

    expect(screen.getByText(/Analysed 3 times/)).toBeInTheDocument();
    expect(screen.getByText(/2 said Underweight/)).toBeInTheDocument();
    expect(screen.getByText(/1 said Hold/)).toBeInTheDocument();
    expect(screen.getByText(/disagreed/)).toBeInTheDocument();
  });

  it('links each run in the history so the dissenting ones can be opened', () => {
    render(<RunHistoryPanel runCount={3} isContested history={contestedHistory} />);

    const dissenter = screen.getByRole('link', { name: /Hold/ });
    expect(dissenter).toHaveAttribute('href', '/runs/run-3');
    expect(dissenter).toHaveTextContent('2026-08-14');
    expect(screen.getByRole('link', { name: /Underweight — 2026-08-13/ })).toHaveAttribute(
      'href',
      '/runs/run-2',
    );
    expect(screen.getAllByRole('link')).toHaveLength(3);
  });

  it('pairs ratings with the completed runs only, not by list position', () => {
    // `ratings` covers completed siblings only (api/store.py `_ratings`) while
    // `runs` covers all of them, so a failed run in the middle would shift a
    // naive same-index pairing and mislabel every later run.
    const history: RunHistory = {
      ...contestedHistory,
      run_count: 3,
      ratings: ['Hold', 'Underweight'],
      runs: [
        contestedHistory.runs[0],
        { ...contestedHistory.runs[1], status: 'failed', error: 'timed out' },
        contestedHistory.runs[2],
      ],
    };

    render(<RunHistoryPanel runCount={3} isContested history={history} />);

    expect(screen.getByRole('link', { name: /Hold — 2026-08-14/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Not completed \(failed\)/ })).toHaveAttribute(
      'href',
      '/runs/run-2',
    );
    expect(screen.getByRole('link', { name: /Underweight — 2026-08-12/ })).toHaveAttribute(
      'href',
      '/runs/run-1',
    );
  });

  it('states the contested verdict from the run itself when the history request has not landed', () => {
    render(<RunHistoryPanel runCount={3} isContested />);

    expect(screen.getByText(/Analysed 3 times/)).toBeInTheDocument();
    expect(screen.getByText(/disagreed/)).toBeInTheDocument();
    expect(screen.queryAllByRole('link')).toHaveLength(0);
  });

  it('says the history could not be loaded rather than falling silent', () => {
    render(<RunHistoryPanel runCount={3} isContested isError />);

    expect(screen.getByText(/Analysed 3 times/)).toBeInTheDocument();
    expect(screen.getByText(/disagreed/)).toBeInTheDocument();
    expect(screen.getByText(/Couldn’t load run history|Couldn't load run history/)).toBeInTheDocument();
  });
});
