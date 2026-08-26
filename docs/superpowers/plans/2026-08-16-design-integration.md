# Design + Backend Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unstyled functional home page and results pages in `web/app/` with the real visual design from `web/design/landing-fintech/index.html` (landing) and `web/design/research/index.html` (results), wired to the live API data already built in Tasks 1-11 of the prior plan — full page, both pages, decorative sections included.

**Architecture:** Port each design file's markup/CSS into the corresponding Next.js route as Tailwind JSX, preserving class names, tokens, and motion vocabulary exactly (`web/design/DESIGN.md` is the extraction source and stays authoritative — if a port disagrees with it, re-check the HTML, not memory). Functional islands (the three ticker-search forms, the verdict card, the reports accordion, the run-history panel, the run-status banner) get real data from the existing `client.ts`/`poll.ts`/`format.ts` layer built previously; everything else (nav links, ticker marquee, trust strip, pipeline stack, use-cases, deck, live-split feature, FAQ, footer, sidebar) is a faithful static-content port with no backend calls.

**Tech Stack:** Same as before — Next.js 16 App Router, TypeScript, TanStack Query, react-markdown. Adds: Tailwind config extensions for the design's custom tokens/utilities, Google Fonts (Inter, Inter Tight), a small IntersectionObserver-based scroll-reveal utility (replaces the reference file's inline `<script>`), inline inline SVG art ported as JSX.

**Spec:** The two reference files are the spec, not a doc that describes them — `web/design/landing-fintech/index.html` (1429 lines) and `web/design/research/index.html` (968 lines), read together with `web/design/DESIGN.md` (471 lines, extraction notes and hard rules). The prior plan, `docs/superpowers/plans/2026-08-16-frontend-integration.md`, is the spec for the functional/API layer this work sits on top of — read its Global Constraints too; they still bind.

