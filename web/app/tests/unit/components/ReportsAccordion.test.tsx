import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ReportsAccordion } from '@/components/ReportsAccordion';
import type { Reports } from '@/lib/api-client/client';

describe('ReportsAccordion', () => {
  it('renders only the sections that actually have prose, not all ten', () => {
    const reports: Reports = {
      final_decision: 'The final call.',
      bull_case: 'The bull case.',
      market: 'The market read.',
      sentiment: null,
      news: '',
    };

    const { container } = render(<ReportsAccordion reports={reports} />);

    expect(container.querySelectorAll('details')).toHaveLength(3);
    expect(screen.getByText('Final Decision')).toBeInTheDocument();
    expect(screen.getByText('Bull Case')).toBeInTheDocument();
    expect(screen.getByText('Market Analysis')).toBeInTheDocument();
    expect(screen.queryByText('Sentiment Analysis')).not.toBeInTheDocument();
    expect(screen.queryByText('News Analysis')).not.toBeInTheDocument();
  });

  it('opens only the first section in REPORT_ORDER so ~11,000 words never dump at once', () => {
    const reports: Reports = {
      final_decision: 'The final call.',
      bull_case: 'The bull case.',
      market: 'The market read.',
    };

    const { container } = render(<ReportsAccordion reports={reports} />);
    const sections = Array.from(container.querySelectorAll('details'));

    // REPORT_ORDER puts final_decision first, ahead of bull_case and market.
    expect(sections[0]).toHaveTextContent('Final Decision');
    expect(sections[0]).toHaveAttribute('open');
    expect(sections.slice(1).map((section) => section.hasAttribute('open'))).toEqual([false, false]);
  });

  it('falls back to the first available section when final_decision is missing', () => {
    const reports: Reports = { market: 'The market read.', bull_case: 'The bull case.' };

    const { container } = render(<ReportsAccordion reports={reports} />);
    const sections = Array.from(container.querySelectorAll('details'));

    expect(sections).toHaveLength(2);
    expect(sections[0]).toHaveTextContent('Bull Case');
    expect(sections[0]).toHaveAttribute('open');
    expect(sections[1]).not.toHaveAttribute('open');
  });

  it('renders nothing when there are no reports at all', () => {
    const { container } = render(<ReportsAccordion reports={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
