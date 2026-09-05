import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { TheCall } from '@/components/research/TheCall';
import { ratingColor } from '@/lib/rating-color';
import type { Verdict } from '@/lib/api-client/client';

vi.mock('@/lib/api-client/client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api-client/client')>('@/lib/api-client/client');
  return { ...actual, downloadExport: vi.fn() };
});
import { downloadExport } from '@/lib/api-client/client';

// jsdom normalizes an inline hex color (e.g. "#C2410C") to rgb(r, g, b) when
// read back via element.style.color -- comparing the raw hex string against
// that readback always fails regardless of whether the right color is
// actually applied, so every color assertion below goes through this.
function hexToRgb(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgb(${r}, ${g}, ${b})`;
}

describe('TheCall', () => {
  it('renders null entry_price/stop_loss as "Not set", never ₹0', () => {
    const verdict: Verdict = {
      rating: 'Underweight',
      price_target: null,
      time_horizon: '3-6 months',
      levels: { action: 'Hold', entry_price: null, stop_loss: null, position_sizing: null },
    };

    render(<TheCall verdict={verdict} runId="run-1" />);

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

    render(<TheCall verdict={verdict} runId="run-1" />);

    // Action renders as its own stat-grid value.
    expect(screen.getByText('Hold')).toBeInTheDocument();

    // Rating is a wholly separate signal carried by ruler position: the
    // UNDERWEIGHT stop must be the one highlighted -- color is set via
    // inline style (ratingColor's hex values), not a Tailwind class, so
    // this checks style.color, not className (the original assertion here
    // checked className for a hex string that was neither how the color is
    // applied nor even underweight's actual color -- it could never have
    // passed).
    const underweightLabel = screen.getByText('UNDERWEIGHT');
    expect(underweightLabel.style.color).toBe(hexToRgb(ratingColor('Underweight').text));

    // ...and critically, the HOLD stop on the ruler must stay unhighlighted
    // even though action is "Hold" — rating and action can legitimately
    // disagree and must never be collapsed into one badge.
    const holdLabel = screen.getByText('HOLD');
    expect(holdLabel.style.color).not.toBe(hexToRgb(ratingColor('Underweight').text));
  });

  it('offers a single export trigger next to the Complete badge, revealing PDF/Excel actions that download this run', async () => {
    const user = userEvent.setup();
    const verdict: Verdict = {
      rating: 'Buy',
      price_target: 500,
      time_horizon: '3-6 months',
      levels: { action: 'Buy', entry_price: 480, stop_loss: 440, position_sizing: null },
    };

    render(<TheCall verdict={verdict} runId="run-42" />);

    // One icon-only trigger (button, not a link -- it navigates nowhere
    // itself, it just reveals the menu on hover/focus), distinguished by
    // aria-label since its visible content is the svg glyph, not text.
    const trigger = screen.getByRole('button', { name: 'Export' });
    expect(trigger.textContent).toBe('');

    // The two format actions live in the menu underneath it at all times (a
    // CSS-only hover/focus reveal, not a mount/unmount toggle) -- so they're
    // queryable regardless of hover state. Both export routes require a
    // bearer token now, which a plain <a href> navigation can't carry, so
    // these are buttons that call downloadExport (apiFetch under the hood),
    // not links -- asserting an href here would be testing the very
    // approach that 401s for every authenticated user.
    const pdfButton = screen.getByRole('menuitem', { name: 'Export as PDF' });
    const excelButton = screen.getByRole('menuitem', { name: 'Export as Excel' });
    expect(pdfButton.tagName).toBe('BUTTON');
    expect(excelButton.tagName).toBe('BUTTON');

    await user.click(pdfButton);
    expect(downloadExport).toHaveBeenCalledWith('run-42', 'pdf');

    await user.click(excelButton);
    expect(downloadExport).toHaveBeenCalledWith('run-42', 'xlsx');
  });

  it('offers a compare button next to the export trigger when another completed run exists', () => {
    const verdict: Verdict = {
      rating: 'Buy',
      price_target: 500,
      time_horizon: '3-6 months',
      levels: { action: 'Buy', entry_price: 480, stop_loss: 440, position_sizing: null },
    };

    render(<TheCall verdict={verdict} runId="run-42" compareHref="/runs/compare?a=run-42&b=run-7" />);

    expect(screen.getByRole('link', { name: 'Compare with previous run' })).toHaveAttribute(
      'href',
      '/runs/compare?a=run-42&b=run-7',
    );
  });

  it('hides the compare button when there is no other completed run to compare against', () => {
    const verdict: Verdict = {
      rating: 'Buy',
      price_target: 500,
      time_horizon: '3-6 months',
      levels: { action: 'Buy', entry_price: 480, stop_loss: 440, position_sizing: null },
    };

    // compareHref defaults to null when the caller doesn't pass it -- the
    // same "nothing to compare against yet" case RunView hits before its
    // history query has landed.
    render(<TheCall verdict={verdict} runId="run-42" />);

    expect(screen.queryByRole('link', { name: 'Compare with previous run' })).not.toBeInTheDocument();
  });

  it('spans the ruler edge to edge: the last dot reaches the row\'s full width, not 4/5 of it', () => {
    const verdict: Verdict = {
      rating: 'Buy',
      price_target: null,
      time_horizon: null,
      levels: {},
    };

    render(<TheCall verdict={verdict} runId="run-1" />);

    // Locate the dot row via the label row's text (unambiguous -- "BUY"
    // only appears in the ruler), then its previous sibling is the dot row.
    // Structural check, since jsdom doesn't run real layout: the dot row
    // must be a flat flex sequence of 5 dots + 4 connecting lines (9 direct
    // children). The previous grid-cols-5 shape nested each dot inside its
    // own column wrapper instead, which is exactly what confined the last
    // line (and therefore the last dot's reach) to 4/5 of the row -- that
    // shape would show only 5 children here (one wrapper per stop), not 9.
    const buyLabel = screen.getByText('BUY');
    const labelRow = buyLabel.parentElement as HTMLElement;
    const dotRow = labelRow.previousElementSibling as HTMLElement;
    expect(dotRow.children).toHaveLength(9);
    // And specifically: 5 of those 9 are the dots themselves.
    expect(dotRow.querySelectorAll(':scope > span.rounded-full')).toHaveLength(5);
  });

  // Which of entry/stop/exit are blank, and why, is now a function of the
  // RATING (api.service._extract_verdict enforces this backend-side):
  // Overweight (a tactical add) only keeps entry; Underweight (a trim)
  // only keeps exit. A single Hold-only sentence used to caption every
  // blank-field case -- these pin that the copy now matches the rating
  // that actually produced the blank fields, not just Hold.
  it('explains Overweight\'s blank stop/exit as a tactical add, not a Hold', () => {
    const verdict: Verdict = {
      rating: 'Overweight',
      price_target: null,
      time_horizon: '6 months',
      levels: { action: 'Buy', entry_price: 777, stop_loss: null, position_sizing: null },
    };

    render(<TheCall verdict={verdict} runId="run-1" />);

    expect(screen.getByText(/tactical add to an existing position/)).toBeInTheDocument();
    expect(screen.queryByText(/blank for a Hold/)).not.toBeInTheDocument();
  });

  it('labels the Underweight execution level as a trim, and keeps the target separate', () => {
    // The two numbers answer different questions: 266.67 is where you
    // SELL, 240 is where the thesis says price GOES. They previously
    // collapsed into one another, rendering EXIT = 266.67 against a
    // 263.00 close -- a 1% "target" over a multi-month horizon.
    const verdict: Verdict = {
      rating: 'Underweight',
      price_target: 240,
      time_horizon: '4 months',
      levels: { action: 'Sell', entry_price: 266.67, stop_loss: null, position_sizing: null },
    };

    render(<TheCall verdict={verdict} runId="run-1" />);

    // "Entry" reads backwards for a sell.
    expect(screen.getByText('TRIM AT')).toBeInTheDocument();
    expect(screen.queryByText('ENTRY')).not.toBeInTheDocument();
    expect(screen.getByText(/level to trim into/)).toBeInTheDocument();
    expect(screen.queryByText(/blank for a Hold/)).not.toBeInTheDocument();
  });

  it('still uses the Hold-specific explanation for an actual Hold', () => {
    const verdict: Verdict = {
      rating: 'Hold',
      price_target: null,
      time_horizon: '3-6 months',
      levels: { action: 'Hold', entry_price: null, stop_loss: null, position_sizing: null },
    };

    render(<TheCall verdict={verdict} runId="run-1" />);

    expect(screen.getByText(/blank for a Hold/)).toBeInTheDocument();
  });

  it('shows no levels explanation at all when Buy/Sell fields are fully populated', () => {
    const verdict: Verdict = {
      rating: 'Buy',
      price_target: 500,
      time_horizon: '6 months',
      levels: { action: 'Buy', entry_price: 480, stop_loss: 440, position_sizing: '2%' },
    };

    render(<TheCall verdict={verdict} runId="run-1" />);

    expect(screen.queryByText(/A blank field is a decision/)).not.toBeInTheDocument();
  });
});
