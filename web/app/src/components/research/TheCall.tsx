import { Fragment } from 'react';
import Link from 'next/link';
import { downloadExport } from '@/lib/api-client/client';
import { formatPrice } from '@/lib/format';
import { ratingColor, DirectionArrow } from '@/lib/rating-color';
import type { Verdict } from '@/lib/api-client/client';

// Single glyph for both formats -- deliberate, not a placeholder: these are
// icon-only buttons distinguished by title/aria-label (a standard toolbar
// pattern), not two different pictograms competing for meaning next to a
// small "Complete" pill. See DESIGN.md §7's icon exception note for the
// same reasoning already applied to the push-notification bell.
const DOWNLOAD_ICON = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path
      d="M12 3v11m0 0l-4-4m4 4l4-4M5 19h14"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

// Two side-by-side panels -- the same visual idiom CompareCard.tsx's own
// `grid sm:grid-cols-2` layout uses for an actual comparison, so the icon
// reads as "compare" rather than needing a legend.
const COMPARE_ICON = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <rect x="3" y="4" width="8" height="16" rx="2" stroke="currentColor" strokeWidth="2.2" />
    <rect x="13" y="4" width="8" height="16" rx="2" stroke="currentColor" strokeWidth="2.2" />
  </svg>
);

// Ported from web/design/research/index.html lines 326-358 ("THE CALL").
// The source's "what the manager actually said" trace panel (lines 360-376)
// is out of scope here — that belongs to the evidence-trace work in a later
// task, not this verdict card.
//
// 2026-08-23: rating and action fields now carry real color (see
// src/lib/rating-color.ts for the scoped DESIGN.md §1 exception this
// implements — bull/bear framing elsewhere on the page is unaffected).

// The five ratings the engine can hand back, in ruler order (source line
// 345). Matched case-insensitively against `verdict.rating` so casing drift
// from the API doesn't silently fail to highlight anything.
const RATING_STOPS = ['Sell', 'Underweight', 'Hold', 'Overweight', 'Buy'] as const;

function ratingIndex(rating: string | null | undefined): number | null {
  if (!rating) return null;
  const index = RATING_STOPS.findIndex((stop) => stop.toLowerCase() === rating.toLowerCase());
  return index === -1 ? null : index;
}

