'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useState } from 'react';
import { analyzeRun, RateLimitError } from '@/lib/api-client/client';

export function SearchForm() {
  const router = useRouter();
  // The "no analysis yet" branch of /stock/[ticker]/[date] deep-links here as
  // /?ticker=…&date=…, so seed the form from the URL rather than dropping the
  // user onto an empty box they have to retype.
  const searchParams = useSearchParams();
  const [ticker, setTicker] = useState(() => searchParams.get('ticker') ?? '');
  const [analysisDate, setAnalysisDate] = useState(() => searchParams.get('date') ?? '');
  const [profile, setProfile] = useState<'fast' | 'detailed'>('fast');
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!ticker.trim()) return;

    setSubmitting(true);
    setErrorMessage(null);

    try {
      // Omit analysis_date entirely when blank so the backend applies its own
      // "defaults to today" behaviour instead of receiving an empty string.
      const { accepted, cached } = await analyzeRun({
        ticker,
        profile,
        ...(analysisDate ? { analysis_date: analysisDate } : {}),
      });
      const query = new URLSearchParams({ cached: cached ? '1' : '0' });
      // Carry the server's own estimate through the navigation — it only
      // exists on the 202 response body, which this page is the last place
      // to see it.
      if (!cached && accepted.estimated_seconds > 0) {
        query.set('est', String(accepted.estimated_seconds));
      }
      router.push(`/runs/${accepted.id}?${query.toString()}`);
    } catch (error) {
      if (error instanceof RateLimitError) {
        setErrorMessage(`${error.detail} Existing analyses are still available to read — see recent runs below.`);
      } else {
        setErrorMessage('Something went wrong requesting this analysis. Please try again.');
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Request an analysis">
      <label htmlFor="ticker-input">Ticker (NSE/BSE)</label>
      <input
        id="ticker-input"
        name="ticker"
        value={ticker}
        onChange={(event) => setTicker(event.target.value)}
        placeholder="RELIANCE or SIEMENS.NS"
        maxLength={32}
        required
      />
      <label htmlFor="date-input">Analysis date (optional)</label>
      <input
        id="date-input"
        name="date"
        type="date"
        value={analysisDate}
        onChange={(event) => setAnalysisDate(event.target.value)}
      />
      <fieldset>
        <legend>Profile</legend>
        <label>
          <input
            type="radio"
            name="profile"
            value="fast"
            checked={profile === 'fast'}
            onChange={() => setProfile('fast')}
          />
          Fast (~4 min)
        </label>
        <label>
          <input
            type="radio"
            name="profile"
            value="detailed"
            checked={profile === 'detailed'}
            onChange={() => setProfile('detailed')}
          />
          Detailed (~14 min)
        </label>
      </fieldset>
      <button type="submit" disabled={submitting}>
        {submitting ? 'Requesting…' : 'Analyse'}
      </button>
      {errorMessage && <div role="alert">{errorMessage}</div>}
    </form>
  );
}
