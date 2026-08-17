import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
// `VerdictSummary` is now a thin re-export of `TheCall` (see
// src/components/VerdictSummary.tsx) — exercised through that name here
// since RunView.tsx still imports it under this name until Task 11 switches
// the call site over to `TheCall` directly.
import { VerdictSummary } from '@/components/VerdictSummary';
import type { Verdict } from '@/lib/api-client/client';

describe('VerdictSummary (TheCall)', () => {
  it('renders null entry_price/stop_loss as "Not set", never ₹0', () => {
    const verdict: Verdict = {
      rating: 'Underweight',
      price_target: null,
      time_horizon: '3-6 months',
      levels: { action: 'Hold', entry_price: null, stop_loss: null, position_sizing: null },
    };

    render(<VerdictSummary verdict={verdict} />);

    // ENTRY and STOP are the two price fields this component renders (see
    // TheCall's stat grid) — both must read "Not set", never a fabricated ₹0.
    const notSetCells = screen.getAllByText('Not set');
    expect(notSetCells.length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('₹0')).not.toBeInTheDocument();
  });

  it('renders rating (ruler highlight) and action (stat grid) as separate signals, never collapsed into one', () => {
    const verdict: Verdict = {
      rating: 'Underweight',
      price_target: 500,
      time_horizon: '3-6 months',
      levels: { action: 'Hold', entry_price: 480, stop_loss: 440, position_sizing: '2% of portfolio' },
    };

    render(<VerdictSummary verdict={verdict} />);

    // Action renders as its own stat-grid value.
    expect(screen.getByText('Hold')).toBeInTheDocument();

    // Rating is a wholly separate signal carried by ruler position: the
    // UNDERWEIGHT stop must be the one highlighted...
    const underweightLabel = screen.getByText('UNDERWEIGHT');
    expect(underweightLabel.className).toContain('#00439D');

    // ...and critically, the HOLD stop on the ruler must stay unhighlighted
    // even though action is "Hold" — rating and action can legitimately
    // disagree and must never be collapsed into one badge.
    const holdLabel = screen.getByText('HOLD');
    expect(holdLabel.className).not.toContain('#00439D');
  });
});
