import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RunHistoryPanel } from '@/components/RunHistoryPanel';
import type { RunHistory } from '@/lib/api-client/client';

describe('RunHistoryPanel', () => {
  it('renders nothing for a single, uncontested run', () => {
    const history: RunHistory = {
      ticker: 'SIEMENS.NS',
      analysis_date: '2026-08-12',
      profile: 'fast',
      run_count: 1,
      ratings: ['Underweight'],
      verdict_is_contested: false,
      runs: [],
    };

    const { container } = render(<RunHistoryPanel history={history} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('surfaces a contested split instead of hiding it behind the latest run', () => {
    const history: RunHistory = {
      ticker: 'SIEMENS.NS',
      analysis_date: '2026-08-12',
      profile: 'fast',
      run_count: 3,
      ratings: ['Hold', 'Underweight', 'Underweight'],
      verdict_is_contested: true,
      runs: [],
    };

    render(<RunHistoryPanel history={history} />);

    expect(screen.getByText(/Analysed 3 times/)).toBeInTheDocument();
    expect(screen.getByText(/2 said Underweight/)).toBeInTheDocument();
    expect(screen.getByText(/1 said Hold/)).toBeInTheDocument();
    expect(screen.getByText(/disagreed/)).toBeInTheDocument();
  });
});