**Testing scope for this plan (explicit user instruction):** Light. Smoke-level checks that components render without crashing across the real data shapes (null levels, completed/failed/queued/contested), plus the two product rules that must never regress (null price never renders as 0; a contested verdict never renders as if it weren't). No new exhaustive TDD suites, no new E2E specs beyond re-running the existing ones to confirm nothing broke. Manual verification is the user's own job from here.

## Global Constraints

- **Do not edit `tradingagents/`, `api/`, or `cli/`.**
- **Never add `Co-Authored-By: Claude` or any AI attribution** to commits.
- **Never fabricate data.** Every number in a functional section (verdict, reports, run stats, recent runs) comes from the live API response. The reference HTML's hardcoded SIEMENS.NS numbers are illustrations to copy the *pattern* from, never values to hardcode into the live components. Marketing-copy numbers (12 agents, 5 teams, 2 debates, 10 reports, ~4/~14 min) are product facts from `PRODUCT_OVERVIEW.md`, not per-run data — those stay static in decorative sections only.
- **Never render a missing price level as `0`.** `formatPrice` (`web/app/src/lib/format.ts`) already encodes this — reuse it, don't reimplement.
- **A contested verdict (`verdict_is_contested`) must never render as if it weren't** — `RunHistoryPanel`'s existing baseline-first behavior (Task 6/fix-wave of the prior plan) must survive the reskin unchanged.
- **`rating` (5-tier) and `levels.action` (3-tier) stay independent fields** — the design's 5-stop ruler shows `rating`; the ACTION cell in the stat grid shows `levels.action`; never collapse them.
- **DESIGN.md's hard motion rules bind:** scroll-reveals are progressive enhancement (content visible without JS/before the observer fires); never transition a scroll-linked `transform`; ambient loops (ticker marquee) pause off-screen via `data-motion-gate`; no pulsing status dots; `prefers-reduced-motion` drops movement, keeps opacity/colour; accordions use class-driven `max-height`, never `grid-template-rows`.
- **Tailwind opacity gotcha:** arbitrary values off the 0/5/10.../100 scale emit nothing (`bg-[#050A18]/92` → no rule). Use the scale, `/[0.92]` bracket syntax, or inline `style`.
- **Custom classes never sit *alongside* a Tailwind utility setting the same property** at equal specificity — replace the utility, don't add beside it (Tailwind's injected stylesheet wins ties).
- **Green/red are reserved for price direction only** — never for bull/bear, ratings, or run status.
- **Frame as research, not advice** — SEBI-sensitive; keep the footer disclaimer from the reference file.
- **Zero em-dashes in visible copy** carried over from the reference files (the files already satisfy this — don't introduce new ones when adapting).
- **The design's four standing detector overrides are not defects:** `overused-font` (Inter/Inter Tight are pinned), `marquee` (the ticker is a requested feature, pauses on hover), `dark-glow` (an inset highlight, not a halo), `layout-transition` (accordion `max-height` is the only working option here — see DESIGN.md §5).

---

## File Structure

```
web/app/src/
├── app/
│   ├── globals.css                       # Task 1: design tokens, base utility classes
│   ├── layout.tsx                        # Task 1: Google Fonts link
│   ├── page.tsx                          # Tasks 3-7: assembled landing page
│   ├── runs/[id]/page.tsx                # Task 11: unchanged data-fetch, new RunView
│   └── stock/[ticker]/[date]/page.tsx    # Task 11: unchanged data-fetch, new RunView
├── components/
│   ├── SearchForm.tsx                    # Task 2: variant-aware (hero | cta | nav)
│   ├── landing/
│   │   ├── SiteNav.tsx                   # Task 3
│   │   ├── TickerMarquee.tsx             # Task 3
│   │   ├── Hero.tsx                      # Task 3
│   │   ├── TrustStrip.tsx                # Task 4
│   │   ├── PipelineStack.tsx             # Task 4
│   │   ├── UseCases.tsx                  # Task 5
│   │   ├── Deck.tsx                      # Task 5
│   │   ├── LiveSplitFeature.tsx          # Task 6
│   │   ├── Faq.tsx                       # Task 6
│   │   ├── CtaSection.tsx                # Task 7
│   │   ├── SiteFooter.tsx                # Task 7 (shared landing/research variant)
│   │   └── RecentRunsSection.tsx         # Task 7 (real data, new design-consistent card list)
│   ├── research/
│   │   ├── ResearchNav.tsx               # Task 8
│   │   ├── RunHeader.tsx                 # Task 8 (dark run-header, replaces old status area)
│   │   ├── TheDesk.tsx                   # Task 9 (sidebar, simplified/static)
│   │   ├── TheCall.tsx                   # Task 9 (verdict card, replaces VerdictSummary's old markup)
│   │   └── ReportsRecord.tsx             # Task 10 (reports accordion, replaces ReportsAccordion's old markup)
│   ├── RunStatusBanner.tsx               # Task 8: reskinned (queued/running/failed, dark theme)
│   ├── VerdictSummary.tsx                # Task 9: becomes a thin wrapper delegating to TheCall
│   ├── ReportsAccordion.tsx              # Task 10: becomes a thin wrapper delegating to ReportsRecord
│   ├── RunHistoryPanel.tsx               # Task 11: reskinned, same props/logic
│   └── RunView.tsx                       # Task 11: assembles research/RunHeader + TheDesk + TheCall + RunHistoryPanel + ReportsRecord
└── lib/
    └── scroll-reveal.ts                  # Task 1: IntersectionObserver hook for .u-reveal
```

Component-per-file, same rationale as the prior plan: each design section is independently understandable and portable, and a reviewer can diff one file per task without holding the whole page in their head.

---

### Task 1: Design tokens, fonts, and shared motion utilities

**Files:**
- Modify: `web/app/src/app/globals.css`
- Modify: `web/app/src/app/layout.tsx`
- Modify: `web/app/tailwind.config.ts` (create if create-next-app v4's Tailwind setup is CSS-only — check first; Tailwind v4 via `@tailwindcss/postcss` may configure entirely in CSS via `@theme` instead of a JS config file. Use whichever the installed version expects — verify with `cat web/app/postcss.config.mjs` and the Tailwind version in `package.json` before choosing.)
- Create: `web/app/src/lib/scroll-reveal.ts`

**Source to extract from:** `web/design/DESIGN.md` §1 (tokens), §2 (typography), §3 (spacing), §4 (motion) — and cross-check against the literal `:root` block and `<style>` block at the top of `web/design/landing-fintech/index.html` (roughly lines 1-440; read the file directly, DESIGN.md itself says "when something here disagrees with the code, the code wins").

- [ ] **Step 1: Add the design tokens**

Add the `:root` custom properties from DESIGN.md §1 to `globals.css`:

```css
:root {
  --navy: #00439D;  --accent-1: #1C6FE6;  --accent-2: #237FFB;  --accent-3: #3DA2F1;
  --ink: #010101;   --ink-2: #202020;     --muted: #757575;
  --tint: #F4F4F4;  --line-1: #EBEBEB;    --line-2: #E0E1E2;
  --void: #050A18;  --void-2: #0A1226;
}
```

- [ ] **Step 2: Add the base utility classes**

Read the exact rules for `.copy`, `.copy-dark`, `.measure`, `.font-tight`, `.grad-navy`, `.grad-text`, `.btn-shimmer`, `.u-rise`, `.u-reveal`/`.is-in`, `.u-ticker`/`.u-ticker-track` from `web/design/landing-fintech/index.html`'s `<style>` block (search for each class name) and port them verbatim into `globals.css`. Also port the research-page-specific ones from `web/design/research/index.html`'s `<style>` block: `.rep`, `.rep__panel`, `.rep__doc`, `.rep__bar`, `.rep__chev`, `.rep__more`, `.ledger`/`.duel` (needed even though the topic-by-topic ledger content itself is out of scope — Task 11's RunHistoryPanel reskin borrows this visual pattern), `.rk` (table), `.team`/`.ag` (sidebar), `--dur-open`/`--ease-open`, `.js-armed` gating. Bring over the `@media (prefers-reduced-motion: reduce)` block from both files (they're near-identical; one copy suffices).

- [ ] **Step 3: Add the Google Fonts link**

In `web/app/src/app/layout.tsx`, add to the `<head>` (or via Next's `next/font/google` if preferred — either is acceptable, but if using `next/font`, verify the resulting CSS variable names match what `.font-tight` and the body font expect, or adjust the utility classes accordingly rather than silently changing the type ramp):

```
Inter (400,500,600,700) — body
Inter Tight (500,600,700,800,900) — .font-tight, headings, labels
```

- [ ] **Step 4: Build the scroll-reveal utility**

`web/app/src/lib/scroll-reveal.ts` — replaces the reference file's inline `<script>` IntersectionObserver logic with a React hook, honoring DESIGN.md's rule that content is visible by default and JS only *arms* the hidden state:

```ts
'use client';

import { useEffect, useRef } from 'react';

/**
 * Progressive-enhancement scroll reveal. The element is visible by default
 * (no inline opacity:0) — this hook adds `anim-ready` once mounted, which is
 * what actually arms the CSS hidden start state (see .u-reveal in
 * globals.css). If this hook never runs (JS disabled), the element stays at
 * its visible resting state. DESIGN.md §4 rule 1.
 */
export function useScrollReveal<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    el.classList.add('anim-ready');

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-in');
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.15 },
    );
    observer.observe(el);

    return () => observer.disconnect();
  }, []);

  return ref;
}
```

Also add the `.u-reveal`/`.anim-ready`/`.is-in` CSS rule set (from the reference file) that this hook's class names actually gate, if not already ported in Step 2.

For `data-motion-gate` (ambient loops pausing off-screen — the ticker marquee), port the reference file's gating CSS/JS as a second small hook or inline `IntersectionObserver` in `TickerMarquee.tsx` (Task 3) rather than here, since it's used in exactly one place.

- [ ] **Step 5: Verify the app still builds and the tokens are visible**

```bash
cd web/app && npm run build
```

Expected: clean build. This task adds no new pages, so there's nothing else to smoke-check yet — later tasks consume these tokens/utilities directly.

- [ ] **Step 6: Commit**

```bash
git add web/app/src/app/globals.css web/app/src/app/layout.tsx web/app/src/lib/scroll-reveal.ts web/app/tailwind.config.ts
git commit -m "feat(web): port design tokens, fonts, and scroll-reveal utility"
```

(Omit `tailwind.config.ts` from the `git add` if Step 1's investigation found Tailwind v4's CSS-only `@theme` config is what's actually in use — adjust the file list to whatever you actually touched.)

---

### Task 2: `SearchForm` variants (hero / cta / nav)

**Files:**
- Modify: `web/app/src/components/SearchForm.tsx`
- Modify: `web/app/tests/unit/SearchForm.test.tsx`

**Interfaces:**
- Consumes: `analyzeRun`, `RateLimitError` (existing, unchanged)
- Produces: `<SearchForm variant="hero" | "cta" | "nav" />` — same submit behavior for all three (200/202/429 branching, deep-link prefill via `useSearchParams`, `analysis_date` support), different markup per variant.

**Why one component, not three:** the three ticker-search instances in the design (hero, CTA, research-page nav) are visually distinct but functionally identical — same fields, same submit handler, same error handling. Splitting them into three separate components would triplicate the `handleSubmit` logic (and its 200/202/429/error-message correctness, which was reviewed carefully in the prior plan). A `variant` prop keeps one source of truth for behavior.

- [ ] **Step 1: Extract the three markup patterns from the source**

Read the three form instances in `web/design/landing-fintech/index.html`:
- Hero form: `id="ticker-hero"`, around line 565-575 (dark, icon-prefixed input, pill button, `max-w-md`)
- CTA form: `id="ticker-cta"`, around line 1242-1249 (dark, no icon, white button, `max-w-md mx-auto`)

And in `web/design/research/index.html`:
- Nav form: `id="ticker"`, around line 232-237 (compact, icon-prefixed, `flex-1 max-w-md`, no visible submit button — submits on Enter, or add a visually-hidden submit button for a11y/no-JS parity with the others)

Note the CTA and nav forms don't have the hero's search icon / analysis-date / profile radio fields visible in the reference markup — the reference page never wired real behavior in, so it never needed those. For the CTA and nav variants, keep the *visual* shell exactly as the reference (single ticker input, one button) but the real submit still needs `profile` and (optionally) `analysis_date` to reach `analyzeRun`. Resolve this by defaulting `profile` to `'fast'` and omitting `analysis_date` for the `cta` and `nav` variants (no date/profile UI shown, matching the reference's visual scope), while the `hero` variant keeps the full set of fields (ticker, date, profile radios) already built in the prior plan. State this decision in your report — it's a deliberate visual-fidelity vs. feature-parity tradeoff, not an oversight.

- [ ] **Step 2: Rewrite `SearchForm.tsx` with the variant prop**

Keep the existing `handleSubmit`, `useSearchParams` prefill, and error-handling logic exactly as built (don't touch that logic — the 200/202/429 branching was reviewed and approved). Change only the rendered markup, branching on `variant`:

```tsx
'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useState } from 'react';
import { analyzeRun, RateLimitError } from '@/lib/api-client/client';

type Variant = 'hero' | 'cta' | 'nav';

export function SearchForm({ variant = 'hero' }: { variant?: Variant }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [ticker, setTicker] = useState(() => searchParams.get('ticker') ?? '');
  const [analysisDate, setAnalysisDate] = useState(() => searchParams.get('date') ?? '');
  const [profile, setProfile] = useState<'fast' | 'detailed'>('fast');
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const showDateAndProfile = variant === 'hero';

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!ticker.trim()) return;

    setSubmitting(true);
    setErrorMessage(null);

    try {
      const { accepted, cached } = await analyzeRun({
        ticker,
        profile,
        ...(showDateAndProfile && analysisDate ? { analysis_date: analysisDate } : {}),
      });
      const query = new URLSearchParams({ cached: cached ? '1' : '0' });
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
    return (
      <form onSubmit={handleSubmit} aria-label="Research another stock" className="flex-1 max-w-md relative">
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
        <button type="submit" className="sr-only" disabled={submitting}>Analyse</button>
        {errorMessage && <div role="alert" className="absolute top-full mt-1 text-xs text-red-300">{errorMessage}</div>}
      </form>
    );
  }

  if (variant === 'cta') {
    return (
      <form onSubmit={handleSubmit} aria-label="Request an analysis" className="mt-9 flex flex-col sm:flex-row gap-3 max-w-md mx-auto">
        <label htmlFor="ticker-cta" className="sr-only">Ticker symbol</label>
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
      <button type="submit" disabled={submitting} className="btn-shimmer rounded-full bg-[#1C6FE6] text-white text-sm font-bold px-7 py-3.5 hover:bg-[#237FFB] transition-colors whitespace-nowrap self-start">
        {submitting ? 'Requesting…' : 'Start researching'}
      </button>
      {errorMessage && <div role="alert" className="text-xs text-red-300">{errorMessage}</div>}
    </form>
  );
}
```

The exact `className` strings above are a starting point extracted from the source at the time this plan was written — re-verify each against the live `web/design/landing-fintech/index.html` / `web/design/research/index.html` markup while implementing, since those files are the actual source of truth per DESIGN.md's own rule, and copy any classes this plan missed (e.g. exact focus-ring colors, transition durations).

- [ ] **Step 3: Update the existing tests**

The prior plan's 3 `SearchForm.test.tsx` tests (200→cached=1, 202→cached=0, 429→banner) call `render(<SearchForm />)` with no variant — since `variant` defaults to `'hero'`, these should keep passing unchanged. Run them to confirm:

```bash
cd web/app && npx vitest run tests/unit/SearchForm.test.tsx
```

Add one light smoke test confirming the `nav` and `cta` variants render their single ticker input without crashing (not a full behavior re-test — the submit logic is already covered by the hero-variant tests and doesn't change per variant):

```tsx
it('renders the nav variant with a single ticker input', () => {
  render(<SearchForm variant="nav" />);
  expect(screen.getByLabelText('Research another stock')).toBeInTheDocument();
});

it('renders the cta variant with a single ticker input', () => {
  render(<SearchForm variant="cta" />);
  expect(screen.getByPlaceholderText('Enter a ticker, e.g. TCS')).toBeInTheDocument();
});
```

- [ ] **Step 4: Run and commit**

```bash
cd web/app && npx vitest run tests/unit/SearchForm.test.tsx
git add web/app/src/components/SearchForm.tsx web/app/tests/unit/SearchForm.test.tsx
git commit -m "feat(web): SearchForm variants for hero, CTA, and nav placements"
```

---

### Task 3: Landing — nav, ticker marquee, hero

**Files:**
- Create: `web/app/src/components/landing/SiteNav.tsx`
- Create: `web/app/src/components/landing/TickerMarquee.tsx`
- Create: `web/app/src/components/landing/Hero.tsx`

**Interfaces:**
- Consumes: `<SearchForm variant="hero" />` (Task 2)
- Produces: `<SiteNav />`, `<TickerMarquee />`, `<Hero />` — assembled into `page.tsx` in Task 7.

**Source:** `web/design/landing-fintech/index.html`, nav ~lines 443-463, ticker ~465-475, hero ~477-660+ (read through the end of the hero section — the "contested figure" card inside the hero, the SVG light-ribbon background, and the grid layout). This is the largest single visual set-piece on the page; take it in one pass, it doesn't split cleanly.

- [ ] **Step 1: Port the nav**

`SiteNav.tsx` — sticky header, logo, in-page anchor links (`#how`, `#use-cases`, `#deck`, `#live`, `#faq`), "Research a stock" CTA anchor (`href="#try"`, scrolls to the hero form — the hero form's wrapping element needs `id="try"` to match). Static, no data.

- [ ] **Step 2: Port the ticker marquee**

`TickerMarquee.tsx` — the scrolling ticker-symbol strip. This is the one ambient/looping animation on the page, so it needs `data-motion-gate` and a pause-off-screen `IntersectionObserver` (DESIGN.md §4 rule 3 — "unpausable loops are an accessibility failure"). Implement as a small local hook or inline effect (not `scroll-reveal.ts`, which is for reveal-on-scroll, a different behavior). Also preserve the CSS `:hover { animation-play-state: paused }` from the source.

- [ ] **Step 3: Port the hero**

`Hero.tsx` — headline, subtext, the SVG light-ribbon background (port as inline JSX SVG, values copied verbatim from source), the "contested figure" illustrative card (static marketing content — this shows *what the product produces*, not a real run, so its SIEMENS numbers stay hardcoded exactly as in the source; do not wire it to live data), and `<SearchForm variant="hero" />` in place of the source's non-functional `<form id="try" onsubmit="return false;">`. Wrap the SearchForm in a container with `id="try"` so the nav's anchor link still resolves.

Apply `useScrollReveal` (Task 1) to the elements the source marks with `.u-rise`/`--rise`/`--delay` custom properties, preserving the staggered-entrance timing.

- [ ] **Step 4: Smoke-check**

```bash
cd web/app && npm run build
```

No dedicated component tests for this task — it's static marketing content plus the already-tested `SearchForm`. A clean build plus a manual look (the user will do this) is the right verification depth per this plan's light-testing scope.

- [ ] **Step 5: Commit**

```bash
git add web/app/src/components/landing/SiteNav.tsx web/app/src/components/landing/TickerMarquee.tsx web/app/src/components/landing/Hero.tsx
git commit -m "feat(web): port landing nav, ticker marquee, and hero"
```

---

### Task 4: Landing — trust strip and pipeline stack

**Files:**
- Create: `web/app/src/components/landing/TrustStrip.tsx`
- Create: `web/app/src/components/landing/PipelineStack.tsx`

**Source:** `web/design/landing-fintech/index.html`, trust strip section and the `#how` sticky-card-stack section (search for `.stack-card`, roughly lines 680-1090 — the file's own section comments mark the boundaries, e.g. "2 · RESEARCHERS" at line 759).

- [ ] **Step 1: Port the trust strip** — light section, static content, no special motion beyond standard scroll-reveal.

- [ ] **Step 2: Port the pipeline stack**

This is the "sticky card stack" pattern DESIGN.md §5 documents: `.stack-card` elements pinned at stepped `top` offsets. Respect the two structural constraints DESIGN.md calls out:
- `--strip` must exceed `padding-top + label height`
- `nav + (n-1)*strip + cardHeight` must fit the viewport, or the last card clips

Copy the exact `--strip`/`top` values from the source rather than re-deriving them — they were already tuned against these constraints.

- [ ] **Step 3: Smoke-check and commit**

```bash
cd web/app && npm run build
git add web/app/src/components/landing/TrustStrip.tsx web/app/src/components/landing/PipelineStack.tsx
git commit -m "feat(web): port landing trust strip and pipeline stack"
```

---

### Task 5: Landing — use-cases and deck

**Files:**
- Create: `web/app/src/components/landing/UseCases.tsx`
- Create: `web/app/src/components/landing/Deck.tsx`

**Source:** `web/design/landing-fintech/index.html`, `#use-cases` section and `#deck` section (search for `.deck-track` — the scroll-pinned horizontal deck DESIGN.md §5 documents).

- [ ] **Step 1: Port use-cases** — light section, card grid, standard scroll-reveal.

- [ ] **Step 2: Port the deck**

The scroll-pinned horizontal deck (`.deck-track` translated by scroll progress) is the most JS-heavy remaining section. Port the source's scroll-progress calculation into a React effect (`useEffect` + scroll listener, or `useScrollReveal`-adjacent hook if the source's approach fits that shape — read the source's inline `<script>` for the exact math before reimplementing, don't guess the transform formula). Respect DESIGN.md §4 rule 2: **never put a CSS `transition` on the scroll-linked transform property** — it will pin the element at its start value and override even `!important` inline styles.

- [ ] **Step 3: Smoke-check and commit**

```bash
cd web/app && npm run build
git add web/app/src/components/landing/UseCases.tsx web/app/src/components/landing/Deck.tsx
git commit -m "feat(web): port landing use-cases and scroll-pinned deck"
```

---

### Task 6: Landing — live split feature and FAQ

**Files:**
- Create: `web/app/src/components/landing/LiveSplitFeature.tsx`
- Create: `web/app/src/components/landing/Faq.tsx`

**Source:** `web/design/landing-fintech/index.html`, `#live` section and `#faq` section (search for the FAQ's accordion markup — same `max-height` class-driven pattern as the research page's report accordion, not `grid-template-rows`).

- [ ] **Step 1: Port the live split feature** — badge + h2 + bullets + 2 CTAs, animated panel opposite. Static content, standard scroll-reveal on entrance.

- [ ] **Step 2: Port the FAQ accordion**

Implement with React state (one open index, or a Set of open indices — check the source: does it allow multiple open at once, or one-at-a-time like the research page's evidence trace? Match the source's actual behavior, don't assume). Use the `--dur-open`/`--ease-open` custom properties and `max-height` transition pattern from Task 1's ported CSS, not a new one.

- [ ] **Step 3: Smoke-check and commit**

```bash
cd web/app && npm run build
git add web/app/src/components/landing/LiveSplitFeature.tsx web/app/src/components/landing/Faq.tsx
git commit -m "feat(web): port landing live-split feature and FAQ accordion"
```

---

### Task 7: Landing — CTA, footer, recent runs, and page assembly

**Files:**
- Create: `web/app/src/components/landing/CtaSection.tsx`
- Create: `web/app/src/components/landing/SiteFooter.tsx`
- Create: `web/app/src/components/landing/RecentRunsSection.tsx`
- Modify: `web/app/src/app/page.tsx`
- Delete: `web/app/src/components/RecentRuns.tsx` (superseded by `RecentRunsSection.tsx`; confirm nothing else imports the old one before deleting)

**Interfaces:**
- Consumes: `<SearchForm variant="cta" />` (Task 2), `listRuns` / `RunSummary` (existing `client.ts`), all landing components from Tasks 3-6.

**Source:** `web/design/landing-fintech/index.html`, CTA section (~1210-1252, already read in full while planning — see this plan's own extracted markup above), footer (~1254-1290+).

- [ ] **Step 1: Port the CTA section** with `<SearchForm variant="cta" />` in place of the source's dead form.

- [ ] **Step 2: Port the footer**

Include the SEBI-sensitive disclaimer paragraph from the source verbatim (the "research tool for Indian-listed equities... nothing on this page is investment advice" text) — this is a Global Constraint, not just visual content. Keep the `TODO(legal)` comment; don't resolve it, that's explicitly out of scope for this plan.

- [ ] **Step 3: Build `RecentRunsSection`**

No exact template exists in the reference file for this (the static comp never needed a real "recent runs" list). Design it consistent with the established system: light section, `rounded-2xl` cards (§3), `.copy`/`.measure` text classes (§2), the accent-1 color for links, using real `RunSummary[]` data from `listRuns`:

```tsx
import Link from 'next/link';
import type { RunSummary } from '@/lib/api-client/client';

export function RecentRunsSection({ runs }: { runs: RunSummary[] }) {
  if (runs.length === 0) return null;

  return (
    <section className="py-16 lg:py-20 bg-white">
      <div className="max-w-screen-xl mx-auto px-6 lg:px-8">
        <h2 className="font-tight font-black text-[#010101] text-3xl tracking-[-0.02em]">Recent analyses</h2>
        <ul className="mt-8 grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {runs.map((run) => (
            <li key={run.id}>
              <Link
                href={`/runs/${run.id}`}
                className="block rounded-2xl border border-[#EBEBEB] p-5 hover:border-[#1C6FE6] transition-colors"
              >
                <p className="font-tight font-bold text-[#010101]">{run.ticker}</p>
                <p className="copy text-[#6F6F6F] mt-1">{run.analysis_date} · {run.status}</p>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Assemble `page.tsx`**

```tsx
import { listRuns } from '@/lib/api-client/client';
import { SiteNav } from '@/components/landing/SiteNav';
import { TickerMarquee } from '@/components/landing/TickerMarquee';
import { Hero } from '@/components/landing/Hero';
import { TrustStrip } from '@/components/landing/TrustStrip';
import { PipelineStack } from '@/components/landing/PipelineStack';
import { UseCases } from '@/components/landing/UseCases';
import { Deck } from '@/components/landing/Deck';
import { LiveSplitFeature } from '@/components/landing/LiveSplitFeature';
import { Faq } from '@/components/landing/Faq';
import { CtaSection } from '@/components/landing/CtaSection';
import { RecentRunsSection } from '@/components/landing/RecentRunsSection';
import { SiteFooter } from '@/components/landing/SiteFooter';

export default async function HomePage() {
  const recentRuns = await listRuns({ limit: 10 });

  return (
    <>
      <SiteNav />
      <TickerMarquee />
      <Hero />
      <TrustStrip />
      <PipelineStack />
      <UseCases />
      <Deck />
      <LiveSplitFeature />
      <Faq />
      <CtaSection />
      <RecentRunsSection runs={recentRuns} />
      <SiteFooter />
    </>
  );
}
```

Note: the prior plan's `page.tsx` wrapped `<SearchForm />` in a `<Suspense>` boundary because `useSearchParams` forces client-side rendering up to the nearest boundary. `Hero.tsx` (Task 3) now owns the only `<SearchForm variant="hero">` on this page — move the `<Suspense>` boundary into `Hero.tsx` around just the `<SearchForm>` (small, correctly-scoped fallback), not around the whole page.

- [ ] **Step 5: Full build + existing test suite**

```bash
cd web/app
npm run build
npx vitest run
npx playwright test
```

Expected: build clean, all existing unit tests pass (SearchForm's tests included), all existing E2E specs pass (they drive real user flows through this page — `search-to-result.spec.ts`, `rate-limit.spec.ts`, `cached-run.spec.ts` all submit through a `SearchForm` on this page and must still find the same `aria-label`/`getByLabel` selectors they used before. If a selector doesn't resolve because the visual port changed an accessible name, fix the port to match the existing test's expectation — do not weaken the test).

- [ ] **Step 6: Commit**

```bash
git add web/app/src/components/landing web/app/src/app/page.tsx
git rm web/app/src/components/RecentRuns.tsx
git commit -m "feat(web): assemble the full landing page with real search and recent runs"
```

---

### Task 8: Research — nav, run header, and status banner

**Files:**
- Create: `web/app/src/components/research/ResearchNav.tsx`
- Create: `web/app/src/components/research/RunHeader.tsx`
- Modify: `web/app/src/components/RunStatusBanner.tsx`

**Interfaces:**
- Consumes: `<SearchForm variant="nav" />` (Task 2), `RunDetail` (existing `client.ts`), `parseApiTimestamp` (existing `format.ts`, from the prior plan's fix wave)
- Produces: `<ResearchNav />`, `<RunHeader run={current} estimatedSeconds={...} />` (dark section, replaces the old plain-text status area for both in-progress and completed runs — completed shows real stats, in-progress/failed show the reskinned `RunStatusBanner`)

**Source:** `web/design/research/index.html` nav (~224-240) and run header (~242-270, already read in full while planning).

- [ ] **Step 1: Port the nav** with `<SearchForm variant="nav" />` and the "Fast run" / "Detailed run" label reflecting `current.profile` (real data, not the source's hardcoded "Fast run").

- [ ] **Step 2: Build `RunHeader` for the completed state**

Ticker, `analysed {analysis_date}` (use `parseApiTimestamp`-safe date formatting — the source shows `analysed 12 August 2026`; format `current.analysis_date`, which is already a plain date, not a timestamp needing timezone correction — don't apply `parseApiTimestamp` to a field that isn't a timestamp), and the stats `<dl>`:
- **Run time:** compute from `parseApiTimestamp(current.completed_at) - parseApiTimestamp(current.created_at)`, formatted as `Xm Ys` (reuse or extract the minute/second formatting logic already in `RunStatusBanner`, don't duplicate it — if it's not already a standalone function, factor it out into `format.ts` as part of this task, e.g. `formatDuration(ms: number): string`).
- **Written:** sum of word counts across all non-null `current.reports` fields. A report's word count is `text.trim().split(/\s+/).filter(Boolean).length` — reuse this in Task 10 too (`ReportsRecord`), so put it in `format.ts` as `countWords(text: string): number` rather than duplicating.
- **Reports:** count of non-null `current.reports` fields (out of 10).

Do not port the source's "All 12 agents finished" line as literal copy — the API has no per-agent count, only a report count (which isn't 1:1 with agent count; the risk panel alone is 3 agents producing 1 `risk_debate` document). Use a truthful equivalent, e.g. `"Analysis complete"` or `"{reportCount} of 10 reports"` — your call, but it must not assert a specific agent count the API didn't provide.

- [ ] **Step 3: Reskin `RunStatusBanner` for queued/running/failed**

Keep the existing logic (elapsed-time `useEffect`, `parseApiTimestamp` usage, terminal-status early return, the `estimatedSeconds` display) exactly as built and reviewed in the prior plan — this task only changes the rendered markup/classes to fit the dark run-header section visually (the reference file has no in-progress/failed state to copy, since it only shows a completed run — design it using the same dark tokens `--void`/`--void-2`/`.copy-dark`/white-on-dark opacity rules from DESIGN.md §1/§9 that the rest of this section already uses, so it reads as the same component in a different state, not a visual non-sequitur). No pulsing dots (Global Constraint / DESIGN.md rule 4) — a static status label is enough.

`RunHeader` renders `RunStatusBanner` when `current.status !== 'completed'`, and the stats `<dl>` when it is — mirroring `RunView`'s existing conditional, just moved one level down into this component.

- [ ] **Step 4: Smoke-check and commit**

```bash
cd web/app && npm run build
git add web/app/src/components/research/ResearchNav.tsx web/app/src/components/research/RunHeader.tsx web/app/src/components/RunStatusBanner.tsx web/app/src/lib/format.ts
git commit -m "feat(web): port research nav and run header, reskin the status banner"
```

---

### Task 9: Research — sidebar and verdict card

**Files:**
- Create: `web/app/src/components/research/TheDesk.tsx`
- Create: `web/app/src/components/research/TheCall.tsx`
- Modify: `web/app/src/components/VerdictSummary.tsx` (becomes a thin re-export of `TheCall` — see Step 3)
- Test: `web/app/tests/unit/components/VerdictSummary.test.tsx` (light update, see Step 4)

**Source:** `web/design/research/index.html`, sidebar ~272-320 and verdict card ~322-370+ (both already read in full while planning — see this plan's own extracted markup above for the exact stat-grid and five-stop-ruler structure).

- [ ] **Step 1: Build `TheDesk` (sidebar)**

Static team/agent list with jump-links (`#call`, `#record`, `#risk` etc. — match against whatever section ids Task 10/11 actually assign, verify at integration time). Render only when `current.status === 'completed'` (matching the parent's existing gate) — at that point "all done" is trivially true for the whole pipeline, so keep the per-agent checkmarks but do not claim any live per-agent granularity the API doesn't have (the checkmarks are decorative confirmation of a completed pipeline, not a status feed).

- [ ] **Step 2: Build `TheCall` (verdict card)**

Real data, mapped from `Verdict`:
- Five-stop ruler (`SELL / UNDERWEIGHT / HOLD / OVERWEIGHT / BUY`) with the dot/bar for `verdict.rating` highlighted — build a small lookup mapping the 5 rating strings to a 0-4 index, and render the `bg-[#00439D] ring-4 ring-[#00439D]/15` treatment (source's "active" stop styling) on that index, `bg-[#EBEBEB]` on the rest. If `verdict.rating` is null, render the ruler with nothing highlighted (not a fabricated default position) or omit the ruler and show `"Rating: Not set"` — your call, but never default to showing an arbitrary stop as if it were real.
- Stat grid: `ACTION` = `verdict.levels.action ?? 'Not set'`, `ENTRY` = `formatPrice(verdict.levels.entry_price)`, `STOP` = `formatPrice(verdict.levels.stop_loss)`, `HORIZON` = `verdict.time_horizon ?? 'Not set'`. Reuse `formatPrice` from `web/app/src/lib/format.ts` — do not reimplement the null-safety.
- Keep the explanatory copy paragraph pattern from the source ("Entry and stop are blank because...") but only render it when at least one of entry/stop is actually null — don't show an explanation for blank fields when both fields are populated.

- [ ] **Step 3: Retire the old `VerdictSummary` markup — keep the build green**

The prior plan's `VerdictSummary.tsx` (plain `<dl>`, no visual design) is superseded by `TheCall`. `RunView.tsx` still imports `VerdictSummary` at this point in the plan (Task 11, not this task, is what switches that import) — **do not delete `VerdictSummary.tsx`**, that would break the build for every task between this one and Task 11. Instead, replace its contents with a thin re-export:

```tsx
export { TheCall as VerdictSummary } from './research/TheCall';
```

If `TheCall`'s prop name isn't literally `verdict` (check what you actually named it in Step 2), adjust the re-export or add a small adapter — the point is `RunView.tsx`'s existing `<VerdictSummary verdict={...} />` call site keeps compiling unchanged until Task 11 deliberately updates it. Task 11 will delete this shim file once it switches `RunView` over to importing `TheCall` directly — note that handoff in your report so Task 11's implementer knows the shim is there to be removed, not preserved.

- [ ] **Step 4: Light test update + build check**

The existing `VerdictSummary.test.tsx` has 2 tests: null levels render "Not set" (never `₹0`), and rating/action render as separate values. Port these same two assertions against `TheCall` (same behavior, new component name/props if they changed) — this is exactly the "two product rules that must never regress" this plan's testing scope calls out, so don't drop this coverage even though testing is otherwise light.

```bash
cd web/app
npx vitest run tests/unit/components
npm run build
```

The build check matters here specifically because of the Step 3 shim — confirm `RunView.tsx`'s still-unchanged `<VerdictSummary verdict={...} />` call site actually compiles against the new re-export before moving on.

- [ ] **Step 5: Commit**

```bash
git add web/app/src/components/research/TheDesk.tsx web/app/src/components/research/TheCall.tsx web/app/src/components/VerdictSummary.tsx web/app/tests/unit/components/VerdictSummary.test.tsx
git commit -m "feat(web): port research sidebar and verdict card, retire old VerdictSummary markup"
```

(Adjust the `git add`/commit if Task 9 Step 3 deleted files instead of modifying them — use `git rm` for anything actually removed.)

---

### Task 10: Research — reports accordion

**Files:**
- Create: `web/app/src/components/research/ReportsRecord.tsx`
- Modify: `web/app/src/components/ReportsAccordion.tsx` (same retire-or-reexport decision as Task 9 Step 3, applied here)
- Modify: `web/app/src/lib/format.ts` (add `countWords`, if Task 8 didn't already)
- Test: `web/app/tests/unit/components/` — light addition, see Step 3

**Interfaces:**
- Consumes: `Reports` type (existing `client.ts`), `countWords` (Task 8 or this task, whichever lands first — coordinate: if Task 8 is done first, this task just imports it)

**Source:** `web/design/research/index.html`, "The full record" section ~610-767 (already read in full while planning — the exact `.rep`/`.rep__panel`/`.rep__bar`/`.rep__doc`/`.rep__more` structure and all 10 report rows are shown above in this plan).

**Scope decision already made (carried from the AskUserQuestion at plan time):** the evidence-trace drill-down (`.fig`/`.trace`, clickable inline source values) and the structured risk-comparison table (`.rk`, per-stance TRIM/INVALIDATION/RE-ENTRY grid) are **not built** — both require structured per-number/per-stance data the API's flat markdown `Reports` strings don't provide. `bull_case`, `bear_case`, and `risk_debate` render as three more rows in this same accordion, exactly like the other 7 reports — not as the source's topic-by-topic `.duel` ledger or `.rk` table. Do not attempt to parse the markdown into structured duels/rows; that's fragile and out of scope.

- [ ] **Step 1: Build `ReportsRecord`**

One `.rep` row per non-null field in `Reports`, in this order (evidence-first per the prior plan's product framing, matches `ReportsAccordion`'s existing `REPORT_ORDER`): `final_decision, investment_plan, bull_case, bear_case, trader_plan, risk_debate, market, sentiment, news, fundamentals`.

For each row:
- **Word count** (`.rep__w`): `countWords(reports[key])`, real.
- **Bar length** (`.rep__bar` / `--len`): `wordCount / maxWordCountAcrossPresentReports`, computed from the actual reports in this run — not the source's hardcoded ratios (`.25`, `.56`, `.84`, `1`, etc., which were tuned to SIEMENS.NS's specific word counts and don't generalize to a different run).
- **Panel content** (`.rep__doc`): the report's markdown rendered via `react-markdown` + `remark-gfm` (same as the old `ReportsAccordion`, just inside the new visual shell) — not the source's hand-truncated "opening extract" prose; render the full report, and let `.rep__doc`'s existing `max-height: 340px; overflow-y: auto` (ported in Task 1) do the length-honesty job the source's CSS comment describes ("a 204-word report and a 3,028-word report both open to the same max height").
- **Open/closed state:** React state, only the first row (`final_decision`, if present) open by default — same rule `ReportsAccordion` already enforces, just re-expressed with the new markup and the `max-height`-driven transition instead of the old plain `<details>` element.

- [ ] **Step 2: Retire the old `ReportsAccordion` markup — keep the build green**

Same rule as Task 9 Step 3: `RunView.tsx` still imports `ReportsAccordion` until Task 11 switches it over. Do not delete the file — replace its contents with a thin re-export:

```tsx
export { ReportsRecord as ReportsAccordion } from './research/ReportsRecord';
```

Adjust for `ReportsRecord`'s actual prop name if it isn't literally `reports`. Task 11 deletes this shim once `RunView` imports `ReportsRecord` directly — note that in your report.

- [ ] **Step 3: Light test**

Port the existing `ReportsAccordion` behavior tests that matter most for this plan's light-testing scope: only non-null fields render a row (not all 10 unconditionally), and only the first row starts open. Skip re-testing markdown rendering itself (react-markdown is a trusted dependency, already exercised) or writing new tests for the bar-length math beyond a basic sanity check that it doesn't divide by zero when only one report is present (`maxWordCount` = that one report's own count → `--len: 1`, not `NaN`).

```bash
cd web/app
npx vitest run tests/unit/components
npm run build
```

The build check confirms `RunView.tsx`'s still-unchanged `<ReportsAccordion reports={...} />` call site compiles against the Step 2 re-export.

- [ ] **Step 4: Commit**

```bash
git add web/app/src/components/research/ReportsRecord.tsx web/app/src/components/ReportsAccordion.tsx web/app/src/lib/format.ts web/app/tests/unit/components
git commit -m "feat(web): port the reports accordion with real word counts and bar lengths"
```

---

### Task 11: Research — history panel reskin and final assembly

**Files:**
- Modify: `web/app/src/components/RunHistoryPanel.tsx` (visual reskin only — props and logic unchanged)
- Modify: `web/app/src/components/RunView.tsx`
- Modify: `web/app/src/components/landing/SiteFooter.tsx` (confirm it's reusable as-is for the research page, or add a `variant` if the research footer in the source differs — check `web/design/research/index.html`'s footer against the landing one before assuming they're identical)
- Delete: `web/app/src/components/VerdictSummary.tsx`, `web/app/src/components/ReportsAccordion.tsx` (the Task 9/10 re-export shims — this task is what finally removes them, once `RunView` imports `TheCall`/`ReportsRecord` directly)
- Delete: `web/app/tests/unit/components/VerdictSummary.test.tsx` if Task 9 didn't already migrate it to test `TheCall` directly under a new filename (check; don't leave a test importing a component that no longer exists)

**Interfaces:**
- Consumes: `TheDesk`, `TheCall` (Task 9), `ReportsRecord` (Task 10), `RunHeader` (Task 8), `RunHistoryPanel` (this task)
- Produces: the fully assembled `<RunView>` both `runs/[id]/page.tsx` and `stock/[ticker]/[date]/page.tsx` already render unchanged (their own data-fetching code from the prior plan doesn't need to change — only what `RunView` renders internally changes)

**No exact source template exists for the run-history / contested-verdict card** — the reference research page shows a single, uncontested run. Style it consistently with the design system already ported (rounded-2xl card, `.copy`/`.measure` text, the accent-1 color for emphasis, the same card border/padding rhythm as `TheCall`), rather than inventing a new visual language. **Do not touch `RunHistoryPanel`'s props, data logic, or the baseline-first contested-verdict behavior** — that was specifically hardened in the prior plan's final review (the flag can't silently hide behind a failed history query) and only the markup should change here.

- [ ] **Step 1: Reskin `RunHistoryPanel`**

Same props (`runCount`, `isContested`, `history`, `isError`), same conditional logic, new markup matching the card system.

- [ ] **Step 2: Verify the research page footer**

Check `web/design/research/index.html`'s footer markup against `web/design/landing-fintech/index.html`'s (already ported in Task 7). If identical, reuse `SiteFooter` directly. If it differs (e.g. no marketing links, just the disclaimer), add a `variant="research"` to `SiteFooter` rather than forking a second footer component.

- [ ] **Step 3: Assemble `RunView`**

```tsx
'use client';

import { useQuery } from '@tanstack/react-query';
import { getRunHistory, type RunDetail } from '@/lib/api-client/client';
import { usePollRun } from '@/lib/poll';
import { ResearchNav } from './research/ResearchNav';
import { RunHeader } from './research/RunHeader';
import { TheDesk } from './research/TheDesk';
import { TheCall } from './research/TheCall';
import { ReportsRecord } from './research/ReportsRecord';
import { RunHistoryPanel } from './RunHistoryPanel';
import { SiteFooter } from './landing/SiteFooter';

export function RunView({
  initialRun,
  estimatedSeconds,
}: {
  initialRun: RunDetail;
  estimatedSeconds?: number;
}) {
  const { data: run } = usePollRun(initialRun.id, initialRun);
  const current = run ?? initialRun;

  const historyQuery = useQuery({
    queryKey: ['history', current.ticker, current.analysis_date, current.profile],
    queryFn: () => getRunHistory(current.ticker, current.analysis_date, current.profile),
    enabled: current.status === 'completed',
  });

  return (
    <>
      <ResearchNav />
      <RunHeader run={current} estimatedSeconds={estimatedSeconds} />
      {current.status === 'completed' && (
        <main className="max-w-screen-xl mx-auto px-6 lg:px-8 py-10 grid lg:grid-cols-[260px_1fr] gap-8 lg:gap-12 items-start">
          <TheDesk />
          <div>
            <TheCall verdict={current.verdict ?? null} />
            <RunHistoryPanel
              runCount={current.run_count}
              isContested={current.verdict_is_contested}
              history={historyQuery.data ?? null}
              isError={historyQuery.isError}
            />
            <ReportsRecord reports={current.reports ?? null} />
          </div>
        </main>
      )}
      <SiteFooter variant="research" />
    </>
  );
}
```

Reconcile the exact prop names/shapes above against what Tasks 8-10 actually produced (this plan was written before those tasks ran — if a component's real signature differs from what's sketched here, follow the real signature, don't force this snippet to match retroactively).

- [ ] **Step 3b: Delete the Task 9/10 shims**

Once `RunView.tsx` imports `TheCall` and `ReportsRecord` directly (Step 3 above), delete the now-unused re-export files and their stale test file:

```bash
git rm web/app/src/components/VerdictSummary.tsx web/app/src/components/ReportsAccordion.tsx
```

Check `web/app/tests/unit/components/VerdictSummary.test.tsx` — if Task 9 left it testing the old `VerdictSummary` re-export rather than migrating it to test `TheCall` under a new filename, move/rename it now so it isn't importing a component that no longer exists. Grep the whole `web/app/src` tree for any other stale `VerdictSummary`/`ReportsAccordion` references before moving on:

```bash
grep -rn "VerdictSummary\|ReportsAccordion" web/app/src web/app/tests
```

Expected: no hits outside `TheCall.tsx`/`ReportsRecord.tsx` themselves and whatever you renamed the test file to.

- [ ] **Step 4: Full verification pass**

```bash
cd web/app
npm run build
npx vitest run
npx playwright test
```

All must pass. This is the integration point where every prior task's work comes together on the two real routes (`/runs/[id]`, `/stock/[ticker]/[date]`) — if the E2E suite breaks here, it's telling you something about how the pieces fit together, not just about this task's own diff. Fix forward rather than weakening a selector to match a visual change, unless the visual change genuinely makes the old selector wrong (e.g. an `aria-label` intentionally changed) — in that case update the spec file to match the new, correct accessible name and say so in your report.

- [ ] **Step 5: Commit**

```bash
git add web/app/src/components/RunHistoryPanel.tsx web/app/src/components/RunView.tsx web/app/src/components/landing/SiteFooter.tsx
git commit -m "feat(web): reskin run history panel and assemble the full research page"
```

---

### Task 12: Light verification pass

**Files:** None new — this task runs and fixes, it doesn't add features.

**Scope:** Per this plan's explicit light-testing instruction — this is a regression sweep, not new coverage. Confirm the two product rules and the full existing suite; do not write new exhaustive tests.

- [ ] **Step 1: Full suite**

```bash
cd web/app
npm run build
npm run lint
npx vitest run
npx playwright test
```

- [ ] **Step 2: Confirm the two must-never-regress rules by reading the relevant code, not just trusting green tests**

- `formatPrice` is still the only path a price level reaches the DOM through in `TheCall` (Task 9) — grep for any raw `verdict.levels.entry_price`/`stop_loss` interpolation that bypassed it.
- `RunHistoryPanel`'s baseline-first contested logic (Task 11) is unchanged from the prior plan's fix-wave version — diff the props/logic (not markup) against `git show <prior-plan-final-commit>:web/app/src/components/RunHistoryPanel.tsx` to confirm only className/JSX structure moved, not the conditionals.

- [ ] **Step 3: Fix anything broken**

If the full suite isn't green, fix it now — this task doesn't close until it is. Do not defer failures to "the user will catch it manually" — light testing means fewer *new* tests, not tolerance for *known* breakage in the existing ones.

- [ ] **Step 4: Report**

Summarize what was ported in full vs. simplified (evidence trace, structured risk table, topic-by-topic ledger, per-agent live status — the four items this plan scoped out or reduced), so the user has an accurate picture of what's real vs. decorative-only before their own manual pass.

- [ ] **Step 5: Commit** (only if Step 3 required fixes; otherwise nothing to commit)

```bash
git add -A
git commit -m "fix(web): resolve regressions found in the design-integration verification pass"
```

---

## Self-Review Notes

- **Spec coverage:** Every functional island called out in the scope discussion (3 search form placements, verdict card, reports accordion, run-history panel, run-status banner, recent runs) has a task. Every decorative section of both reference files (nav, ticker, hero, trust strip, pipeline, use-cases, deck, live-split, FAQ, CTA, footer on landing; nav, run header, sidebar, footer on research) has a task. The four API-data-limited simplifications (evidence trace, risk table, bull/bear ledger, per-agent live status) are each explicitly named with the reasoning, not silently dropped.
- **Placeholder scan:** No TBD/TODO-as-a-cop-out. The plan's own `TODO(...)` mentions (legal disclaimer, wordmark placeholder) are carried over from the source file deliberately, per DESIGN.md's own instruction to keep them until real content exists — not placeholders in this plan's deliverables.
- **Type consistency:** `TheCall`, `ReportsRecord`, `RunHeader`, `TheDesk` prop shapes are sketched consistently with `RunView`'s existing `current: RunDetail` access patterns; `formatPrice`/`countWords`/`formatDuration` are each defined once (in `format.ts`) and reused across every task that needs them, not reimplemented per-component.
