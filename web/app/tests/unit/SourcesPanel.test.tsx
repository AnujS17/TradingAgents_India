import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SourcesPanel } from '@/components/research/SourcesPanel';
import type { NewsSource } from '@/lib/api-client/client';

const source: NewsSource = {
  title: 'Example Corp posts results',
  source: 'Reuters',
  published_date: '2026-08-01',
  url: 'https://example.com/a',
  snippet: 'Results were in line with estimates.',
};

describe('SourcesPanel', () => {
  it('renders nothing when sources is empty', () => {
    const { container } = render(<SourcesPanel sources={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders a card per source with title linked to its url', () => {
    render(<SourcesPanel sources={[source]} />);

    expect(screen.getByText('Example Corp posts results')).toBeInTheDocument();
    expect(screen.getByText('Reuters')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Example Corp posts results' });
    expect(link).toHaveAttribute('href', 'https://example.com/a');
  });

  it('renders the title as plain text (no link) when url is absent', () => {
    render(<SourcesPanel sources={[{ ...source, url: null }]} />);

    expect(screen.getByText('Example Corp posts results')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
});
