// Ported from web/design/landing-fintech/index.html lines 698-903 (the
// "PIPELINE STACK" section, id="how"): the sticky card stack DESIGN.md §5
// documents. Four `.stack-card` articles pin at stepped `top` offsets
// (`--navh + var(--i) * var(--strip)`, set via the `--i` inline custom
// property on each <article>, exactly as in the source) so they visually
// pile up as the reader scrolls past them.
//
// The `--strip`/`--navh`/`top` values and the two responsive overrides
// (short-laptop `--strip: 50px` and the <1024px static fallback) are copied
// verbatim into globals.css from source lines 280-372, not re-derived — see
// the comment there. DESIGN.md's two structural constraints
// (`--strip` > padding-top + label height; `nav + (n-1)*strip + cardHeight`
// fits the viewport) were already satisfied by those numbers in the source.
//
// This section has no ancestor with `overflow: hidden` — body already uses
// `overflow-x: clip` (globals.css) per DESIGN.md's sticky-positioning rule,
// and nothing here re-adds a clipping ancestor between <body> and the
// `.stack-card` elements.
//
// No scroll-reveal here: the source's pipeline-stack cards don't carry
// `.u-reveal`, only the sticky-pin motion itself.
export function PipelineStack() {
  return (
    <section id="how" className="bg-[#F7F8FB] border-y border-[#EBEBEB]">
      <div className="max-w-screen-xl mx-auto px-6 lg:px-8 pt-20 lg:pt-24 pb-10">
        <h2 className="stack-head font-tight font-black text-[#010101]">
          Twelve agents. Five teams.
          <br />
          One committee decision.
        </h2>
        <p className="text-[#5C6070] mt-5 text-lg max-w-xl leading-relaxed">
          Each team finishes its work before the next one starts. Scroll to follow a single stock
          all the way through.
        </p>
      </div>

      <div className="stack-wrap max-w-screen-xl mx-auto px-6 lg:px-8 pb-24">
        {/* 1 · ANALYSTS */}
        <article className="stack-card" style={{ ['--i' as string]: '0' }}>
          <p className="stack-label">Analysts</p>
          <div className="stack-art">
            <svg
              viewBox="0 0 340 420"
              role="img"
              aria-label="Four analyst reports arriving for SIEMENS, each with its own reading"
            >
              <rect x="0" y="0" width="340" height="420" rx="26" fill="#0E1730" />
              <rect x="14" y="14" width="312" height="392" rx="18" fill="#fff" />
              <text x="34" y="48" className="s-mut">Four analysts reading</text>
              <text x="34" y="72" className="s-tick">SIEMENS.NS</text>

              <rect x="30" y="90" width="280" height="70" rx="12" fill="#F4F6FB" stroke="#E4E8F2" />
              <text x="44" y="112" className="s-lbl">Market</text>
              <text x="44" y="136" className="s-val">RSI 61 · above 200-DMA</text>
              <g stroke="#1C6FE6" strokeWidth="3.4" strokeLinecap="round">
                <path d="M232 140V116" />
                <path d="M248 140V124" />
                <path d="M264 140V108" />
                <path d="M280 140V128" />
                <path d="M296 140V118" />
              </g>

              <rect x="30" y="170" width="280" height="70" rx="12" fill="#F4F6FB" stroke="#E4E8F2" />
              <text x="44" y="192" className="s-lbl">Fundamentals</text>
              <text x="44" y="216" className="s-val">Margin 9.8%, third fall</text>
              <g fill="#237FFB">
                <rect x="236" y="204" width="12" height="14" rx="3" />
                <rect x="254" y="196" width="12" height="22" rx="3" />
                <rect x="272" y="208" width="12" height="10" rx="3" />
                <rect x="290" y="190" width="12" height="28" rx="3" />
              </g>

              <rect x="30" y="250" width="280" height="70" rx="12" fill="#F4F6FB" stroke="#E4E8F2" />
              <text x="44" y="272" className="s-lbl">News</text>
              <text x="44" y="296" className="s-val">4 filings, 12 articles</text>
              <circle cx="286" cy="286" r="15" fill="#E7F0FE" />
              <path d="M279 286h14M286 279v14" stroke="#1C6FE6" strokeWidth="2.6" strokeLinecap="round" />

              <rect x="30" y="330" width="280" height="58" rx="12" fill="#F4F6FB" stroke="#E4E8F2" />
              <text x="44" y="352" className="s-lbl">Sentiment</text>
              <text x="44" y="374" className="s-val">Retail mildly negative</text>
            </svg>
          </div>
          <div className="stack-copy">
            <h3 className="stack-title">Four specialists read the company at the same time</h3>
            <ul className="stack-list">
              <li>Price, volume and momentum</li>
              <li>Statements, ratios and promoter dealings</li>
              <li>Exchange filings, news and retail chatter</li>
            </ul>
            <p className="stack-note">None of them sees another&apos;s report. That comes next.</p>
          </div>
        </article>

        {/* 2 · RESEARCHERS */}
        <article className="stack-card" style={{ ['--i' as string]: '1' }}>
          <p className="stack-label">Researchers</p>
          <div className="stack-art">
            <svg
              viewBox="0 0 340 420"
              role="img"
              aria-label="A bull and a bear reading the same order-book figure in opposite directions"
            >
              <rect x="0" y="0" width="340" height="420" rx="26" fill="#0E1730" />
              <rect x="14" y="14" width="312" height="392" rx="18" fill="#fff" />
              <text x="34" y="48" className="s-mut">Both sides cite</text>
              <text x="34" y="76" className="s-fig">₹1,240cr</text>
              <text x="34" y="96" className="s-mut">order book, Q1</text>

              <path d="M170 118v210" stroke="#C9D6EE" strokeWidth="1.5" strokeDasharray="4 5" />

              <rect x="30" y="118" width="128" height="104" rx="12" fill="#EEF3FE" stroke="#1C6FE6" />
              <text x="44" y="142" className="s-lbl" fill="#00439D">Bull</text>
              <text x="44" y="166" className="s-sml">Up 18% on</text>
              <text x="44" y="184" className="s-sml">last year.</text>
              <text x="44" y="202" className="s-sml">Demand is fine.</text>

              <rect x="182" y="118" width="128" height="104" rx="12" fill="#F2FAFF" stroke="#3DA2F1" />
              <text x="196" y="142" className="s-lbl" fill="#1B6FA8">Bear</text>
              <text x="196" y="166" className="s-sml">Same book,</text>
              <text x="196" y="184" className="s-sml">margin still</text>
              <text x="196" y="202" className="s-sml">fell again.</text>

              <path d="M112 244h116" stroke="#00439D" strokeWidth="2.6" strokeLinecap="round" />
              <path
                d="M220 238l8 6-8 6"
                stroke="#00439D"
                strokeWidth="2.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path d="M228 268H112" stroke="#3DA2F1" strokeWidth="2.6" strokeLinecap="round" />
              <path
                d="M120 262l-8 6 8 6"
                stroke="#3DA2F1"
                strokeWidth="2.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />

              <rect x="30" y="296" width="280" height="92" rx="14" fill="#0E1730" />
              <text x="48" y="326" className="s-lbl" fill="#7FC4FF">The manager rules</text>
              <text x="48" y="352" className="s-white">Bear wins on margins.</text>
              <text x="48" y="374" className="s-white">Trim, do not exit.</text>
            </svg>
          </div>
          <div className="stack-copy">
            <h3 className="stack-title">A bull and a bear argue over the very same numbers</h3>
            <ul className="stack-list">
              <li>The bull builds the case to buy</li>
              <li>The bear answers that case, line by line</li>
              <li>A manager reads both and says who won</li>
            </ul>
            <p className="stack-note">Same evidence on both desks, so a split tells you something real.</p>
          </div>
        </article>

        {/* 3 · TRADER & RISK */}
        <article className="stack-card" style={{ ['--i' as string]: '2' }}>
          <p className="stack-label">Trader &amp; risk</p>
          <div className="stack-art">
            <svg
              viewBox="0 0 340 420"
              role="img"
              aria-label="A trade plan being pushed in three directions by aggressive, neutral and cautious analysts"
            >
              <rect x="0" y="0" width="340" height="420" rx="26" fill="#0E1730" />
              <rect x="14" y="14" width="312" height="392" rx="18" fill="#fff" />
              <text x="34" y="48" className="s-mut">The trader proposes</text>

              <rect x="30" y="62" width="280" height="86" rx="14" fill="#0E1730" />
              <text x="48" y="90" className="s-white-lg">Hold</text>
              <text x="48" y="114" className="s-dim">Entry —</text>
              <text x="140" y="114" className="s-dim">Stop —</text>
              <text x="48" y="134" className="s-dim">Trim into strength</text>

              <path
                d="M170 156v20M62 176h216M62 176v16M170 176v16M278 176v16"
                stroke="#D7DEEC"
                strokeWidth="2"
              />

              <rect x="30" y="196" width="86" height="118" rx="12" fill="#fff" stroke="#1C6FE6" />
              <text x="44" y="220" className="s-tiny" fill="#1C6FE6">Aggressive</text>
              <path
                d="M46 288l16-26 14 12 16-30"
                stroke="#1C6FE6"
                strokeWidth="3.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <text x="44" y="252" className="s-sml">Add here</text>

              <rect x="127" y="196" width="86" height="118" rx="12" fill="#fff" stroke="#237FFB" />
              <text x="141" y="220" className="s-tiny" fill="#237FFB">Neutral</text>
              <text x="141" y="252" className="s-sml">Hold size</text>
              <path d="M143 284h54M143 298h32" stroke="#237FFB" strokeWidth="3.2" strokeLinecap="round" />

              <rect x="224" y="196" width="86" height="118" rx="12" fill="#fff" stroke="#3DA2F1" />
              <text x="238" y="220" className="s-tiny" fill="#1B6FA8">Cautious</text>
              <text x="238" y="252" className="s-sml">Cut first</text>
              <path
                d="M240 272l16 24 16-20"
                stroke="#3DA2F1"
                strokeWidth="3.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />

              <rect x="30" y="330" width="280" height="56" rx="12" fill="#EEF3FE" stroke="#C9D9F7" />
              <text x="48" y="354" className="s-lbl" fill="#00439D">Survived review</text>
              <text x="48" y="374" className="s-sml">Size cut, stop left blank</text>
            </svg>
          </div>
          <div className="stack-copy">
            <h3 className="stack-title">The plan gets pushed in three directions before it counts</h3>
            <ul className="stack-list">
              <li>A trader turns the call into something you could act on</li>
              <li>Three analysts attack it: bold, middle and cautious</li>
              <li>Only what survives all three carries forward</li>
            </ul>
            <p className="stack-note">They argue with the plan, not with the company.</p>
          </div>
        </article>

        {/* 4 · PORTFOLIO MANAGER */}
        <article className="stack-card" style={{ ['--i' as string]: '3' }}>
          <p className="stack-label">Portfolio manager</p>
          <div className="stack-art">
            <svg
              viewBox="0 0 340 420"
              role="img"
              aria-label="Final verdict screen showing a Hold rating with entry and stop left blank"
            >
              <rect x="0" y="0" width="340" height="420" rx="26" fill="#0E1730" />
              <rect x="14" y="14" width="312" height="392" rx="18" fill="#fff" />
              <text x="34" y="48" className="s-mut">Final call</text>
              <text x="34" y="80" className="s-verdict">Hold</text>

              <path d="M34 108h272" stroke="#E4E8F2" strokeWidth="4" strokeLinecap="round" />
              <g fill="#fff" stroke="#E4E8F2" strokeWidth="4">
                <circle cx="34" cy="108" r="8" />
                <circle cx="102" cy="108" r="8" />
                <circle cx="238" cy="108" r="8" />
                <circle cx="306" cy="108" r="8" />
              </g>
              <circle cx="170" cy="108" r="13" fill="#00439D" />
              <text x="24" y="134" className="s-tiny">Sell</text>
              <text x="222" y="134" className="s-tiny">Over</text>
              <text x="288" y="134" className="s-tiny">Buy</text>

              <rect x="30" y="152" width="280" height="46" rx="11" fill="#F4F6FB" stroke="#E4E8F2" />
              <text x="46" y="180" className="s-sml">Entry price</text>
              <text x="270" y="180" className="s-blank">—</text>

              <rect x="30" y="206" width="280" height="46" rx="11" fill="#F4F6FB" stroke="#E4E8F2" />
              <text x="46" y="234" className="s-sml">Stop-loss</text>
              <text x="270" y="234" className="s-blank">—</text>

              <rect x="30" y="260" width="280" height="46" rx="11" fill="#EEF3FE" stroke="#C9D9F7" />
              <text x="46" y="288" className="s-sml">Position</text>
              <text x="204" y="288" className="s-strong">Trim on rallies</text>

              <text x="34" y="336" className="s-mut">Why</text>
              <text x="34" y="360" className="s-sml">Order growth is real, but</text>
              <text x="34" y="380" className="s-sml">margins fell three quarters.</text>
            </svg>
          </div>
          <div className="stack-copy">
            <h3 className="stack-title">One final call, written in plain English</h3>
            <ul className="stack-list">
              <li>A clear rating you can actually act on</li>
              <li>The reason it landed there, in a sentence</li>
              <li>Fields left blank when the evidence will not support a number</li>
            </ul>
            <p className="stack-note">A blank entry price is a decision, not a gap.</p>
          </div>
        </article>
      </div>
    </section>
  );
}
