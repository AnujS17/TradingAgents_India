import { formatPrice } from '@/lib/format';
import type { Verdict } from '@/lib/api-client/client';

// Ported from web/design/research/index.html lines 326-358 ("THE CALL").
// The source's "what the manager actually said" trace panel (lines 360-376)
// is out of scope here — that belongs to the evidence-trace work in a later
// task, not this verdict card.

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
  const { rating, time_horizon, levels = {} } = verdict;

  // Never fabricate a rating position: if `rating` is null or doesn't match
  // one of the five known stops, activeIndex stays null and nothing on the
  // ruler is highlighted.
  const activeIndex = ratingIndex(rating);

  const entryIsNull = levels.entry_price === null || levels.entry_price === undefined;
  const stopIsNull = levels.stop_loss === null || levels.stop_loss === undefined;
  // Only show the "blank field is a decision" copy when it's actually true
  // of at least one of the two fields it explains — don't caption fully
  // populated levels with an excuse that doesn't apply.
  const showLevelsExplanation = entryIsNull || stopIsNull;

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
        <span className="font-tight font-bold text-xs rounded-full bg-[#F0F6FF] text-[#00439D] border border-[#D3E1F7] px-3.5 py-2">
          Complete
        </span>
      </div>

      {activeIndex === null ? (
        <p className="font-tight font-bold text-[#676D80] text-sm mt-7">Rating: Not set</p>
      ) : (
        <div className="mt-7">
          <div className="grid grid-cols-5 items-center">
            {RATING_STOPS.map((stop, index) => {
              const isActive = index === activeIndex;
              return (
                <div className="flex items-center" key={stop}>
                  <span
                    className={
                      isActive
                        ? 'h-4 w-4 rounded-full bg-[#00439D] ring-4 ring-[#00439D]/15 shrink-0'
                        : 'h-3 w-3 rounded-full bg-[#EBEBEB] shrink-0'
                    }
                  />
                  {index < RATING_STOPS.length - 1 && <span className="h-1.5 flex-1 bg-[#EBEBEB]" />}
                </div>
              );
            })}
          </div>
          <div className="grid grid-cols-5 mt-2.5 font-tight text-[11px] font-bold tracking-wide text-[#676D80]">
            {RATING_STOPS.map((stop, index) => (
              <span key={stop} className={index === activeIndex ? 'text-[#00439D]' : undefined}>
                {stop.toUpperCase()}
              </span>
            ))}
          </div>
        </div>
      )}

      <dl className="grid sm:grid-cols-4 gap-px bg-[#EBEBEB] rounded-2xl overflow-hidden mt-7">
        <div className="bg-white p-4">
          <dt className="font-tight text-[11px] font-bold tracking-wide text-[#676D80]">ACTION</dt>
          <dd className="font-tight font-extrabold text-[#010101] text-lg mt-1">{levels.action ?? 'Not set'}</dd>
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
          <dt className="font-tight text-[11px] font-bold tracking-wide text-[#676D80]">HORIZON</dt>
          <dd className="font-tight font-extrabold text-[#010101] text-lg mt-1">{time_horizon ?? 'Not set'}</dd>
        </div>
      </dl>

      {showLevelsExplanation && (
        <p className="copy text-[#6F6F6F] mt-4 measure">
          Entry and stop are blank because the evidence does not support a number yet. A blank field is a decision, not
          a gap.
        </p>
      )}
    </section>
  );
}
