'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { analyzeRun, RateLimitError } from '@/lib/api-client/client';

export function SearchForm() {
  const router = useRouter();
  const [ticker, setTicker] = useState('');
  const [profile, setProfile] = useState<'fast' | 'detailed'>('fast');
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!ticker.trim()) return;

    setSubmitting(true);
    setErrorMessage(null);

    try {
      const { accepted, cached } = await analyzeRun({ ticker, profile });
      router.push(`/runs/${accepted.id}?cached=${cached ? '1' : '0'}`);
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
