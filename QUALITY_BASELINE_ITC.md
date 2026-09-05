# ITC.NS — accuracy baseline for the modified-vs-base comparison

Companion to `QUALITY_BASELINE_SIEMENS.md`, which tests whether *shortening*
breaks reasoning. This one tests something different and harder: whether the
modified engine can survive **bad input data** as well as the base engine did.

Both runs below consumed a byte-identical, one-session-stale price snapshot.
The base engine produced a usable recommendation anyway. The modified engine
did not. That is the whole finding, and it is why "our changes are individually
correct" was not sufficient.

## The two runs

| | Base (`perf-worktree`) | Modified (`ui-worktree`) |
|---|---|---|
| Artifact | `reports/ITC.NS_20260902_161132` | run `18d14756244df444…` |
| Ran at | 2026-09-02 16:11 IST | 2026-09-02 00:26 IST |
| Profile | detailed, 2 debate rounds | fast, 1 debate round |
| Model | `deepseek-v4-flash-0731` (OpenRouter) | `deepseek-v4-flash` (direct) |
| Verdict | **Underweight**, trim into ₹268–272 | **Overweight**, buy at ₹255.50 |
| Market analyst said | SELL | SELL |

Note the last row: **both** technical analysts said SELL. The base engine's
chain respected that; the modified engine's chain overrode it.

## Ground truth (verified against yfinance, 2026-09-03)

Anything below is checkable, not a matter of opinion.

| Fact | Value |
|---|---|
| Close 2026-08-31 | ₹255.50 (also the 52-week low) |
| Close 2026-09-01 | **₹266.60 (+4.34%)** |
| Close 2026-09-02 | ₹266.30 |
| Low after 08-31 | ₹261.50 (09-01) — **₹255.50 never traded again** |
| RSI-14 on 08-31 / 09-01 | 24.1 → **41.7** |
| MACD histogram 08-31 / 09-01 | −1.32 → **−0.89 (contracting)** |
| Lower Bollinger 09-01 | 258.08 — price **above** it |
| Last traded in ₹250–258 before 08-31 | **June 2022** (2023/24/25 lows: 314.9 / 388.4 / 394.9) |
| Dividend yield (vendor) | **6.02%** |
| Dividends ÷ FCF FY26 | 182.7B ÷ 162.8B = **112%** |
| Payout ratio (earnings) | 91.5% |
| ROE / ROCE in retrieved data | **absent — never fetched** |
| Q1 FY27 revenue y/y | 190.0B vs 213.7B = **−11.1%** |
| Q1 operating income y/y | 47.5B vs 63.9B = **−25.7%** |
| Q1 normalized NI y/y | 40.8B vs 52.4B = **−22.1%** |
| Inventory y/y | 188.7B vs 158.4B = **+19.1%** |
| FY23→FY26 net income CAGR | 191.92B → 206.89B = **2.53%** |

## The scorecard — 8 load-bearing claims

Pre-registered: each is checkable against the table above, and each is
something a competent analyst either gets or misses.

| # | Claim | Base | Modified |
|---|---|---|---|
| 1 | Recommends a level that was actually reachable after the run | ✅ 268–272; 09-02 high 269.00 | ❌ 255.50, never traded again |
| 2 | Does not assert support it has no data for | ✅ "no measured support below 255.50 **in 13 months**" | ❌ "₹253–255 **multi-year support**" (last true in 2022) |
| 3 | Scopes its evidence window explicitly | ✅ "the verified 13-month OHLCV history"; "Data as of Aug 31 close" | ❌ buried note, no window stated |
| 4 | Uses the computed dividend yield over the social one | ✅ "~6% yield" | ❌ "5.2% yield" ×12 (from a tweet) |
| 5 | Resolves the payout question correctly | ✅ "dividends exceeded FCF, **though OCF of 184.6B still covered it**" | ❌ bull says 74%, bear says 112%, never reconciled |
| 6 | Q1 deterioration quantified correctly | ✅ −11% / −25.7% / −22% all exact | ✅ all exact |
| 7 | Multi-year growth trend interrogated | ✅ "FY23→FY26 only ~2.5–3%" — skips demerger-distorted FY25 | ❌ absent |
| 8 | Flags that its own price data is stale | ❌ knew of the 09-01 pop, never said the price was stale | ❌ same, and worse — anchored to it |

**Base: 7 / 8. Modified: 2 / 8.**

Claim 8 is the one *neither* engine got, and it is the root cause of claim 1.
Both had "ITC Rallies 4.3%" dated 09-01 sitting in their own news report while
quoting a 08-31 price, and neither reconciled the two.

## Root causes, and what each fix targets

