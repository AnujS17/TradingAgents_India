import { Fragment } from 'react';

// Small evidence-visual primitives for TrustStrip's four argument cards.
// 2026-08-28, round 3 (design review: RSI number visually collided with
// the "was 76" ghost tick at small render size; the two number-driven
// cards needed a real percentage, not just a direction; the timeline
// needed its events visually valenced). Every added figure below is
// pulled straight from the real bull_case/bear_case text in
// api/fixtures/sample_run.json -- "adjusted PAT fell ~18-19% to
// ₹343 crore" and "operating cash flow collapsed from ₹1,655 crore to
// ₹375 crore" (a 77% YoY drop) are both real sentences from that file,
// not invented to match a percentage the user suggested as an example.
//
// RSI's gauge uses conventional oversold/neutral/overbought zone tinting
// (green/grey/red) -- a domain convention (every real charting platform
// colors RSI zones this way), used only inside that one gauge.
//
// The leadership-churn timeline is a SECOND, explicit extension of that
// same green/red-for-price-direction exception, requested directly this
// round: events are colored by their own real-world valence (a
// resignation is negative, a divestment is the company's own proactive
// move) using the exact colors already approved for rating/action
// (rating-color.ts's buy/sell -700 family), not new hexes. "New mgmt" is
// left neutral on purpose -- that event is the actual subject of the
// bull/bear disagreement on this card, and forcing a color onto it would
// silently pick a side the debate hasn't settled. Logged in DESIGN.md §1.

const NAVY = '#00439D';
const BEAR_BLUE = '#1B6FA8';
const AMBER_BG = '#FFF6E8';
const AMBER_TEXT = '#8A5A00';
const AMBER_BORDER = '#F3D9A8';
const INK = '#010101';
const MUTED = '#676D80';
const LINE = '#E0E1E2';
// Same -700 family already verified for the rating/action exception
// (rating-color.ts) -- reused here, not a new color introduced.
const POSITIVE = '#15803D';
const NEGATIVE = '#B91C1C';

