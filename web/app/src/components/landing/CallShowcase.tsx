// Dark-glossy showcase card, visually in the language of Deck.tsx (same
// section reuses .deck-card's glass/shadow vocabulary via
// .call-showcase-card, same rgba(255,255,255,.09) floating-chip device as
// Deck's .viz-chip). Built 2026-08-28 after an explicit decision NOT to
// build a fabricated "stock added/removed, +189%" realized-return card
// (the original reference): that format asserts a tracked historical
// result this product doesn't have, in any styling.
//
// Restyled 2026-08-28, round 3: pushed the styling itself much closer to
// that reference -- a more dramatic 3D tilt, a richer multi-stop glow
// fill, a glossy diagonal sheen, a glowing hero number, and thin
// connector "flagpoles" from each Stop/Entry/Target dot up to its pill,
// echoing the reference's speech-bubble annotation lines. What's
// deliberately NOT copied: the reference's jagged, high-frequency zigzag
// line. That texture specifically reads as real tick-by-tick price
// history; recreating it for a real, named stock (HAL.NS) would fabricate
// granular price data the same way a fake percentage would, just less
// obviously. The curve stays a smooth, clearly-schematic 3-point line —
// smoothness is doing real work here, not a missed detail.
//
// Every badge is a real Indian-market call from a real completed run
// this session (HAL, SENORES, SCHAEFFLER, all Overweight/Buy), and every
// percentage is that call's own stated target's upside from its own
// stated entry -- forward-looking arithmetic on real numbers, computed
// at render time, not invented. Each floating badge says "target" inline
// so it still reads honestly even seen on its own, out of context.

type Call = {
  ticker: string;
  entry: number;
  stop: number;
  target: number;
  current: number;
  rating: string;
  action: string;
  date: string;
};

// Real completed runs, same fixtures already used elsewhere on this site
// (HAL.NS is the same run TheCall.tsx/PricePathChart.tsx showcase on the
// research page).
const HERO: Call = { ticker: 'HAL.NS', entry: 4625, stop: 4355, target: 5099, current: 4865.5, rating: 'Overweight', action: 'Buy', date: '27 Aug 2026' };
const MOVERS: Call[] = [
  { ticker: 'SENORES', entry: 1410, stop: 1150, target: 1550, current: 1410, rating: 'Overweight', action: 'Buy', date: '26 Aug 2026' },
  { ticker: 'SCHAEFFLER', entry: 4047, stop: 3970, target: 4280, current: 4047, rating: 'Overweight', action: 'Buy', date: '26 Aug 2026' },
];

function upside(call: Call) {
  return (((call.target - call.entry) / call.entry) * 100).toFixed(1);
}

const VIEW_W = 360;
const VIEW_H = 130;
const X_STOP = 40;
const X_MID = 180;
const X_TARGET = 320;
const Y_TOP = 26;
const Y_BOTTOM = 96;

function yFor(value: number, lo: number, hi: number) {
  const t = (value - lo) / (hi - lo);
  return Y_BOTTOM - t * (Y_BOTTOM - Y_TOP);
}