| # | Root cause | Ours? | Fix |
|---|---|---|---|
| RC1 | `_price_anchor` made the stale price *binding* on the Trader ("must transact at THIS price"). Base had no anchor, so it reasoned from the analysts' cited shelf instead. | **yes** | `_sessions_missed`; a stale anchor degrades to an order-of-magnitude check and hands primacy back to cited levels |
| RC2 | `balanced` word cap compressed reasoning agents 3–3.5× but data agents only 1.2–1.8×, so the entire cut landed on judgement. Market report hit its cap and contained "support" **zero** times. | profile | S/R block made structural and **exempt from the word cap**; `balanced_word_scale` 2.5 → 4.0 |
| RC3 | 1 debate round = bull → bear → stop. The bull never had to answer the bear, so its unsourced claim reached the RM standing. At 2 rounds the bull conceded the honest version. | profile | fast profile restored to 2 debate + 2 risk rounds |
| RC4 | No precedence rule: a filed-statement number and a tweet arrive as identical prose, so the quotable one wins. | pre-existing | `get_evidence_precedence_instruction()` on bull, bear, RM, PM |
| RC5 | Underweight with no `price_target` nulls `entry_price` too → card renders with no level at all | **yes** | promote `entry_price` to the exit level rather than lose it |
| RC6 | Staleness note read as routine weekend handling, so every agent ignored it | pre-existing | named session count + explicit cross-check against the news reports |

## How to re-run this

1. Point both worktrees at the same ticker and date.
2. Score claims 1–8 from the table above.
3. **Modified must score ≥ base.** Anything less means a change bought speed
   with accuracy, which is the trade this document exists to prevent.

Claim 1 is the one to watch: it is the only claim that is purely about whether
the output was *usable*, and it is the one that failed silently.

---

# Controlled head-to-head — 2026-09-04

The scorecard above compared a `fast` run against a `detailed` run, which
confounded code with profile. This is the like-for-like rerun.

## Controls held

| Variable | Value (both arms) |
|---|---|
| Ticker / analysis date | ITC.NS / 2026-09-03 |
| Profile | fast |
| Model | `deepseek-v4-flash`, provider `deepseek` — forced via env on **both**, so neither worktree's own `.env` could win |
| Data window | latest row 2026-09-03, close ₹263.00 — **verified identical in both snapshots** |
| Fundamentals | landed in both (1871 / 1810 words) |

Two traps this setup exists to avoid, both of which spoiled the first attempt:

* **`sys.path`.** `python script.py` puts the *script's* directory on the
  path, not the cwd — without `PYTHONPATH` pointing at the baseline
  worktree, the "baseline" arm imports the installed (modified) package and
  silently runs 2 debate rounds. The comparison then shows no difference
  because there is no difference.
* **Data drift.** The first attempt's arms ran ~14 hours apart, so the
  second one picked up a session the first never saw. Pinning the analysis
  date to a *completed* session makes `load_ohlcv`'s date filter guarantee
  parity regardless of when each arm runs.

## Results

| | modified-fast | baseline-fast |
|---|---|---|
| Wall clock | 491.6 s | **205.7 s** (2.4× faster) |
| Verdict | Overweight, entry ~₹263 | Hold |
| Market report | 791 w | 676 w |
| Bull / Bear | **1353 / 1319 w** | 468 / 415 w |
| Debate total | **2672 w** | 883 w |

| Claim | modified | baseline |
|---|---|---|
| Structured Support & Resistance block | ✅ present | ❌ **absent (3rd baseline run running, 3rd absence)** |
| Evidence window stated | ✅ "over the 30 sessions provided: 2026-07-24 → 2026-09-03" ×3 | ❌ none |
| Downside-support claim coherent | ✅ "below 255.50 … no measured support … downside price discovery" | ❌ **"no measured support until the 200-SMA zone"** — the 200-SMA is 307.91, i.e. 17% *above* price, so it cannot be downside support |
| Cross-report corroboration clause | ✅ "levels outside [window] … cannot be corroborated from this snapshot" | ❌ none |
| Payout arithmetic cited | ✅ ₹182.7B vs ₹162.8B FCF | ❌ neither figure |
| Dividend yield | ✅ ~6% throughout | ✅ 6.0% (plus a correctly-labelled 4.9% *FCF* yield) |
| Q1 revenue −11.1% | ✅ | ✅ |
| Unfounded "multi-year support" | ✅ none | ✅ none |

## Reading

The differentiator is **price-structure discipline**, and it is the one
thing that reproduced. Across three baseline runs this session the market
report never once produced a structured S/R block, and here it produced an
incoherent downside-support claim that the modified arm's window-scoping
makes unstateable.

What did NOT differentiate: dividend yield and Q1 arithmetic. The baseline
gets both right when it has fundamentals data. The evidence-precedence rule
was therefore not stress-tested by this run — the baseline never reached for
the social figure it was written to outrank.

## Caveats

n=1 per arm on one ticker and one date. Verdicts differ (Overweight vs
Hold) but nothing here establishes which is correct — that needs forward
returns, not a scorecard. Sampling is not bitwise deterministic even at
temperature 0.2 with a fixed seed. And the modified engine costs 2.4× the
wall clock for the depth it buys.
