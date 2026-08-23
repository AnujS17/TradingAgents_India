import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SearchForm } from '@/components/SearchForm';
import { RateLimitError } from '@/lib/api-client/client';

const pushMock = vi.fn();
let currentSearchParams = new URLSearchParams();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => currentSearchParams,
}));

vi.mock('@/lib/api-client/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client/client')>();
  return { ...actual, analyzeRun: vi.fn() };
});

import { analyzeRun } from '@/lib/api-client/client';

describe('SearchForm', () => {
  afterEach(() => {
    vi.clearAllMocks();
    currentSearchParams = new URLSearchParams();
  });

  it('navigates to the run with cached=1 on a 200 (existing) response', async () => {
    vi.mocked(analyzeRun).mockResolvedValue({
      cached: true,
      accepted: { id: 'r1', status: 'completed', poll_url: '/runs/r1', estimated_seconds: 0 },
    });

    render(<SearchForm />);
    await userEvent.type(screen.getByLabelText(/Ticker/), 'SIEMENS.NS');
    await userEvent.click(screen.getByRole('button', { name: /Start researching/ }));

    expect(pushMock).toHaveBeenCalledWith('/runs/r1?cached=1');
  });

  it('navigates to the run with cached=0 on a 202 (new) response', async () => {
    vi.mocked(analyzeRun).mockResolvedValue({
      cached: false,
      accepted: { id: 'r2', status: 'queued', poll_url: '/runs/r2', estimated_seconds: 240 },
    });

    render(<SearchForm />);
    await userEvent.type(screen.getByLabelText(/Ticker/), 'RELIANCE');
    await userEvent.click(screen.getByRole('button', { name: /Start researching/ }));

    // est= carries the 202's estimated_seconds through the navigation — the
    // run detail endpoint never returns it, so this is its only route to the
    // waiting screen.
    expect(pushMock).toHaveBeenCalledWith('/runs/r2?cached=0&est=240');
  });

  it('seeds the ticker and date from a /?ticker=…&date=… deep link', async () => {
    currentSearchParams = new URLSearchParams({ ticker: 'SIEMENS.NS', date: '2026-08-12' });
    vi.mocked(analyzeRun).mockResolvedValue({
      cached: true,
      accepted: { id: 'r3', status: 'completed', poll_url: '/runs/r3', estimated_seconds: 0 },
    });

    render(<SearchForm />);

    expect(screen.getByLabelText(/Ticker/)).toHaveValue('SIEMENS.NS');
    expect(screen.getByLabelText(/Analysis date/)).toHaveValue('2026-08-12');

    await userEvent.click(screen.getByRole('button', { name: /Start researching/ }));

    expect(analyzeRun).toHaveBeenCalledWith({
      ticker: 'SIEMENS.NS',
      profile: 'fast',
      analysis_date: '2026-08-12',
    });
  });

  it('omits analysis_date entirely when the date field is left blank', async () => {
    vi.mocked(analyzeRun).mockResolvedValue({
      cached: true,
      accepted: { id: 'r4', status: 'completed', poll_url: '/runs/r4', estimated_seconds: 0 },
    });

    render(<SearchForm />);
    await userEvent.type(screen.getByLabelText(/Ticker/), 'RELIANCE');
    await userEvent.click(screen.getByRole('button', { name: /Start researching/ }));

    expect(analyzeRun).toHaveBeenCalledWith({ ticker: 'RELIANCE', profile: 'fast' });
  });

  it('sends time_horizon, trimmed, when the field is filled in', async () => {
    vi.mocked(analyzeRun).mockResolvedValue({
      cached: true,
      accepted: { id: 'r6', status: 'completed', poll_url: '/runs/r6', estimated_seconds: 0 },
    });

    render(<SearchForm />);
    await userEvent.type(screen.getByLabelText(/Ticker/), 'RELIANCE');
    await userEvent.type(screen.getByLabelText(/Time horizon/), '  3-6 months  ');
    await userEvent.click(screen.getByRole('button', { name: /Start researching/ }));

    expect(analyzeRun).toHaveBeenCalledWith({
      ticker: 'RELIANCE',
      profile: 'fast',
      time_horizon: '3-6 months',
    });
  });

  it('omits time_horizon entirely when the field is left blank', async () => {
    vi.mocked(analyzeRun).mockResolvedValue({
      cached: true,
      accepted: { id: 'r7', status: 'completed', poll_url: '/runs/r7', estimated_seconds: 0 },
    });

    render(<SearchForm />);
    await userEvent.type(screen.getByLabelText(/Ticker/), 'RELIANCE');
    await userEvent.click(screen.getByRole('button', { name: /Start researching/ }));

    expect(analyzeRun).toHaveBeenCalledWith({ ticker: 'RELIANCE', profile: 'fast' });
  });

  it('shows the server rate-limit message and does not navigate on 429', async () => {
    vi.mocked(analyzeRun).mockRejectedValue(new RateLimitError('Daily limit reached.', 3600));

    render(<SearchForm />);
    await userEvent.type(screen.getByLabelText(/Ticker/), 'SIEMENS.NS');
    await userEvent.click(screen.getByRole('button', { name: /Start researching/ }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Daily limit reached.');
    expect(screen.getByRole('alert')).toHaveTextContent('Existing analyses are still available');
    expect(pushMock).not.toHaveBeenCalled();
  });

  it('renders the nav variant with a single ticker input', () => {
    render(<SearchForm variant="nav" />);
    expect(screen.getByLabelText('Research another stock')).toBeInTheDocument();
  });

  it('renders the cta variant with a single ticker input', () => {
    render(<SearchForm variant="cta" />);
    expect(screen.getByPlaceholderText('Enter a ticker, e.g. TCS')).toBeInTheDocument();
  });

  // The cta variant (Task 7's CtaSection) is a second real, money-spending
  // submit path — the test above only proves it renders, not that its form
  // actually wires to analyzeRun. The 200/202/429 branching itself is shared
  // code already covered by the hero-variant tests above, so this just
  // proves the cta variant's own button/form triggers it, mirroring the
  // first test's shape with variant="cta".
  it('submits through analyzeRun on the cta variant', async () => {
    vi.mocked(analyzeRun).mockResolvedValue({
      cached: true,
      accepted: { id: 'r5', status: 'completed', poll_url: '/runs/r5', estimated_seconds: 0 },
    });

    render(<SearchForm variant="cta" />);
    await userEvent.type(screen.getByPlaceholderText('Enter a ticker, e.g. TCS'), 'TCS');
    await userEvent.click(screen.getByRole('button', { name: /Start researching/ }));

    expect(analyzeRun).toHaveBeenCalledWith({ ticker: 'TCS', profile: 'fast' });
    expect(pushMock).toHaveBeenCalledWith('/runs/r5?cached=1');
  });
});