function DownArrowBadge({ color = INK, size = 26 }: { color?: string; size?: number }) {
  return (
    <span
      className="rounded-full flex items-center justify-center shrink-0"
      style={{ width: size, height: size, backgroundColor: '#F1F2F5' }}
    >
      <svg width={size * 0.5} height={size * 0.5} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M6 7L17 18M17 18H9M17 18V10" stroke={color} strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

function TrendArrow({ direction, color, size = 12 }: { direction: 'up' | 'down'; color: string; size?: number }) {
  const d = direction === 'up' ? 'M6 17L17 6M17 6H9M17 6V14' : 'M6 7L17 18M17 18H9M17 18V10';
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d={d} stroke={color} strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ── RSI gauge (Technical analysis) ──────────────────────────────────
const GAUGE_W = 220;
const GAUGE_H = 100;
const GAUGE_CX = 110;
const GAUGE_CY = 92;
const GAUGE_R = 78;

function polar(angleDeg: number, r: number) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: GAUGE_CX + r * Math.cos(rad), y: GAUGE_CY - r * Math.sin(rad) };
}
// RSI 0..100 maps to the semicircle's 180deg (left) .. 0deg (right).
function angleForRsi(value: number) {
  return 180 - value * 1.8;
}
function zoneArc(rsiFrom: number, rsiTo: number, color: string) {
  const a1 = polar(angleForRsi(rsiFrom), GAUGE_R);
  const a2 = polar(angleForRsi(rsiTo), GAUGE_R);
  return <path key={color} d={`M ${a1.x} ${a1.y} A ${GAUGE_R} ${GAUGE_R} 0 0 1 ${a2.x} ${a2.y}`} stroke={color} strokeWidth="10" fill="none" strokeLinecap="round" />;
}

// Reverted 2026-08-28 to the plainer first-pass gauge (no OVERSOLD/
// OVERBOUGHT side labels) at the user's request. The number still sits
// BELOW the arc rather than inside it, though -- that repositioning was
// a bug fix (the ghost-tick and the number visually collided inside the
// small viewBox at render size), not a style choice, so it's kept.
export function RsiGauge({ from, to }: { from: number; to: number }) {
  const needle = polar(angleForRsi(to), GAUGE_R - 22);
  const ghost = polar(angleForRsi(from), GAUGE_R + 8);
  const ghostInner = polar(angleForRsi(from), GAUGE_R - 8);
  return (
    <div className="h-[92px] flex flex-col items-center justify-center gap-1">
      <svg viewBox={`0 0 ${GAUGE_W} ${GAUGE_H}`} className="h-[58px] w-auto" role="presentation" aria-hidden="true">
        {zoneArc(0, 30, '#A9D3AE')}
        {zoneArc(30, 70, '#DDDFE3')}
        {zoneArc(70, 100, '#EDA893')}
        {/* Ghost tick: where RSI was (76) before it cooled. */}
        <line x1={ghostInner.x} y1={ghostInner.y} x2={ghost.x} y2={ghost.y} stroke={MUTED} strokeWidth="2.5" opacity="0.6" />
        {/* Needle: where it is now (66). */}
        <line x1={GAUGE_CX} y1={GAUGE_CY} x2={needle.x} y2={needle.y} stroke={INK} strokeWidth="3" strokeLinecap="round" />
        <circle cx={GAUGE_CX} cy={GAUGE_CY} r="4.5" fill={INK} />
      </svg>
      <div className="flex items-baseline gap-1.5">
        <p className="font-tight text-xl font-black leading-none" style={{ color: INK }}>
          {to}
        </p>
        <p className="font-tight text-[10px] font-bold tracking-wide" style={{ color: MUTED }}>
          RSI · WAS {from}
        </p>
      </div>
    </div>
  );
}

// ── Cash reserve bar (The balance sheet) ────────────────────────────
// One relationship, not a pair to reconcile: a big, mostly-full reserve
// bar (the cash pile is real and large) directly above a small "burned
// this year" line (it isn't growing) -- read top-to-bottom as one
// sentence. The operating-cash-flow badge adds the real YoY percentage
// (₹1,655cr -> ₹375cr, a 77% drop, from the bear_case text) without
// competing with the two headline numbers above it.
export function CashReserveBar({
  reserveLabel,
  reserveFillPct,
  burnLabel,
  changeBadge,
}: {
  reserveLabel: string;
  reserveFillPct: number;
  burnLabel: string;
  changeBadge: string;
}) {
  return (
    <div className="h-[92px] flex flex-col justify-center gap-2.5">
      <div>
        <div className="h-3 w-full rounded-full overflow-hidden" style={{ backgroundColor: '#EAECF0' }}>
          <div className="h-full rounded-full" style={{ width: `${reserveFillPct}%`, backgroundColor: NAVY }} />
        </div>
        <p className="font-tight text-sm font-black mt-1.5" style={{ color: INK }}>
          {reserveLabel}
        </p>
      </div>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <DownArrowBadge size={22} />
          <p className="font-tight text-sm font-black" style={{ color: INK }}>
            {burnLabel}
          </p>
        </div>
        <span
          className="rounded-full border font-tight text-[9.5px] font-bold tracking-wide px-2 py-1 shrink-0 flex items-center gap-1"
          style={{ borderColor: LINE, color: NEGATIVE, backgroundColor: '#FEF2F2' }}
        >
          <TrendArrow direction="down" color={NEGATIVE} size={9} />
          {changeBadge}
        </span>
      </div>
    </div>
  );
}

// ── Profit-dip callout (The LVM gain) ───────────────────────────────
// One statement, one reason -- plain "Profit" instead of "adjusted PAT,"
// a single explanatory tag instead of a two-box reconciliation. The
// headline now carries the real decline percentage from the bear_case
// text ("adjusted PAT fell ~18-19% to ₹343 crore").
export function ProfitDipCallout({ headline, reasonTag }: { headline: string; reasonTag: string }) {
  return (
    <div className="h-[92px] flex flex-col items-center justify-center gap-2.5 text-center">
      <div className="flex items-center gap-2.5">
        <DownArrowBadge size={30} />
        <p className="font-tight text-xl font-black" style={{ color: INK }}>
          {headline}
        </p>
      </div>
      <span
        className="rounded-full border font-tight text-[10.5px] font-bold px-3 py-1"
        style={{ borderColor: AMBER_BORDER, backgroundColor: AMBER_BG, color: AMBER_TEXT }}
      >
        {reasonTag}
      </span>
    </div>
  );
}

// ── Event timeline (Leadership churn) ───────────────────────────────
export type TimelineStep = { label: string; tone: 'up' | 'down' | 'neutral' };

export function EventTimeline({ steps }: { steps: TimelineStep[] }) {
  return (
    <div className="h-[92px] flex items-center px-0.5">
      {steps.map((step, i) => {
        const isLast = i === steps.length - 1;
        const dotColor = step.tone === 'up' ? POSITIVE : step.tone === 'down' ? NEGATIVE : isLast ? BEAR_BLUE : NAVY;
        return (
          <Fragment key={step.label}>
            <div className="flex flex-col items-center gap-2 w-[62px] shrink-0">
              <span className="relative flex items-center justify-center w-3 h-3 shrink-0">
                <span
                  className="w-3 h-3 rounded-full border-2"
                  style={{ borderColor: dotColor, backgroundColor: step.tone === 'neutral' && !isLast ? '#fff' : dotColor }}
                />
                {step.tone !== 'neutral' && (
                  <span className="absolute -top-3.5">
                    <TrendArrow direction={step.tone} color={dotColor} size={11} />
                  </span>
                )}
              </span>
              <span className="font-tight text-[9px] font-bold text-center leading-tight" style={{ color: MUTED }}>
                {step.label}
              </span>
            </div>
            {!isLast && <span className="flex-1 h-[2px] -mt-[26px]" style={{ backgroundColor: LINE }} />}
          </Fragment>
        );
      })}
    </div>
  );
}
