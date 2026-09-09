# TickerInvest — web design reference

How to build a new page for this site so it matches what already ships.

**Reference implementation:** `web/design/landing-fintech/index.html`. Every value below was
extracted from that file, not remembered. When something here disagrees with the code,
the code wins — re-extract and fix this file.

> `web/design/landing/index.html` is a **different, abandoned direction** ("Board and Tape",
> midnight indigo, marigold/ice). Do not mix the two. Build against `landing-fintech`.

---

## 0. Read this first

The page is a **single self-contained HTML file**: Tailwind via CDN `<script>`, one
inline `<style>` block, one inline `<script>` at the end. No build step, no npm, no
framework. A new page is a new sibling file that copies the `<head>`, the `<style>`
block, and the closing `<script>`.

Two consequences that have caused real bugs:

1. **Tailwind's stylesheet is injected AFTER the inline `<style>` block.** At equal
   specificity Tailwind wins. Never add a custom class *alongside* a Tailwind utility
   that sets the same property — **replace** the utility. (This is why `.relative` beat
   `position: sticky`, and why `.copy` had to replace `text-sm` rather than join it.)
2. **Arbitrary Tailwind opacity values off the scale silently emit nothing.**
   `bg-[#050A18]/92` produced no rule at all and left a nav transparent. Use the scale,
   bracket syntax `/[0.92]`, or an inline `style`.

---

## 1. Tokens

Copy the `:root` block verbatim from the reference file. Current values:

```css
--navy: #00439D;  --accent-1: #1C6FE6;  --accent-2: #237FFB;  --accent-3: #3DA2F1;
--ink: #010101;   --ink-2: #202020;     --muted: #757575;
--tint: #F4F4F4;  --line-1: #EBEBEB;    --line-2: #E0E1E2;
--void: #050A18;  --void-2: #0A1226;    /* dark section ground */
```

**Colour rules**
- One accent family (the blues). `--accent-1` is the CTA colour everywhere.
- **Green and red are reserved for price direction only** — with one scoped
  exception, made 2026-08-23 by explicit user override after this rule was
  raised and the tradeoff stated plainly: the 5-tier rating (Sell..Buy) and
  the 3-tier action badge (Sell/Hold/Buy) now use a real diverging red-grey-
  green scale (`web/app/src/lib/rating-color.ts`). Every non-color pairing
  keeps the rest of this rule as written: still never use green/red for
  **bull/bear** (that's an argument stance, not a price call — stays on the
  navy/`#1B6FA8` pair) or for any other status/badge on the page. Indian
  retail readers already read green/red as "my position is up/down";
  borrowing them for anything that isn't the rating/action fields still
  mislabels something the reader will misread as a price move.
  — Second exception, 2026-08-28, explicit user request: the landing
  page's "Leadership churn" argument card (`TrustStrip.tsx`) colors its
  event-timeline nodes green/red by real-world valence (a divestment is
  the company's own proactive move; a resignation or a weak print is a
  negative outcome), reusing the same rating-color `-700` family rather
  than new hexes. The one event whose valence is the card's actual
  bull/bear subject ("new management") is left neutral on purpose, so
  the color-coding doesn't silently pick a side of the debate.
- Light sections: `#fff` / `--tint` ground, `--ink` headings, `--muted` body.
- Dark sections: `--void` ground, white headings, `rgba(255,255,255,.55–.62)` body.

**Page theme lock:** the page alternates full dark and full light *sections*. Never
flip theme inside a section.

---

## 2. Typography

