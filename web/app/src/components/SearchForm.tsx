'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useState } from 'react';
import { analyzeRun, RateLimitError } from '@/lib/api-client/client';

type Variant = 'hero' | 'cta' | 'nav';

export function SearchForm({ variant = 'hero' }: { variant?: Variant }) {
  const router = useRouter();
  // The "no analysis yet" branch of /stock/[ticker]/[date] deep-links here as
  // /?ticker=…&date=…, so seed the form from the URL rather than dropping the
  // user onto an empty box they have to retype.
  const searchParams = useSearchParams();
  const [ticker, setTicker] = useState(() => searchParams.get('ticker') ?? '');
  const [analysisDate, setAnalysisDate] = useState(() => searchParams.get('date') ?? '');
  const [profile, setProfile] = useState<'fast' | 'detailed'>('fast');
  const [timeHorizon, setTimeHorizon] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // The cta and nav variants only show a ticker field (matching the design's
  // visual scope for those placements) — they never render date/profile UI,
  // so even if a deep link prefilled analysisDate, don't forward it for those
  // variants. The hero variant's behaviour is unchanged: it forwards
  // analysisDate exactly as before.
  const showDateAndProfile = variant === 'hero';

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
        ...(showDateAndProfile && analysisDate ? { analysis_date: analysisDate } : {}),
        ...(showDateAndProfile && timeHorizon.trim() ? { time_horizon: timeHorizon.trim() } : {}),
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

  if (variant === 'nav') {
    // No form-level aria-label here: the sr-only <label htmlFor> below
    // already names the input, and duplicating the same text as the form's
    // accessible name causes getByLabelText to match both elements
    // ambiguously.
    return (
      <form onSubmit={handleSubmit} className="flex-1 max-w-md relative">
        <label htmlFor="ticker-nav" className="sr-only">Research another stock</label>
        <svg className="absolute left-4 top-1/2 -translate-y-1/2" width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="7" stroke="#8FA0C4" strokeWidth="2"/><path d="M21 21l-4.3-4.3" stroke="#8FA0C4" strokeWidth="2" strokeLinecap="round"/></svg>
        <input
          id="ticker-nav"
          value={ticker}
          onChange={(event) => setTicker(event.target.value)}
          placeholder="Research another stock"
          maxLength={32}
          className="w-full rounded-full border border-white/15 bg-white/[0.06] pl-11 pr-4 py-2.5 text-sm text-white placeholder:text-white/55 focus:outline-none focus:border-[#3DA2F1] transition-colors"
        />
        {/* The reference markup has no visible submit button for this variant
            (submits on Enter only) — this sr-only button preserves a11y and
            no-JS parity with the hero/cta variants without changing the
            visual shell. */}
        <button type="submit" className="sr-only" disabled={submitting}>
          {submitting ? 'Requesting…' : 'Analyse'}
        </button>
        {errorMessage && <div role="alert" className="absolute top-full mt-1 text-xs text-red-300">{errorMessage}</div>}
      </form>
    );
  }

  if (variant === 'cta') {
    return (
      <form onSubmit={handleSubmit} aria-label="Request an analysis" className="mt-9 flex flex-col sm:flex-row gap-3 max-w-md mx-auto">
        {/* The source (landing-fintech/index.html:1243) gives both this field
            and the hero's #ticker-hero the identical sr-only label "Ticker
            symbol" — harmless in raw static HTML, but once both sections
            render on the same assembled page (Task 7) it makes the two
            fields indistinguishable by accessible name, which is a real a11y
            defect (and what broke getByLabel('Ticker symbol') in the E2E
            suite once CtaSection joined Hero on one page: Playwright's
            getByLabel matches substrings, so even a longer label starting
            with "Ticker symbol" stayed ambiguous). Given a label with no
            overlapping substring instead of reusing the hero's. */}
        <label htmlFor="ticker-cta" className="sr-only">Enter a ticker to research</label>
        <input
          id="ticker-cta"
          value={ticker}
          onChange={(event) => setTicker(event.target.value)}
          placeholder="Enter a ticker, e.g. TCS"
          maxLength={32}
          className="flex-1 rounded-full border border-white/15 bg-white/[0.07] px-5 py-3.5 text-sm text-white placeholder:text-white/40 focus:outline-none focus:border-[#3DA2F1] transition-all duration-150"
        />
        <button type="submit" disabled={submitting} className="btn-shimmer rounded-full bg-white text-[#050A18] text-sm font-black px-7 py-3.5 hover:bg-white/90 transition-colors whitespace-nowrap">
          {submitting ? 'Requesting…' : 'Start researching'}
        </button>
        {errorMessage && <div role="alert" className="text-xs text-red-300 mt-3">{errorMessage}</div>}
      </form>
    );
  }

  // hero (default) — full fields
  //
  // Always stacks vertically (`flex-col`, no `sm:flex-row`): the source form
  // this variant was ported from (landing-fintech/index.html:565) only ever
  // had 2 children (ticker input + submit button), where `sm:flex-row` reads
  // fine. This hero variant adds a 3rd child (the date input + profile
  // fieldset row) that the source never had — at `sm:` and above, 3 flex
  // children racing for a 448px (`max-w-md`) row starve the ticker input
  // (`flex-1`) down to ~62px (just its icon padding), which measured as a
  // genuine collapse in-browser at 1280/768/640px (final review finding #1).
  // Keeping this column-only avoids the collapse at every viewport.
  return (
    <form onSubmit={handleSubmit} aria-label="Request an analysis" className="u-rise mt-8 flex flex-col gap-3 max-w-md" style={{ ['--rise' as string]: '16px', ['--delay' as string]: '.32s' }}>
      <div className="relative flex-1">
        <svg className="absolute left-4 top-1/2 -translate-y-1/2" width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="7" stroke="#8FA0C4" strokeWidth="2"/><path d="M21 21l-4.3-4.3" stroke="#8FA0C4" strokeWidth="2" strokeLinecap="round"/></svg>
        <label htmlFor="ticker-hero" className="sr-only">Ticker symbol</label>
        <input
          id="ticker-hero"
          value={ticker}
          onChange={(event) => setTicker(event.target.value)}
          placeholder="Try TCS, RELIANCE, SIEMENS…"
          maxLength={32}
          className="w-full rounded-full border border-white/15 bg-white/[0.06] pl-11 pr-4 py-3.5 text-sm text-white placeholder:text-white/40 focus:outline-none focus:border-[#3DA2F1] focus:bg-white/[0.09] transition-all duration-150"
        />
      </div>
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
        <label htmlFor="date-hero" className="sr-only">Analysis date (optional)</label>
        <input
          id="date-hero"
          type="date"
          value={analysisDate}
          onChange={(event) => setAnalysisDate(event.target.value)}
          className="rounded-full border border-white/15 bg-white/[0.06] px-4 py-2 text-xs text-white/70 focus:outline-none focus:border-[#3DA2F1]"
        />
        <fieldset className="flex items-center gap-3 text-xs text-white/60">
          <legend className="sr-only">Profile</legend>
          <label className="flex items-center gap-1.5">
            <input type="radio" name="profile" checked={profile === 'fast'} onChange={() => setProfile('fast')} /> Fast (~4 min)
          </label>
          <label className="flex items-center gap-1.5">
            <input type="radio" name="profile" checked={profile === 'detailed'} onChange={() => setProfile('detailed')} /> Detailed (~14 min)
          </label>
        </fieldset>
      </div>
      <div className="relative flex-1">
        <label htmlFor="horizon-hero" className="sr-only">Time horizon (optional)</label>
        <input
          id="horizon-hero"
          value={timeHorizon}
          onChange={(event) => setTimeHorizon(event.target.value)}
          placeholder="Holding period, e.g. 3-6 months (optional)"
          maxLength={64}
          className="w-full rounded-full border border-white/15 bg-white/[0.06] px-4 py-2.5 text-xs text-white placeholder:text-white/40 focus:outline-none focus:border-[#3DA2F1] focus:bg-white/[0.09] transition-all duration-150"
        />
      </div>
      <button type="submit" disabled={submitting} className="btn-shimmer rounded-full bg-[#1C6FE6] text-white text-sm font-bold px-7 py-3.5 hover:bg-[#237FFB] transition-colors whitespace-nowrap self-start">
        {submitting ? 'Requesting…' : 'Start researching'}
      </button>
      {errorMessage && <div role="alert" className="text-xs text-red-300">{errorMessage}</div>}
    </form>
  );
}
