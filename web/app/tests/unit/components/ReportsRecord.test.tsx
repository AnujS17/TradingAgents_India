import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ReportsRecord } from '@/components/research/ReportsRecord';
import type { Reports } from '@/lib/api-client/client';

describe('ReportsRecord', () => {
  it('renders only the sections that actually have prose, not all ten', () => {
    const reports: Reports = {
      final_decision: 'The final call.',
      bull_case: 'The bull case.',
      market: 'The market read.',
      sentiment: null,
      news: '',
    };

    const { container } = render(<ReportsRecord reports={reports} />);

    expect(container.querySelectorAll('.rep')).toHaveLength(3);
    expect(screen.getByText('Final decision')).toBeInTheDocument();
    expect(screen.getByText('Bull case')).toBeInTheDocument();
    expect(screen.getByText('Market')).toBeInTheDocument();
    expect(screen.queryByText('Sentiment')).not.toBeInTheDocument();
    expect(screen.queryByText('News')).not.toBeInTheDocument();
  });

  it('opens only the first row in REPORT_ORDER so ~11,000 words never dump at once', () => {
    const reports: Reports = {
      final_decision: 'The final call.',
      bull_case: 'The bull case.',
      market: 'The market read.',
    };

    const { container } = render(<ReportsRecord reports={reports} />);
    const rows = Array.from(container.querySelectorAll('.rep'));

    // REPORT_ORDER puts final_decision first, ahead of bull_case and market.
    expect(rows[0]).toHaveTextContent('Final decision');
    expect(rows[0]).toHaveAttribute('aria-expanded', 'true');
    expect(rows.slice(1).map((row) => row.getAttribute('aria-expanded'))).toEqual(['false', 'false']);
  });

  it('falls back to nothing open when final_decision is missing', () => {
    const reports: Reports = { market: 'The market read.', bull_case: 'The bull case.' };

    const { container } = render(<ReportsRecord reports={reports} />);
    const rows = Array.from(container.querySelectorAll('.rep'));

    expect(rows).toHaveLength(2);
    // Only final_decision opens by default; when it's absent, nothing does.
    expect(rows.every((row) => row.getAttribute('aria-expanded') === 'false')).toBe(true);
  });

  it('renders nothing when there are no reports at all', () => {
    const { container } = render(<ReportsRecord reports={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('computes bar length as a fraction of the longest present report, never NaN', () => {
    // Two reports of different lengths: the longer one should reach --len:1,
    // the shorter one a fraction of that, and neither should be NaN/undefined.
    const reports: Reports = {
      final_decision: 'one two three four five six seven eight',
      market: 'one two three four',
    };

    const { container } = render(<ReportsRecord reports={reports} />);
    const bars = Array.from(container.querySelectorAll<HTMLElement>('.rep__bar i'));

    expect(bars).toHaveLength(2);
    const lens = bars.map((bar) => bar.style.getPropertyValue('--len'));
    expect(lens).toContain('1');
    expect(lens.every((len) => len !== '' && !Number.isNaN(Number(len)))).toBe(true);
  });

  it('resolves bar length to a full-width bar, not NaN, when only one report is present', () => {
    const reports: Reports = { final_decision: 'one two three' };

    const { container } = render(<ReportsRecord reports={reports} />);
    const bar = container.querySelector<HTMLElement>('.rep__bar i');

    expect(bar).not.toBeNull();
    expect(bar!.style.getPropertyValue('--len')).toBe('1');
  });
});