Fonts (pinned by the client — do not substitute, and ignore any "Inter is overused"
detector finding):

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Inter+Tight:wght@500;600;700;800;900&display=swap" rel="stylesheet">
```

`Inter Tight` = display/headings/labels (`.font-tight`). `Inter` = body.

### The ramp

| Role | Size | Weight | Notes |
|---|---|---|---|
| Section display (`h2`) | `text-4xl sm:text-5xl` | 900 | `leading-[1.02] tracking-[-0.025em]` |
| Card title | 17px (`text-xl`) / 1.05rem | 600–800 | |
| Lede | 16–17px | 400 | one per section, under the `h2` |
| **Body** | **15px** | 400 | use `.copy` |
| Meta / caption | 12px | 400–700 | captions, stat labels, UI chrome |

Three classes carry this — use them instead of per-element Tailwind sizes:

```css
.copy      { font-size: .9375rem; line-height: 1.62; }
.copy-dark { font-size: .9375rem; line-height: 1.68; letter-spacing: .004em; }
.measure   { max-width: 68ch; }
```

**Rules**
- 15px is the body floor for prose. Below that only for genuine meta or simulated
  product-UI chrome (the fake app cards) — those are a legitimate dense role.
- **Light text on dark needs compensation on all three axes**: more line-height, a
  touch of positive tracking, a lifted tone. That is exactly what `.copy-dark` is.
- Adjacent roles need a **≥1.15× size step** *or* a clear weight/colour difference.
  Two roles 1.12× apart doing different jobs is a hierarchy failure.
- Put `.measure` on any prose that would otherwise run the full container.
- 45–75ch applies to **prose**. Multi-column card text at 25–30ch is fine — do not
  "fix" it.
- **Measuring ch: `1ch ≠ 0.5em`.** Inter's `0` is 0.63em. Measure by rendering
  `'0'.repeat(100)` in the element's own computed `font` and dividing. An assumed
  ratio produced a 26% error and a false bug report.

---

## 3. Spacing

- Section padding: **`py-20 lg:py-28`** (112px) for major sections, **`py-16 lg:py-20`**
  (80px) for lighter strips. Reuse these two; don't invent a third.
- Container: `max-w-screen-xl mx-auto px-6 lg:px-8`.
- **Rhythm beats uniformity.** Inside a group use tight gaps; between groups use
  generous ones. Target a **≥3× ratio** (the engine section uses 14px vs 52px). One
  repeated value everywhere is the failure mode.
- Radii: `rounded-2xl` (cards), `rounded-[28px]`/`rounded-[32px]` (feature panels),
  `rounded-full` (pills/CTAs). Pick per role and stay consistent.

---

## 4. Motion

Keep the existing vocabulary. Curves and durations that are already in use:

| Purpose | Curve | Duration |
|---|---|---|
| Entrance / confident arrival | `cubic-bezier(0.16, 1, 0.3, 1)` | 400–700ms |
| Sectional slide-up | `cubic-bezier(0.22, 1, 0.36, 1)` | 350ms |
| Hover / colour | Tailwind default | 150ms |
| Accordion | `cubic-bezier(.4, 0, .2, 1)` | 450ms |

Reusable classes: `.u-rise` (staggered page-load entrance, `--rise`/`--delay`),
`.u-reveal` + `.is-in` (scroll reveal), `.btn-shimmer` (one-shot sweep on hover),
`.u-ticker` (marquee).

### Hard motion rules — these came from a real audit that failed

1. **Scroll-reveals must be progressive enhancement.** Content renders visible by
   default; JS adds an `anim-ready` class that *arms* the hidden start state. If the
   observer never fires or JS is off, the reader still gets the content. Never author
   content at `opacity: 0` as its resting state.
2. **Never transition a scroll-linked `transform`.** A CSS transition outranks even
   `!important` inline styles and pins the element at its start value. Scroll position
   already supplies continuity.
3. **Ambient loops must pause off-screen.** Put `data-motion-gate` on the section, and
   register the animated selector in *both* gate rule lists (`paused` and
   `.is-onscreen … running`). Unpausable loops are an accessibility failure.
4. **No pulsing status dots.** A static coloured dot plus its text label carries the
   same information. This is the single clearest AI-slop tell.
5. Don't reuse one identical entrance on every section. Cap it at ~3 elements.
6. `prefers-reduced-motion`: drop movement, keep opacity/colour transitions.
7. Animate `transform`/`opacity`. If you must animate a gradient, animate a
   pseudo-element's `opacity` instead of the `background` (10 tiles repainting per
   frame was a real regression).
8. Timing can express distance — the engine pulses derive duration from wire length.

---

## 5. Page architecture

Current section order in the reference page:

```
nav (dark, sticky) → ticker → hero (dark) + stat rail → trust strip (light)
→ #how pipeline stack (light) → #use-cases (light) → #deck (dark)
→ #live split feature (dark) → #faq (light) → CTA (dark) → footer (light)
```

`#engine` (the research-engine graph) is currently **commented out** in the reference
file — a labelled block, CSS and JS left intact. Uncomment to restore.