export function CallShowcase() {
  const yStop = yFor(HERO.stop, HERO.stop, HERO.target);
  const yMid = yFor(HERO.current, HERO.stop, HERO.target);
  const yTarget = yFor(HERO.target, HERO.stop, HERO.target);
  const path = `M ${X_STOP} ${yStop} Q ${X_MID} ${yMid + (yStop - yMid) * 0.3} ${X_MID} ${yMid} T ${X_TARGET} ${yTarget}`;

  return (
    <section className="bg-[#050A18] relative overflow-hidden">
      <div aria-hidden="true" className="absolute inset-0 opacity-40" style={{ background: 'radial-gradient(600px 300px at 20% 0%, rgba(28,111,230,.25), transparent)' }} />
      <div className="max-w-screen-xl mx-auto px-6 lg:px-8 py-16 lg:py-20 relative">
        <div className="max-w-2xl">
          <h2 className="font-tight font-black text-white text-4xl sm:text-5xl leading-[1.02] tracking-[-0.025em]">
            Not just a rating. A real plan.
          </h2>
          <p className="mt-3 text-[15px]" style={{ color: 'rgba(255,255,255,.58)' }}>
            Every call ships with a stated entry, stop, and target — not a bare buy or sell label.
            Here is a real one, and two more from the same week.
          </p>
        </div>

        <div className="mt-14 call-showcase-wrap">
          <div className="call-showcase-movers">
            {MOVERS.map((call) => (
              <span key={call.ticker} className="call-showcase-mover">
                <span className="call-showcase-mover__ticker">{call.ticker}</span>
                <span className="call-showcase-mover__pct">+{upside(call)}% target</span>
              </span>
            ))}
          </div>

          <div className="call-showcase-frame">
            <div className="call-showcase-card">
              <div className="call-showcase-sheen" aria-hidden="true" />
              <div className="flex items-center justify-between relative">
                <div>
                  <p className="font-tight font-black text-white text-lg">{HERO.ticker}</p>
                  <p className="font-tight text-[11px] font-bold tracking-wide" style={{ color: 'rgba(255,255,255,.5)' }}>
                    {HERO.rating.toUpperCase()} · {HERO.action.toUpperCase()}
                  </p>
                </div>
                <span className="call-showcase-tag">Real call, {HERO.date}</span>
              </div>

              <div className="mt-5 relative flex items-center gap-2">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="shrink-0">
                  <path d="M6 17L17 6M17 6H9M17 6V14" stroke="#7FC4FF" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <p className="call-showcase-hero-pct">+{upside(HERO)}%</p>
              </div>
              <p className="font-tight text-[11px] font-bold tracking-wide mt-1 relative" style={{ color: 'rgba(255,255,255,.5)' }}>
                TARGET vs. ENTRY — NOT YET REALIZED
              </p>

              <div className="relative mt-7">
                <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} className="w-full h-auto" role="presentation" aria-hidden="true">
                  <defs>
                    <linearGradient id="csFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#7FC4FF" stopOpacity="0.55" />
                      <stop offset="45%" stopColor="#1C6FE6" stopOpacity="0.28" />
                      <stop offset="100%" stopColor="#1C6FE6" stopOpacity="0" />
                    </linearGradient>
                    <linearGradient id="csStroke" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor="#3DA2F1" />
                      <stop offset="100%" stopColor="#B9E1FF" />
                    </linearGradient>
                    <filter id="csGlow" x="-30%" y="-30%" width="160%" height="160%">
                      <feGaussianBlur stdDeviation="3.2" result="blur" />
                      <feMerge>
                        <feMergeNode in="blur" />
                        <feMergeNode in="SourceGraphic" />
                      </feMerge>
                    </filter>
                  </defs>
                  <path d={`${path} L ${X_TARGET} ${VIEW_H} L ${X_STOP} ${VIEW_H} Z`} fill="url(#csFill)" />
                  <path d={path} fill="none" stroke="url(#csStroke)" strokeWidth="3" strokeLinecap="round" filter="url(#csGlow)" />

                  {/* Flagpole connectors — thin lines from each dot up to its
                      pill, echoing the reference's speech-bubble tails. */}
                  <line x1={X_STOP} y1={yStop - 6} x2={X_STOP} y2={20} stroke="rgba(255,255,255,.3)" strokeWidth="1.5" strokeDasharray="1 3" />
                  <line x1={X_MID} y1={yMid - 6} x2={X_MID} y2={20} stroke="rgba(255,255,255,.3)" strokeWidth="1.5" strokeDasharray="1 3" />
                  <line x1={X_TARGET} y1={yTarget - 6} x2={X_TARGET} y2={20} stroke="rgba(255,255,255,.3)" strokeWidth="1.5" strokeDasharray="1 3" />

                  <circle cx={X_STOP} cy={yStop} r="4" fill="#0A1226" stroke="rgba(255,255,255,.5)" strokeWidth="1.5" />
                  <circle cx={X_MID} cy={yMid} r="4.5" fill="#fff" />
                  <circle cx={X_TARGET} cy={yTarget} r="4" fill="#7FC4FF" />
                </svg>

                <span className="call-showcase-tag call-showcase-tag--float" style={{ left: '2%', top: '3%' }}>
                  Stop ₹{HERO.stop.toLocaleString('en-IN')}
                </span>
                <span className="call-showcase-tag call-showcase-tag--float" style={{ left: '38%', top: '3%' }}>
                  Entry ₹{HERO.entry.toLocaleString('en-IN')}
                </span>
                <span className="call-showcase-tag call-showcase-tag--float" style={{ right: '0%', top: '3%' }}>
                  Target ₹{HERO.target.toLocaleString('en-IN')}
                </span>
              </div>

              <p className="text-[13px] leading-relaxed mt-6 relative" style={{ color: 'rgba(255,255,255,.55)' }}>
                This is the trade plan a real, completed {HERO.ticker} analysis actually stated — the
                target is what the call aims for, not a return it has already delivered.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