export function TheCall({
  verdict,
  runId,
  compareHref = null,
}: {
  verdict: Verdict | null;
  runId: string;
  // The most recent OTHER completed run of the same question, computed by
  // RunView from the run-history query -- null when this is the only
  // completed run (nothing to compare against), in which case the button
  // doesn't render at all rather than linking to an empty compare page.
  compareHref?: string | null;
}) {
  if (!verdict) return null;

  // `levels = {}` is a compile-time-only safety net, not a real runtime case.
  // The backend's `Verdict.levels` uses `Field(default_factory=TradeLevels)`
  // (api/schemas.py), and Pydantic leaves default-factory fields out of the
  // JSON Schema `required` array — so the generated types mark it optional
  // even though every actual API response populates it.
  const { rating, time_horizon, levels = {}, price_target, current_price } = verdict;

  // Never fabricate a rating position: if `rating` is null or doesn't match
  // one of the five known stops, activeIndex stays null and nothing on the
  // ruler is highlighted.
  const activeIndex = ratingIndex(rating);
  const activeColor = ratingColor(rating);
  const actionColor = ratingColor(levels.action);

  const entryIsNull = levels.entry_price === null || levels.entry_price === undefined;
  const stopIsNull = levels.stop_loss === null || levels.stop_loss === undefined;
  const exitIsNull = price_target === null || price_target === undefined;
  // Only show the "blank field is a decision" copy when it's actually true
  // of at least one of the three fields it explains — don't caption fully
  // populated levels with an excuse that doesn't apply. current_price is
  // deliberately excluded: it's the real last close, not a decision, so its
  // absence (a vendor outage) isn't the same kind of blank and gets no
  // explanatory copy here.
  const showLevelsExplanation = entryIsNull || stopIsNull || exitIsNull;
  // Which fields are blank, and why, is now a function of the RATING
  // (api.service._extract_verdict enforces this backend-side) --
  // Overweight/Underweight are tactical adjustments to an EXISTING
  // position, not a fresh full trade, so only one of the three levels
  // means anything for each. A single Hold-only sentence used to cover
  // every blank-field case; it now has to match which rating produced it,
  // or a reader sees "nothing to size" next to a card that clearly has an
  // entry and a rating other than Hold.
  const levelsExplanation =
    rating === 'Overweight'
      ? 'Stop is blank for an Overweight — this is a tactical add to an existing position, not a fresh trade, so there is no new stop to protect; the risk sits on the core holding. Entry is where to add; exit is where the thesis expects price to go. A blank field is a decision, not a gap.'
      : rating === 'Underweight'
        ? 'Stop is blank for an Underweight — a position being reduced is not being protected, it is being reduced. Entry is the level to trim into; exit is where the thesis expects price to go. A blank field is a decision, not a gap.'
        : rating === 'Hold'
          ? 'Entry, stop and exit are blank for a Hold — there is no position being opened or added to, so there is nothing to size. A blank field is a decision, not a gap.'
          : 'Some levels are blank — see the full record below for why.';

  return (
    // aria-label is "Verdict summary", not the visible "The call" heading:
    // this is the pre-existing accessible name from the old placeholder
    // VerdictSummary (web/app/src/components/VerdictSummary.tsx, since
    // deleted), which three already-reviewed E2E specs
    // (search-to-result/cached-run/rate-limit.spec.ts) locate via
    // `page.getByLabel('Verdict summary')`. The design source
    // (web/design/research/index.html) has no aria-label on this section at
    // all, so there is no design intent being overridden here, and renaming
    // it to echo the visible h2 would be a redundant a11y label besides.
    <section id="call" aria-label="Verdict summary" className="rounded-[28px] border border-[#E0E1E2] bg-white p-7 lg:p-9">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-tight font-black text-[#010101] text-2xl tracking-[-0.02em]">The call</h2>
          <p className="copy text-[#6F6F6F] mt-1">The portfolio manager ruled after both debates closed.</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {/* One trigger, not two buttons: hovering (or, for keyboard/touch,
              focusing) reveals a small menu with both export formats. `group`
              scopes the CSS-only show/hide to this wrapper; `group-focus-within`
              is what makes it reachable without a mouse -- tabbing to either
              menu item keeps the menu open the same way hovering does. Both
              export routes require a bearer token now, which a plain <a href>
              navigation can't carry -- so these are buttons that call
              downloadExport (apiFetch under the hood) and trigger the save via
              a blob + synthetic <a download>, not a direct navigation. */}
          <div className="relative group">
            <button
              type="button"
              title="Export"
              aria-label="Export"
              aria-haspopup="true"
              className="w-9 h-9 rounded-full border border-[#E0E1E2] text-[#676D80] flex items-center justify-center hover:border-[#1C6FE6] hover:text-[#1C6FE6] group-focus-within:border-[#1C6FE6] group-focus-within:text-[#1C6FE6] transition-colors"
            >
              {DOWNLOAD_ICON}
            </button>
            <div
              role="menu"
              aria-label="Export"
              className="absolute right-0 top-full mt-1.5 z-10 w-44 rounded-2xl border border-[#E0E1E2] bg-white shadow-lg py-1.5 opacity-0 invisible -translate-y-1 pointer-events-none transition-all duration-150 group-hover:opacity-100 group-hover:visible group-hover:translate-y-0 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:visible group-focus-within:translate-y-0 group-focus-within:pointer-events-auto"
            >
              <button
                type="button"
                role="menuitem"
                onClick={() => downloadExport(runId, 'pdf')}
                className="block w-full text-left px-4 py-2 font-tight font-semibold text-sm text-[#010101] hover:bg-[#F5F6F8]"
              >
                Export as PDF
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => downloadExport(runId, 'xlsx')}
                className="block w-full text-left px-4 py-2 font-tight font-semibold text-sm text-[#010101] hover:bg-[#F5F6F8]"
              >
                Export as Excel
              </button>
            </div>
          </div>
          {/* Right of download, per the layout this replaces: a pick-two
              checkbox section used to live in RunHistoryPanel; now it's this
              one-click default (current run vs. the most recent other
              completed run of the same question) instead of a whole section
              dedicated to comparison. Absent entirely when there's nothing
              to compare against (compareHref is null). */}
          {compareHref && (
            <Link
              href={compareHref}
              title="Compare with previous run"
              aria-label="Compare with previous run"
              className="w-9 h-9 rounded-full border border-[#E0E1E2] text-[#676D80] flex items-center justify-center hover:border-[#1C6FE6] hover:text-[#1C6FE6] transition-colors"
            >
              {COMPARE_ICON}
            </Link>
          )}
          <span className="font-tight font-bold text-xs rounded-full bg-[#F0F6FF] text-[#00439D] border border-[#D3E1F7] px-3.5 py-2">
            Complete
          </span>
        </div>
      </div>

      {/* The prominent verdict: large, colored, shape-coded (an arrow, not
          just a hue) so the rating is legible at a glance, not just present
          on a small ruler dot further down. This is the answer to "what did
          they decide" — it comes before the ruler that explains it. */}
      <div
        className="mt-6 rounded-2xl border flex items-center gap-4 px-5 py-4"
        style={{ backgroundColor: activeColor.bg, borderColor: activeColor.border }}
      >
        <span
          className="w-10 h-10 rounded-full flex items-center justify-center shrink-0"
          style={{ backgroundColor: activeColor.text, color: '#fff' }}
        >
          <DirectionArrow direction={activeColor.direction} />
        </span>
        <div>
          <p className="font-tight text-[11px] font-bold tracking-wide" style={{ color: activeColor.text }}>
            RATING
          </p>
          <p
            className="font-tight font-black text-2xl sm:text-3xl tracking-[-0.02em] leading-none mt-0.5"
            style={{ color: activeColor.text }}
          >
            {rating ?? 'Not set'}
          </p>
        </div>
      </div>

      {activeIndex === null ? null : (
        <div className="mt-6">
          {/* A flat flex row of alternating dot/line siblings, not a
              grid-cols-5 of five independent dot+line pairs (the previous
              shape): grid-cols-5 gave each stop its own column and confined
              that stop's trailing line to the SAME column, so the line
              between Overweight and Buy never reached past Overweight's own
              column -- the ruler visually stopped 1/5 short of the right
              edge, with the Buy dot sitting at the 80% mark instead of 100%.
              Flattening to one row of dots (shrink-0) and connecting lines
              (flex-1) as direct siblings makes each line span the ACTUAL gap
              between its two neighbouring dots, so the first dot's left edge
              and the last dot's right edge land on the container's own
              edges -- Fragment (not a wrapping div) is what makes each
              stop's dot and line become true siblings of the row instead of
              nesting one level deeper, which is what reintroduces the same
              per-stop-column bug this replaces. */}
          <div className="flex items-center">
            {RATING_STOPS.map((stop, index) => {
              const isActive = index === activeIndex;
              const stopColor = ratingColor(stop);
              return (
                <Fragment key={stop}>
                  <span
                    className="rounded-full shrink-0"
                    style={
                      isActive
                        ? {
                            height: '1rem',
                            width: '1rem',
                            backgroundColor: stopColor.text,
                            boxShadow: `0 0 0 4px ${stopColor.bg}, 0 0 0 5px ${stopColor.border}`,
                          }
                        : { height: '.75rem', width: '.75rem', backgroundColor: '#EBEBEB' }
                    }
                  />
                  {/* Always gradient, regardless of activeIndex: this is a fixed
                      5-point rating scale, not a progress bar, so Sell..Buy all
                      exist simultaneously — nothing here is "not reached yet."
                      The dot is the only thing that should mark position; a
                      track that fades to grey past the active stop reads as
                      "how far along," which is the wrong metaphor for a rating. */}
                  {index < RATING_STOPS.length - 1 && (
                    <span
                      className="h-1.5 flex-1"
                      style={{
                        background: `linear-gradient(90deg, ${ratingColor(RATING_STOPS[index]).text}55, ${ratingColor(RATING_STOPS[index + 1]).text}55)`,
                      }}
                    />
                  )}
                </Fragment>
              );
            })}
          </div>
          {/* justify-between, matching the dot row above: the first label
              sits flush left (under the Sell dot) and the last sits flush
              right (under the Buy dot, now that it actually reaches the
              edge), with the middle three evenly spaced between -- the same
              alignment logic as the dot row, kept as two separate rows
              (rather than labels under a single merged row) so the label
              text can wrap/hide independently below the sm breakpoint.
              Hidden below sm: "UNDERWEIGHT"/"OVERWEIGHT" at 11px don't fit a
              fifth of a mobile-width card without colliding into their
              neighbours (verified: they visibly overlapped at 390px). The
              big colored rating badge above already states the active
              rating in full, clear text — the dots-and-track ruler above
              this row still shows position at every width; this label row
              is the part that's genuinely redundant once the badge exists,
              so it's what gives way. */}
          <div className="hidden sm:flex justify-between mt-2.5 font-tight text-[11px] font-bold tracking-wide">
            {RATING_STOPS.map((stop, index) => (
              <span key={stop} style={{ color: index === activeIndex ? ratingColor(stop).text : '#676D80' }}>
                {stop.toUpperCase()}
              </span>
            ))}
          </div>
        </div>
      )}

      <dl className="grid sm:grid-cols-3 lg:grid-cols-6 gap-px bg-[#EBEBEB] rounded-2xl overflow-hidden mt-7">
        <div className="bg-white p-4">
          <dt className="font-tight text-[11px] font-bold tracking-wide text-[#676D80]">CURRENT PRICE</dt>
          <dd className="font-tight font-extrabold text-[#010101] text-lg mt-1">{formatPrice(current_price)}</dd>
        </div>
        <div className="p-4" style={{ backgroundColor: levels.action ? actionColor.bg : '#fff' }}>
          <dt className="font-tight text-[11px] font-bold tracking-wide text-[#676D80]">ACTION</dt>
          <dd
            className="font-tight font-extrabold text-lg mt-1"
            style={{ color: levels.action ? actionColor.text : '#010101' }}
          >
            {levels.action ?? 'Not set'}
          </dd>
        </div>
        <div className="bg-white p-4">
          {/* For a trim the execution level is a SELL, so "Entry" reads
              backwards. Same field, direction-correct label. */}
          <dt className="font-tight text-[11px] font-bold tracking-wide text-[#676D80]">
            {rating === 'Underweight' || rating === 'Sell' ? 'TRIM AT' : 'ENTRY'}
          </dt>
          <dd className="font-tight font-semibold text-[#676D80] text-lg mt-1">{formatPrice(levels.entry_price)}</dd>
        </div>
        <div className="bg-white p-4">
          <dt className="font-tight text-[11px] font-bold tracking-wide text-[#676D80]">STOP</dt>
          <dd className="font-tight font-semibold text-[#676D80] text-lg mt-1">{formatPrice(levels.stop_loss)}</dd>
        </div>
        <div className="bg-white p-4">
          <dt className="font-tight text-[11px] font-bold tracking-wide text-[#676D80]">EXIT</dt>
          <dd className="font-tight font-semibold text-[#676D80] text-lg mt-1">{formatPrice(price_target)}</dd>
        </div>
        <div className="bg-white p-4">
          <dt className="font-tight text-[11px] font-bold tracking-wide text-[#676D80]">HORIZON</dt>
          <dd className="font-tight font-extrabold text-[#010101] text-lg mt-1">{time_horizon ?? 'Not set'}</dd>
        </div>
      </dl>

      {showLevelsExplanation && (
        <p className="copy text-[#6F6F6F] mt-4 measure">{levelsExplanation}</p>
      )}
    </section>
  );
}