**Reusable section patterns** (copy the markup, swap content):
- **Sticky card stack** — `.stack-card` pinned at stepped `top` offsets. Requires:
  `--strip` must exceed `padding-top + label height`, and
  `nav + (n-1)*strip + cardHeight` must fit the viewport or the last card clips.
- **Scroll-pinned horizontal deck** — `.deck-track` translated by scroll progress.
- **Split feature** — badge + `h2` + short bullets + 2 CTAs, animated panel opposite.
- **Accordion** — class-driven `max-height`. (Not `grid-template-rows`: Chrome cannot
  interpolate `0fr→1fr` in an auto-height grid and the transition sticks.)

**`position: sticky` breaks if any ancestor has `overflow: hidden`.** Put the clip on
the background layer, not the section. Use `overflow-x: clip` on `body`, never `hidden`.

---

## 6. Content rules

- **Never invent numbers.** Every figure on the page comes from `PRODUCT_OVERVIEW.md`
  (12 agents, 5 teams, 2 debates, 10 reports, ~11k words, ~4 min / ~14 min, NSE+BSE).
  Competitor-style stats ("1Bn+ parameters") have no true equivalent here.
- **No fabricated testimonials, logos, or user counts.** The testimonials block stays
  a commented `TODO(proof)` until real quotes exist.
- Frame as **research, not advice** — SEBI-sensitive. Keep the disclaimer in the footer.
- A blank field is meaningful: render "Not set", never `0` or a dash.
- Keep `TODO(...)` markers for anything unshippable. Current ones: `name` (wordmark is
  a placeholder), `art` ×2 (picsum placeholders), `proof`, `regulatory`, `legal`.
