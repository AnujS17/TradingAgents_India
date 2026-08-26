import { formatPrice } from '@/lib/format';
import { ratingColor, DirectionArrow } from '@/lib/rating-color';
import type { Verdict } from '@/lib/api-client/client';

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

export function TheCall({ verdict }: { verdict: Verdict | null }) {
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
        <span className="font-tight font-bold text-xs rounded-full bg-[#F0F6FF] text-[#00439D] border border-[#D3E1F7] px-3.5 py-2 shrink-0">
          Complete
        </span>
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
          <div className="grid grid-cols-5 items-center">
            {RATING_STOPS.map((stop, index) => {
              const isActive = index === activeIndex;
              const stopColor = ratingColor(stop);
              return (
                <div className="flex items-center" key={stop}>
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
                  {index < RATING_STOPS.length - 1 && (
                    <span
                      className="h-1.5 flex-1"
                      style={{
                        background:
                          index < activeIndex
                            ? `linear-gradient(90deg, ${ratingColor(RATING_STOPS[index]).text}55, ${ratingColor(RATING_STOPS[index + 1]).text}55)`
                            : '#EBEBEB',
                      }}
                    />
                  )}
                </div>
              );
            })}
          </div>
          {/* Hidden below sm: "UNDERWEIGHT"/"OVERWEIGHT" at 11px don't fit a
              fifth of a mobile-width card without colliding into their
              neighbours (verified: they visibly overlapped at 390px). The
              big colored rating badge above already states the active
              rating in full, clear text — the dots-and-track ruler above
              this row still shows position at every width; this label row
              is the part that's genuinely redundant once the badge exists,
              so it's what gives way. */}
          <div className="hidden sm:grid grid-cols-5 mt-2.5 font-tight text-[11px] font-bold tracking-wide">
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
          <dt className="font-tight text-[11px] font-bold tracking-wide text-[#676D80]">ENTRY</dt>
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
        <p className="copy text-[#6F6F6F] mt-4 measure">
          Entry, stop and exit are blank for a Hold — there is no position being opened or added to, so there is
          nothing to size. A blank field is a decision, not a gap.
        </p>
      )}
    </section>
  );
}
