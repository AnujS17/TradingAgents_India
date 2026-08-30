import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { CompareCard } from '@/components/CompareCard';
import type { RunDetail } from '@/lib/api-client/client';

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
    verdict: {
      rating: 'Overweight',
      price_target: 4200,
      time_horizon: '3-6 months',
      current_price: 4047,
      levels: { action: 'Buy', entry_price: 4047, stop_loss: 3970, position_sizing: null },
    },
    reports: {
      final_decision:
        '**Rating**: Overweight\n\n**Executive Summary**: Trim MCX.NS exposure by roughly one-third into strength.\n\n**Investment Thesis**: Long thesis text here.',
    },
    ...overrides,
  } as RunDetail;
}

describe('CompareCard', () => {
  it('renders the rating, action, entry/stop/exit/current price, and horizon', () => {
    render(<CompareCard run={completedRun()} />);

    expect(screen.getByText('SIEMENS.NS')).toBeInTheDocument();
    expect(screen.getByText('Overweight')).toBeInTheDocument();
    expect(screen.getByText('Buy')).toBeInTheDocument();
    // Entry (4047) and current price (4047) share a value, so this asserts
    // the pair rather than either alone via getByText.
    expect(screen.getAllByText('₹4,047')).toHaveLength(2);
    expect(screen.getByText('₹3,970')).toBeInTheDocument(); // stop
    expect(screen.getByText('₹4,200')).toBeInTheDocument(); // exit
    expect(screen.getByText('3-6 months')).toBeInTheDocument();
  });

  it('shows Not set rather than a fabricated value for missing levels', () => {
    const run = completedRun({
      verdict: { rating: 'Hold', price_target: null, time_horizon: null, current_price: null, levels: {} },
    });

    render(<CompareCard run={run} />);

    // ACTION, ENTRY, STOP, EXIT, CURRENT PRICE, HORIZON are all unset.
    expect(screen.getAllByText('Not set').length).toBeGreaterThanOrEqual(5);
  });

  it('links the ticker heading to the full run report', () => {
    render(<CompareCard run={completedRun()} />);

    expect(screen.getByRole('link', { name: 'SIEMENS.NS' })).toHaveAttribute('href', '/runs/run-1');
  });

  it('surfaces the executive summary excerpt, not the raw markdown', () => {
    render(<CompareCard run={completedRun()} />);

    expect(screen.getByText(/Trim MCX\.NS exposure/)).toBeInTheDocument();
    expect(screen.queryByText(/\*\*Executive Summary\*\*/)).not.toBeInTheDocument();
  });

  it('expands the full report in place on click, instead of navigating away', async () => {
    const run = completedRun({
      reports: {
        final_decision: '**Rating**: Overweight\n\n**Executive Summary**: Short summary.',
        market: 'A distinctive market report paragraph that only appears once expanded.',
      },
    });

    render(<CompareCard run={run} />);

    // "View full report" is a button, not a Link -- the whole point is that
    // clicking it must never navigate away from the comparison.
    const toggle = screen.getByRole('button', { name: /view full report/i });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Final decision')).not.toBeInTheDocument();

    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Final decision')).toBeInTheDocument();
    expect(screen.getByText('Market')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /hide full report/i })).toBeInTheDocument();
  });

  it('collapses the full report again on a second click', async () => {
    render(<CompareCard run={completedRun()} />);

    const openButton = screen.getByRole('button', { name: /view full report/i });
    await userEvent.click(openButton);
    expect(screen.getByText('Final decision')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /hide full report/i }));

    expect(screen.queryByText('Final decision')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /view full report/i })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
  });

  it('gives each card its own unique report-panel ids, for when two are on screen at once', async () => {
    const runA = completedRun({ id: 'run-a' });
    const runB = completedRun({ id: 'run-b' });

    const { container } = render(
      <>
        <CompareCard run={runA} />
        <CompareCard run={runB} />
      </>,
    );

    const buttons = screen.getAllByRole('button', { name: /view full report/i });
    await userEvent.click(buttons[0]);
    await userEvent.click(buttons[1]);

    // Both cards open "Final decision" simultaneously -- if the panel ids
    // collided (e.g. both "doc-final_decision"), this query would find one
    // element reused for both instead of two distinct regions.
    const panels = container.querySelectorAll('[role="region"][aria-label="Final decision"]');
    expect(panels).toHaveLength(2);
    expect(panels[0].id).not.toBe(panels[1].id);
  });
});
