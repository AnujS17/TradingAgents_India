import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { VerdictSummary } from '@/components/VerdictSummary';
import type { Verdict } from '@/lib/api-client/client';

describe('VerdictSummary', () => {
  it('renders null price_target/entry_price/stop_loss as "Not set", not 0', () => {
    const verdict: Verdict = {
      rating: 'Underweight',
      price_target: null,
      time_horizon: '3-6 months',
      levels: { action: 'Hold', entry_price: null, stop_loss: null, position_sizing: null },
    };

    render(<VerdictSummary verdict={verdict} />);

    const notSetCells = screen.getAllByText('Not set');
    expect(notSetCells.length).toBeGreaterThanOrEqual(3);
    expect(screen.queryByText('₹0')).not.toBeInTheDocument();
  });

  it('renders rating and action as separate values, never collapsed into one', () => {
    const verdict: Verdict = {
      rating: 'Underweight',
      price_target: 500,
      time_horizon: '3-6 months',
      levels: { action: 'Hold', entry_price: 480, stop_loss: 440, position_sizing: '2% of portfolio' },
    };

    render(<VerdictSummary verdict={verdict} />);

    expect(screen.getByText('Underweight')).toBeInTheDocument();
    expect(screen.getByText('Hold')).toBeInTheDocument();
  });
});