- **Zero em-dashes (`—`) in visible copy.** Use a period, comma, or colon. Enforced for
  Persuade prose (`landing-fintech`, `research/index.html`'s hand-authored copy). NOT
  enforced for the Operate surface's dynamic, data-driven strings once real React
  components took over (`RunHistoryPanel`'s list labels and status text, the compare
  page's subhead) — those read closer to a data separator than persuasive prose, and
  retrofitting them would mean rewriting copy pervasive across already-shipped,
  already-tested components for a rule this specific text was never actually checked
  against. Noted here rather than silently drifting further from the written rule.
- **Max 1 eyebrow per 3 sections.** Eyebrows that just restate the headline below them
  get deleted.
- Hero: max 4 text elements (eyebrow, headline, subtext, CTAs). No tagline under the
  CTA, no decoration strip.

---

## 7. Images

- `picsum.photos/seed/{seed}/{w}/{h}` works. **`source.unsplash.com` is dead (503)** —
  the random/featured endpoints were discontinued.
- Picsum returns **random** subjects, so it is only honest as a low-opacity
  `mix-blend-luminosity` texture layer where the subject doesn't matter. Do not put a
  random photo in a content slot on a finance page.
- Icons are hand-authored inline SVG in a duotone style (translucent base shape +
  solid foreground), sized 20–22px in a 44px `grad-navy` tile. Match the headline
  literally. **Zoom-verify any curved icon at render size** — a bezier "scale" read as
  an unrecognisable blob at 22px until redrawn with lines and circles.
- **Scoped exception: 🔔 on the push-notification button** (`RunStatusBanner.tsx`,
  "Notify me" / "Notified"). Emoji, not hand-authored SVG — deliberate, not an
  oversight: it costs zero asset work, and it matches the bell glyph every OS
  notification-permission prompt already shows the same reader, which reads clearer
  here than a bespoke duotone bell would. Redraw as SVG only if a second icon-bearing
  button ships elsewhere and the mismatch starts reading as inconsistent — not before.

---

## 8. Skills — what to invoke, and when

All are installed. Invoke with the `Skill` tool.

| Task | Skill | Notes |
|---|---|---|
| Spacing, rhythm, hierarchy | `impeccable:impeccable` → `layout` | |
| Typography, type scale | `impeccable:impeccable` → `typeset` | |
| Adding or improving motion | `impeccable:impeccable` → `animate` | |
| Final pass before shipping | `impeccable:impeccable` → `polish` | |
| Whole new page / anti-slop check | `design-taste-frontend` | strict pre-flight checklist |
| Motion philosophy, curves, durations | `emil-design-eng` | |
| Auditing existing motion | `design-motion-principles` (audit mode) | emits an HTML report |
| Building one animation from scratch | `animate` | |
| Contrast / keyboard / ARIA | `accessibility` | |

### Orchestration for a new page

1. **`design-taste-frontend` first.** It is audit-first and owns the brief read. State
   the one-line design read and the three dials before writing code
   (this page: `VARIANCE 7 / MOTION 5 / DENSITY 4`).
2. **Build** using the tokens, ramp, and section patterns above.
3. **`impeccable:impeccable`** for refinement. Its setup runs
   `node <skill-base-dir>/scripts/context.mjs` **once per session** — do not rerun.
   Then load the one playbook that owns the request, then `craft-floor.md` immediately
   before editing UI.
4. **Run its detector** and act on findings:
   ```bash
   node "C:/Users/anujs/.claude/plugins/cache/impeccable/impeccable/4.1.1/skills/impeccable/scripts/detect.mjs" \
     --json --scope type|layout <file>
   ```
   It runs **degraded** here (no htmlparser2/css-select) — regex only. It cannot tell an
   *inset* shadow from a glow halo and cannot resolve selectors, so findings are an
   undercount and some are false positives.
5. **Verify in bounded passes**, not a loop: build fully, inspect once, fix in one
   batch, confirm once, stop.

### Standing detector overrides (do not "fix" these)

| Finding | Why it stands |
|---|---|
| `overused-font` ×11 | Inter / Inter Tight are client-pinned |
| `marquee` | the ticker is a requested feature; it pauses on hover |
| `dark-glow` | an **inset** highlight; the regex can't distinguish inset from halo |
| `layout-transition` | accordion `max-height`; the alternatives are broken (see §5) |

These four are also persisted as `ignore-value` entries in `.impeccable/config.json`,
scoped per file (`web/design/landing-fintech/index.html`, `web/design/research/index.html`). The table above
is why; the config is what actually suppresses them.

---

## 9. Operate-surface patterns (research page)

**Reference implementation:** `web/design/research/index.html`. Same rule as §0: every value
here was extracted from that file. Everything in §§1–9 above still applies; this section
only adds what a Persuade page never needed.

### Why a second reference file

`landing-fintech` is Persuade: the visitor decides and acts, design is the product.
The research page is **Operate**: the visitor is in a task, reading an argument and
verifying numbers. Same tokens, same type ramp, same spacing scale, but three defaults
flip:

- **Accent width narrows.** Persuade earns some decoration; Operate spends the accent
  colour on primary actions, current selection, and state only (`impeccable` Operate
  guidance). The research page has no gradient text, no `grad-navy` panels outside the
  nav mark, no shimmer.
- **Disclosure tempo shortens.** §4 pins `cubic-bezier(.4,0,.2,1)` / 450ms for the
  landing page's one hero accordion. The research page reuses the curve but drops the
  duration to **260ms** (`--dur-open`) — it has ten stacked report rows plus inline
  evidence traces, and 450ms per row reads as sluggish once you're opening several.
  Same vocabulary, surface-appropriate speed.
- **No page-load choreography.** `.u-rise`, `.u-reveal` and friends stay on the landing
  page. A task surface loads into the task; the only authored motion here is the
  disclosure transitions themselves.

### The corrected greys

`--muted: #757575` and the ad hoc `#747474` in `landing-fintech` are both fine **on
that page's pure-white body ground** (4.60:1 / 4.67:1). They fail once the ground
darkens even slightly. The research page's body is `#F7F8FB`, not `#fff`, so the same
greys dropped to 4.35–4.40:1. Two replacement greys, verified against every ground in
actual use on this page (white cards, `#F7F8FB` page background, `#F6FAFF` trace
panels):

```
#6F6F6F   /* was #747474 — secondary copy, section ledes on white or near-white */
#676D80   /* was #9AA0AE / #8A90A0 / #6B7186 — meta, captions, table row labels */
```

Rule going forward: **don't reuse `--muted` or `#747474` on any ground darker than pure
white without re-measuring.** If a card sits on `#F7F8FB` or a tinted panel, use
`#6F6F6F` / `#676D80` or re-measure for that specific ground. This also caught four
real failures in `landing-fintech`'s dark sections (`.run-state`, the entry/stop/action
labels, "Research Manager rules", the elapsed-time chip) — those were `text-white/38`
through `/45`; all raised to `/55`, which is what §1 already specifies as the dark-body
floor (`.55–.62`) and the only value that clears 4.5:1 across every dark card ground
measured (`#050A18`, `rgb(18,22,36)`, `rgb(26,30,43)`, `rgb(29,34,47)`).

### Evidence trace

A number inside an argument is a `<button class="fig">`. Clicking it opens an inline
card showing the **pre-fetched tool value** the agent was handed, not a restatement of
the claim — the run's no-invented-numbers discipline made inspectable.

```css
.fig  { color: var(--navy); font-weight: 600; border-bottom: 1px dashed #9FC0EE; }
.trace { overflow: hidden; transition: max-height var(--dur-open) var(--ease-open); }
```

- **One trace open at a time, page-wide**, not per-section. Closing every other
  `.fig[aria-expanded="true"]` before opening a new one keeps the reader's place
  legible; two open traces competing for attention is noise.
- **The values live in the DOM, not in a JS object.** A `[data-trace-store]` section
  near the page foot holds every entry as ordinary markup (`[data-trace-entry="key"]`).
  JS clones `innerHTML` from there into the clicked figure's panel. This is what makes
  disclosure progressive enhancement (§4 rule 1) actually true for evidence, not just
  for report bodies: with JS off, the values are still on the page, just not
  interactive, in a labelled "The values behind the figures" section instead of
  floating unreachable inside a script.
- **z-index matters when a trace sits inside a positioned section.** The contested
  ledger (`.ledger::before`, next entry) draws an absolutely-positioned rule down its
  centre. A trace panel opened between two ledger rows must set
  `position: relative; z-index: 1` or the rule paints through the card. Found by
  screenshot-zooming an open trace during verification, not by the detector.
- **Scope discipline: only trace a figure that reconciles.** The fundamentals report
  and the debate quote two different receivables totals for the same fact (₹1,464 cr
  vs ₹1,771 cr). That figure stays an attributed claim in running prose, not a `.fig`.
  A "verified" badge on a number that doesn't reconcile against its own source would be
  the exact failure this product exists to prevent. Trace what checks out; leave the
  rest as prose.

### Contested ledger (the seam, generalised)

`landing-fintech` has one seam: a single contested figure, two readings, one ruling.
The research page generalises it to a repeatable unit for **N** contested points.

```
.ledger              position: relative — carries the centre rule
  ::before           the rule itself, absolutely positioned, min-width:900px only
.ledger__head        column labels (BULL / BEAR), desktop-only, display:none below 900px
.duel                one contested point: grid-template-columns: 1fr 176px 1fr at ≥900px
  .duel__topic       the centre label, sits on the rule, bg:#fff so the line breaks under it
  .duel__bull/.bear  the two readings
    .duel__side      "BULL"/"BEAR" — visually hidden at desktop (clip-path inset(50%),
                     never display:none), becomes the only side-identifying cue once
                     the pair stacks below 900px and the spatial left/right cue is gone
```

- **Label once, not per-row, when position already carries the meaning.** At desktop,
  left/right *is* bull/bear; twelve repeated "BULL"/"BEAR" labels would be redundant.
  `.ledger__head` says it once. Below 900px the pairs stack top-to-bottom, the spatial
  cue disappears, and the per-row `.duel__side` — kept in the accessibility tree at
  every width via `clip-path`, never `display:none` — becomes load-bearing again.
- **Rhythm: 10px inside a pair, 46px between pairs** (§3's ≥3× ratio, applied here as
  ~4.6×). A `.duel + .duel { margin-top: 46px }` reads six arguments as six distinct
  rounds, not one wall of text.
- **`main > * { min-width: 0 }`** — grid items default to `min-width: auto`, so a wide
  child anywhere in the main column (the risk table below, in this build) forces the
  *entire* two-column page grid wider than the viewport, silently, with no single
  element visibly overflowing in a screenshot. This is the overflow bug most likely to
  recur on the next Operate page that mixes a grid layout with a wide tabular child.
  Diagnose by walking the DOM for the innermost element wider than the viewport whose
  overflow isn't already contained — don't assume the wide element is the direct cause.

### Risk / comparison table

Three speakers, one fixed set of parameters, genuinely different values per cell. This
is the one place on the page that reaches for `<table>` instead of cards — the content
is tabular (row × column lookup), not a list.

```css
.rk           { min-width: 560px; }              /* table needs its own floor */
.rk__adopted  { background: #F6FAFF; }            /* the column the manager took */
.rk__tag      { background: var(--accent-1); color: #fff; border-radius: 999px; }
```

- Wrap in `overflow-x-auto` and give the `<table>` its own `min-width`, not the
  wrapper. Combined with `main > * { min-width: 0 }` above, this is what lets the table
  scroll horizontally on narrow viewports instead of forcing the whole page wide.
- Mark the adopted column, don't just state it in prose below. `MANAGER TOOK THIS` as
  an accent-filled pill on the column header answers "which one won" at a glance,
  before the reader gets to the paragraph that explains why.
- `<caption class="sr-only">` describes the comparison being made; screen-reader users
  get the table's purpose before its cells.

### Report list — expandable, length still honest

Extends the existing `.rep` / `.rep__bar` length-honesty pattern (already in §"Reusable
section patterns" territory) into a real disclosure control.

```css
.rep__doc { max-height: 340px; overflow-y: auto; }   /* the bound that makes it work */
```

- **Cap the inner scroll, not the outer panel.** A 204-word report and a 3,028-word
  report both open to the *same* max height (the reports get 340px / 322px in practice
  — the shorter document's own content is shorter than the cap). Without the inner
  cap, `.rep__panel`'s `max-height: <scrollHeight>px` would make the sentiment report's
  row visually dominate the list the moment it's opened, and the transition duration
  would need to scale with content length to still feel like "one speed."
- **One hairline per row state, not two.** `.rep[aria-expanded="true"]` clears its own
  `border-bottom`; the now-visible `.rep__panel` draws the line instead. Both drawing
  at once (the original build's bug, caught by a `panel.getBoundingClientRect().height
  === 0.8` reading during verification, not by eye) produces a barely-visible double
  rule that looks like a rendering glitch.
- **Chevron rotates, colour shifts, weight doesn't change.** `.rep[aria-expanded="true"]
  .rep__chev { transform: rotate(90deg) }` plus a colour shift to `--accent-1` is
  the entire "this is open" signal. No layout shift in the row itself.

### Armed disclosure (the JS-off contract for interactive panels)

The idiom every disclosure control on this page shares, generalising §4 rule 1
("scroll-reveals must be progressive enhancement... never author content at opacity:0
as its resting state") from scroll reveals to click-to-expand panels:

```css
.trace, .rep__panel { overflow: hidden; transition: max-height var(--dur-open) var(--ease-open); }
.js-armed .trace, .js-armed .rep__panel { max-height: 0; }
```

```js
document.documentElement.classList.add('js-armed');   // first line the script runs
```

- **Resting state (no JS) is open.** Every report body and every evidence entry is
  real, readable document content before the script ever runs. JS's first act is to
  *arm* the collapsed state by adding `.js-armed` to `<html>` — the CSS rule that
  actually collapses panels is gated behind that class, so it's inert until JS says
  otherwise.
- **Consequence for content authoring:** nothing that matters can live only inside a
  JS data structure. The evidence-trace store (previous section) exists as a DOM
  section specifically so this contract holds for the drill-down, not just for the
  report bodies.
- **Re-measure on resize, not just on open.** `max-height` is set to a *pixel*
  `scrollHeight` at the moment of opening; a viewport resize that reflows the text
  inside an already-open panel leaves the old pixel value stale (either clipping new
  lines or leaving dead space). A debounced `resize` listener re-measures every
  currently-open `.rep__panel` and `.trace` panel.

---

## 10. React app additions (no static mockup precedent)

Everything in §§1-9 is extracted from a static HTML reference file (§0, §9) — build the
mockup first, extract the pattern, then write the React component. The items below
shipped the other way round: built directly in the live app, no preceding mockup.
Noted here so a later re-extraction pass doesn't miss them, and so the gap from the
usual workflow is a recorded decision, not silent drift.

### Run comparison (two-up cards)

`web/app/src/app/runs/compare/page.tsx` + `CompareCard.tsx`. Two runs, side by side,
each a compact card (`rounded-[28px]`, the same card shell as every other section)
rather than §9's "Risk / comparison table" `<table>` shape: that pattern fits three
speakers against one fixed parameter set (a row × column lookup). This compares two
*whole* runs, each carrying its own independent set of fields — reads as two peers,
not as a 2-column table forcing every field into its own row.

- `grid sm:grid-cols-2 gap-6`, the same breakpoint every other two-up grid on the site
  already uses.
- Reuses TheCall's rating badge and stat-`dl` markup at a smaller type scale — no new
  visual language, just a compact restatement of an existing pattern.
- Entry point is `RunHistoryPanel`'s sibling list (select two, "Compare selected"
  appears), not a dedicated nav item or a bare URL a reader is expected to construct:
  comparing is a follow-on action from "these runs disagreed," not a page someone
  browses to cold.

### Checkboxes

First use of a native checkbox on the site (`RunHistoryPanel`'s run-selection, feeding
the comparison above). No custom control: `<input type="checkbox"
className="accent-[#1C6FE6] disabled:opacity-30">`. `accent-color` keeps native
keyboard/touch behaviour intact for free, rather than hand-building a styled box.
Disabled state (a run with no verdict yet — queued, running, or failed) drops to 30%
opacity instead of hiding the control, so the row's shape stays constant whether or
not that particular run is currently selectable.

---

## 11. Verification checklist

Before calling a page done:

- [ ] Type scan and layout scan show no *new* findings
- [ ] No horizontal overflow (`scrollWidth === clientWidth`)
- [ ] No console errors
- [ ] All in-page anchors resolve to real ids
- [ ] Body text ≥ 4.5:1 contrast; large text ≥ 3:1
- [ ] Content still visible with JS disabled / observers never firing
- [ ] Ambient loops pause off-screen
- [ ] `prefers-reduced-motion` drops movement but keeps meaning
- [ ] Zero em-dashes; eyebrow count ≤ ⌈sections ÷ 3⌉
- [ ] Screenshot **after** reveals settle — a shot taken mid-transition looks broken
      and has twice triggered a false bug hunt
