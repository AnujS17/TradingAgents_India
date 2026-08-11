# Session Handoff — TradingAgents_Ind audit & pivot work

Written 2026-08-10 by a prior Claude Code session that ran out of context. Read this fully before doing anything else, then continue from "Open item" below.

## Repo layout

- `E:\Research papers\TradingAgents1\TradingAgents` — original repo, pivoted earlier to a **tech-stock** focus.
- `E:\Research papers\TradingAgents1\TradingAgents_Ind` — manual fork of the above, pivoted to **India (NSE/BSE)** focus, kept fully separate. **This is the active repo for the work below.**
- Dedicated venv for this repo (do not use the other repo's venv — they've collided before):
  `E:\Research papers\TradingAgents1\TradingAgents_Ind\.venv\Scripts\python.exe`
- Run tests with: `cd "E:\Research papers\TradingAgents1\TradingAgents_Ind" && .venv\Scripts\python.exe -m pytest tests/ -q -m unit`
- graphify graph lives at `graphify-out\graph.json` in this repo. To resync after a code change (code-only, no LLM key needed):
  `cd "E:\Research papers\TradingAgents1\TradingAgents_Ind" && "C:\Users\anujs\AppData\Local\Programs\Python\Python310\python.exe" -m graphify . --update --code-only`
  (Full `--update` without `--code-only` will also try to semantically re-extract changed report .md files, which needs an LLM key — avoid that, always pass `--code-only` for source-code-only resyncs.)
- The user's global CLAUDE.md says: use graphify for code navigation, and re-run the update above after any code change.

## What happened this session, in order

1. **India-market pivot** (see plan file `C:\Users\anujs\.claude\plans\cozy-dazzling-gosling.md` for full original spec) — renamed tech-stock-focused code/prompts/news to India-focused equivalents across ~10 agent files, `default_config.py`, `agent_utils.py`, `tech_news.py`→`india_news.py`, test files. **Appears complete** based on files read this session (`india_insider.py`, `get_india_market_instruction`, `fx_rates.py` all exist and are wired in) — not re-verified with a fresh grep this session; if picking this thread back up, grep for `tech_stock`/`tech_news`/`TECH_TICKER` across the repo to confirm zero leftover references.
2. **Insider-transaction data**: added `tradingagents/dataflows/india_insider.py` wrapping `jugaad_data.nse.NSEArchives.bulk_deals_raw()` — `fetch_promoter_bulk_deals(ticker, curr_date, limit=None)`.
3. **Currency-mismatch warning**: added `tradingagents/dataflows/fx_rates.py` (`fetch_fx_rate`, `currency_mismatch_warning`) using yfinance FX tickers, wired into `y_finance.py`'s fundamentals/balance-sheet/cashflow/income-statement fetchers.
4. **Bug: GDELT queries silently rejected 100% of the time.** `gdelt_news.py`'s `get_news()`/`get_global_news()` built unparenthesized `"X" OR "Y"` queries; GDELT's DOC 2.0 API requires them wrapped in parens. Fixed by wrapping. Verified live (error category changed from syntax-rejection to rate-limit).
5. **Bug: crash on `route_to_vendor()`.** `except ValueError` was listed before `except requests.exceptions.RequestException` in `tradingagents/dataflows/interface.py`; `requests.exceptions.JSONDecodeError` is a subclass of both, matched the wrong (source-order-first) branch, and re-raised instead of falling back to the next vendor — crashed a live run on RELIANCE.BO. Fixed by reordering the except clauses. Regression test: `tests/test_tool_routing.py::test_news_route_falls_back_on_malformed_json_response`.
6. **Bug (biggest one): ticker never corrected at state level.** A bare ticker like `"RELIANCE"` was set once into `company_of_interest` in `create_initial_state()` and never updated — even though the LLM's own tool calls self-corrected to `RELIANCE.NS` mid-run. This broke every deterministic pre-fetch (verified market snapshot, StockTwits, Reddit, India news, promoter bulk deals) for the whole run, since those don't have LLM reasoning to self-correct. Root cause of "technical data not fetched / stocktwits empty / no news / no reddit" symptom the user reported on a RELIANCE run. Fixed: added `resolve_ticker_symbol()` in `tradingagents/agents/utils/agent_utils.py` (tries bare/`.NS`/`.BO` variants via `previousClose` check, `@lru_cache`d), called once in `tradingagents/graph/propagation.py`'s `create_initial_state()`. Regression tests: `tests/test_ticker_resolution.py` (6 tests).
7. **Bug: redundant duplicate tool calls.** `get_verified_market_snapshot` was both pre-fetched directly AND exposed to the LLM via `bind_tools()` in `market_analyst.py`, so the LLM would redundantly re-invoke it with identical args. Fixed by removing it from the `tools` list (kept the pre-fetch call) in `market_analyst.py`, and removed its now-dead `ToolNode` registration in `trading_graph.py`. Test updated: `tests/test_tool_routing.py::test_market_tool_node_does_not_expose_verified_snapshot_as_callable_tool`.
8. **Bug: duplicate `[Data]` log entries in `message_tool.log`.** Found while auditing a LAURUSLABS.BO run's log for the user. `MessageBuffer.add_tool_call()` in `cli/main.py` already dedupes correctly and returns `False` on a repeat, but the caller in `run_analysis()`'s streaming loop ignored the return value and logged `[Data]` unconditionally — so every analyst's full data dump got duplicated once (root cause: `stream_mode="values"` re-emits the full state after every graph node, and `audit_tool_calls` isn't cleared between an analyst's own chunk and the "Msg Clear <X>" node right after it). Fixed by gating the `add_message("Data", ...)` call on `add_tool_call()`'s return value in `cli/main.py`. Regression test: `tests/test_tool_log_hygiene.py::test_audit_call_data_message_not_duplicated_on_repeat_chunk`.
9. **Full-suite verification after fix #8**: `157 passed, 4 failed (pre-existing/unrelated), 75 subtests passed`. The 4 failures are all in `tests/test_adx_dmi_indicators.py` — see "Known gap" below.
10. **Graphify resynced** after the `cli/main.py` + `tests/test_tool_log_hygiene.py` changes (code-only incremental update, 2 files re-extracted, graph now 1395 nodes / 2547 edges / 89 communities).
11. **Full audit of the LAURUSLABS.BO run** (`C:\Users\anujs\.tradingagents\logs\LAURUSLABS.BO\2026-08-10\message_tool.log` + `reports\LAURUSLABS.BO_20260810_132449\complete_report.md`), requested by the user to check data completeness / tool usage / hallucination / accuracy:
    - **No hallucination found.** Every numeric claim across market/fundamentals/news/sentiment/bull/bear/risk/trader/PM sections traces exactly to logged tool output.
    - Data completeness good: market analyst had a full verified snapshot + 5yr fundamentals; sentiment analyst genuinely had nothing (StockTwits `HTTPError`, empty news/Reddit/India-RSS) and reported that honestly with an explicit low-confidence flag rather than fabricating — this is expected/correct behavior, not a bug.
    - Tool usage correct post-fix #7 (no more duplicate `get_verified_market_snapshot` calls).
    - Minor **unfixed, low-priority** cosmetic issue found: `fetch_promoter_bulk_deals` gets called on essentially every graph tick throughout the run, producing a repeated identical `[Data]` line each time (cheap, cached, always correct — just log noise). I asked the user whether to apply the same `MessageBuffer` dedup pattern to it or leave as-is. **Their answer wasn't captured before this handoff — ask again or check if they replied.**

## Known gap (pre-existing, not fixed this session)

`tests/test_adx_dmi_indicators.py` (4 tests) expects ADX/DMI indicator support that doesn't exist yet in `tradingagents/dataflows/alpha_vantage_indicator.py` — its supported-indicator list is `['close_50_sma', 'close_200_sma', 'close_10_ema', 'macd', 'macds', 'macdh', 'rsi', 'boll', 'boll_ub', 'boll_lb', 'atr', 'vwma']`, no `adx`/`dmi`. This has shown up as a stable 4-failure baseline across this whole session — treat it as a known, separate, unimplemented-feature gap, not a regression from any of the fixes above.

## Open item — resolved 2026-08-10

User asked to dedupe `fetch_promoter_bulk_deals`'s repeated `[Data]` log entries. Investigation found no new production fix was needed: `audit_tool_calls` has no LangGraph reducer on that state key, so once `fundamentals_analyst.py` sets it, the value persists unchanged and gets re-emitted on every subsequent `stream_mode="values"` chunk for the rest of the run (that's why it looked like every tick). Fix #8 in `cli/main.py` already gates the `[Data]` log write on `MessageBuffer.add_tool_call()`'s `(name, args)` dedup key **generically**, not per-tool — and `fetch_promoter_bulk_deals`'s args (`ticker`, `curr_date`) never change within a run, so fix #8 already fully suppresses the repeat for it too. The LAURUSLABS.BO log that showed the repetition predates fix #8 landing in code. Added `test_bulk_deals_audit_call_not_duplicated_across_whole_run` in `tests/test_tool_log_hygiene.py` to lock this in (12 repeated chunks → 1 `[Data]` line). Full suite: 157 passed, same 4 pre-existing ADX/DMI failures (see "Known gap" above), no regressions. Graphify resynced.

No other known outstanding bugs from this session's work. If the user gives a new task, treat the above as background context, not a to-do list.

## Session 2 (2026-08-10) — sentiment/news data-source repair

Triggered by the LAURUSLABS.BO audit: technicals were fine and the system correctly reported "no data" rather than hallucinating, so the remaining work was making the *sources* actually return data. All root causes were confirmed live before any code was written (diagnostic scripts hit the real APIs).

1. **StockTwits was never down — wrong symbol namespace.** StockTwits indexes Indian equities as `SYMBOL.NSE`; we passed the yfinance `.NS`/`.BO` form, which 404s for *every* Indian ticker (`LAURUSLABS.BO` → 404, `LAURUSLABS.NSE` → 30 messages). There is no `.BSE` namespace, so both suffixes map to `.NSE`, with a bare-symbol retry. Fixed in `stocktwits.py` (`_symbol_candidates`, `_request_stream`). The failure string now lists what was tried, so a symbol bug can't be misread as an outage again. Tests: `tests/test_stocktwits_symbols.py`.
2. **Company news window too narrow.** Not a parsing bug — yfinance had 12 articles for LAURUSLABS.BO, but the newest was 2026-07-24 (17 days back) and the hardcoded 7-day window discarded all of them. Added `company_news_lookback_days: 30` to `default_config.py`, consumed by both `news_analyst.py` and `sentiment_analyst.py` (`_news_window_start`, formerly `_seven_days_back`). Verified: the window now surfaces the Q1 FY27 earnings-call report. Both prompts were updated to state the actual window and to require the analyst to flag how old a story is.
3. **Ticker-only text matching missed most of the market.** `india_news.py` matched articles via a hardcoded 20-ticker keyword map; everything else fell back to matching the literal ticker (`"LAURUSLABS"`), which Indian media never print — they write "Laurus Labs". Same bug in `reddit.py`. Added `tradingagents/dataflows/company_names.py` (`company_search_terms`), which resolves the real company name from yfinance, strips corporate suffixes, and keeps a curated alias table only for colloquial names no API returns (RIL, HUL, L&T). It lives in `dataflows` rather than reusing `agent_utils.resolve_instrument_identity` because `agent_utils` imports *from* `dataflows` — the reverse would be circular. Tests: `tests/test_company_names.py`.
4. **Reddit subreddits made India-only.** Dropped r/stocks and r/investing (US-equity boards, ~never carry an NSE/BSE symbol); now 7 verified-live India boards ordered by subscriber count. Also fixed `_fetch_subreddit`, which searched the raw exchange-qualified ticker (a guaranteed miss) instead of the search variants. PRAW/OAuth is the working path — **Reddit's public JSON API now returns 403 for every subreddit unauthenticated**, so `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` in `.env` are effectively required, not optional.
5. **MFI was on the wrong scale (found during this work, not previously reported).** stockstats returns MFI as a 0–1 ratio, but its shipped guidance says "overbought >80 / oversold <20". The snapshot printed `mfi: 0.9224` next to `rsi: 81.9118` — applying the documented rubric inverts the signal (reads 92 = deeply overbought as deeply oversold), contradicting the RSI beside it. Added `normalize_indicator_value()` in `stockstats_utils.py`, applied in `market_data_validator.py` and `y_finance.py`. The LAURUSLABS report happened not to cite MFI, so no past decision was corrupted — but it was live for any run that did. Tests: `tests/test_indicator_scaling.py`.

**Suite after this work: 342 passed, 4 failed** — the same 4 pre-existing ADX/DMI failures documented under "Known gap". Graphify resynced (1455 nodes / 2709 edges / 107 communities).

**Minor, not fixed (deliberately):** `.env` has keys written as `REDDIT_CLIENT_ID = ...`, so the parsed key carries a trailing space. `load_dotenv()` strips it, so it works today, but a direct `os.getenv` read would miss it. Left alone rather than editing a secrets file unprompted.

**Not verified end-to-end:** these fixes were each confirmed live at the fetcher level, but a full CLI run on an Indian ticker has not been done since. That is the natural next step.

### Follow-up: GDELT query fix (same session)

Investigating "how does each news source actually gather news" surfaced the **biggest single coverage bug so far**, in the same class as #3 above but in the vendor that matters most.

`gdelt_news.get_news()` built its query as `f'("{ticker.upper()}" OR "{ticker}")'`. For an already-uppercase ticker both halves are identical, and it searched the literal string `LAURUSLABS.BO` — which appears in no news article anywhere. GDELT is **first** in the `news_data` chain (`gdelt,yfinance,alpha_vantage,finnhub`), so the highest-reach source returned nothing for every Indian ticker and silently fell through to yfinance on every run.

Measured live, same date window:
- old query `("LAURUSLABS.BO" OR "LAURUSLABS.BO")` → **0 articles**
- new query `("LAURUSLABS" OR "Laurus Labs")` → **30 articles**, top hit *"Laurus Labs surges past Rs 1 lakh crore MCAP…"* dated **2026-08-05**

That story sits **inside the original 7-day window**, so the LAURUSLABS.BO run reported "no company-specific news" while a market-cap milestone was sitting in GDELT the whole time. The 30-day widening (#2) helped, but this bug alone caused that miss.

Fixed via new `news_search_terms()` in `company_names.py`, used by `gdelt_news._build_ticker_query()`. It differs from `company_search_terms()` deliberately: no `$` cashtag (a social convention absent from news prose) and no long company name when the suffix-stripped form already subsumes it as a phrase query. `company_search_terms` output is unchanged, so Reddit/India-RSS behaviour is untouched. Caching moved to `_resolved_parts` with a public `clear_caches()` helper so tests stop reaching into private symbols. Tests: `tests/test_gdelt_query.py`.

**Suite: 350 passed, 4 failed** (same ADX/DMI baseline). Graphify resynced (1478 nodes / 2775 edges / 98 communities).

**Known, not fixed — GDELT rate limiting.** GDELT returns HTTP 429 aggressively (hit repeatedly while testing). `route_to_vendor` treats `RequestException` as fallback-worthy for news methods, so a rate-limited GDELT silently falls through to yfinance with no retry and no visible warning in the report. The query fix only pays off on calls that aren't throttled. Adding modest backoff/retry in `_search_articles`, or surfacing "GDELT throttled" in the audit log, is the obvious next improvement.

**Also worth knowing:** `RSS_NEWS_VENDORS` in `interface.py` is an empty set, so the result-merging branch in `route_to_vendor` never executes — every news fetch returns the **first** vendor that succeeds and stops. You never get the union of gdelt + yfinance + alpha_vantage + finnhub. If yfinance returns 3 thin articles, that is the entire news picture for the run.

### Follow-up 2: GDELT retry + cross-vendor news merging (same session)

Both items flagged above are now done.

**GDELT rate-limit retry.** `_search_articles` retries HTTP 429/503 with exponential backoff (2s, 4s), honours `Retry-After` when it parses as seconds (capped at 30s), and logs each retry plus an explicit "giving up" line before raising — so a throttled GDELT is now visible in logs instead of vanishing into a silent vendor fallback. New config: `gdelt_max_retries` (2), `gdelt_retry_base_delay` (2.0), `gdelt_timeout_seconds` (15). Tests: `tests/test_gdelt_retry.py`.

⚠️ **Measured latency cost — do not trust the backoff numbers alone.** A fully-throttled GDELT fetch takes **~45s**, not the ~6s of sleep. GDELT does not reject fast while throttling: each attempt itself stalls ~13s (near the timeout), so the cost is 3 slow requests *plus* 2s+4s of sleep. I originally wrote "~6s worst case" in the config comment; that was wrong and has been corrected in place. Results are cached per (method, args) via `_cached_route_to_vendor`, so it is paid at most once per distinct fetch per run. Set `gdelt_max_retries: 0` to restore fast-fail if runs feel slow.

**Cross-vendor news merging.** `RSS_NEWS_VENDORS` (dead empty set) is gone, replaced by config key `merged_news_vendors: ["gdelt", "yfinance"]`. News results from those vendors are now UNIONED instead of first-wins. alpha_vantage and finnhub stay fallback-only: they need API keys and are US-centric, so merging them buys little India coverage for real latency and key-exhaustion risk.

Two implementation notes worth knowing if you touch this:
- The merge pass and the fallback pass now share one `_invoke_vendor()` helper. They previously had **separate copies** of the exception handling, and the copies had drifted — the merge pass caught only `AlphaVantageRateLimitError`, so enabling merging without this refactor would have reintroduced the exact crash-on-JSONDecodeError bug fixed earlier this session, just on a different code path.
- `merge_vendors` is gated on `method in NEWS_METHODS` at the point of construction, not only at the merge block. The fallback loop skips whatever is in `merge_vendors`; leaving it populated for a non-news method skipped those vendors in the loop while the merge pass never ran, silently dropping every configured vendor for `get_stock_data`. My own test caught this — keep `test_merging_only_applies_to_news_methods`.
- Absent config key ⇒ empty ⇒ first-wins preserved, so pre-existing configs do not silently start making an extra vendor call per fetch (`test_absent_merge_config_preserves_first_wins_behaviour`).

**Superseded — see "Follow-up 3" below.** Auditing a live TMPV.NS run showed two of the fixes above did not work as shipped.

**Not done:** cross-vendor de-duplication. GDELT and Yahoo can both carry the same story; each vendor's block keeps its own heading so the origin is visible, but an LLM could read one story reported twice as two independent corroborating sources. Worth addressing if it shows up in practice.

**Suite at that point: 4 failed, 210 passed** under `-m unit`. Same ADX/DMI baseline. On a full unmarked run a 5th failure appears — `test_deepseek_reasoning.py::TestDeepSeekLiveStructuredOutput::test_v4_flash_returns_structured_output` — which is a **live** DeepSeek API call returning `402 Insufficient Balance`. That is an account-billing state, not a code regression; it is unrelated to any change in this session. Graphify resynced (1511 nodes / 2868 edges / 89 communities).

### Follow-up 3: TMPV.NS audit — Reddit precision, GDELT retry correctness, news-path visibility

Auditing a live TMPV.NS run (2026-08-10 22:55, after the fixes above) confirmed several fixes working — MFI on 0–100, the 30-day company-news window, StockTwits `.NSE` returning 30 genuinely material messages (JLR margin-guidance cut, July PV sales +59% YoY, Sanand flood disruption, Stellantis talks), no duplicate tool calls, and zero hallucination (every figure traced to tool output; `Net Income: -16320000000` → "−₹16.3bn"). TMPV's 200-SMA is valid: Yahoo back-adjusts the ticker with 1,238 rows to 2021 despite the demerger.

It also exposed **two of my own fixes as broken in practice**, plus a structural news-path weakness.

**1. Reddit search results were unverified — a regression introduced by the earlier company-name fix.** The report listed "5 recent posts mentioning TMPV.NS" whose title and body contained neither "TMPV" nor "Tata". Reddit's `subreddit.search()` is not a filter — it ranks on its own relevance signals (comments, flair, image content) and returns loosely-related hits. The listing-scan leg had always applied a local substring check; **the search legs never did**, and that asymmetry was the bug. Previously it searched `"TMPV.NS"`, matched nothing, and the flaw stayed hidden; adding company-name queries turned "no results" into "wrong results", which is worse — wrong results reach the LLM as evidence. Fixed with `_post_mentions_ticker()`, now applied to all four paths (PRAW search, PRAW listing, JSON search, JSON listing). Verified: TMPV now returns 0 posts (honest) while RELIANCE.NS still returns 6 (not over-filtered). Tests in `tests/test_reddit_fetcher.py`.

**2. The GDELT retry could not succeed as configured.** Two independent defects:
   - `gdelt_retry_base_delay` was 2.0, producing 2s/4s waits — **both below GDELT's documented "one request every 5 seconds"**. A retry schedule under the published floor is not a retry, it is three guaranteed failures. Default is now 5.0, with `test_backoff_never_dips_below_gdelt_documented_floor` pinning it.
   - **GDELT signals throttling two ways**: HTTP 429, *and* HTTP 200 with a plain-text notice body. Only the 429 form was handled; the 200 form sailed into `response.json()` → `JSONDecodeError` → silent vendor fallback, so a throttled GDELT looked like a GDELT with no articles. Now detected via `_is_throttle_response()`, which raises `HTTPError` (a `RequestException`, so `route_to_vendor` still falls back cleanly).
   - Watch out: `"" in "{["` is `True` in Python, so the empty-body case must be tested **before** the JSON-prefix check. My own test caught this; `test_empty_body_is_treated_as_throttle_not_parsed` guards it.
   - Added a process-wide request spacer (`gdelt_min_request_interval`, default 5.0s, thread-safe). This is **preventive hygiene only**: measured 2026-08-10, once GDELT has blocked a caller, even 6s spacing keeps returning 429. It stops us *earning* a block; it cannot lift one.

**3. News path delivered nothing useful, and said so nowhere.** The only company-news article for TMPV was a **Mahindra & Mahindra** earnings story — a competitor — and with GDELT throttled the analyst had zero TMPV-specific institutional news. The genuinely market-moving facts reached the run only through the *sentiment* path (StockTwits), which is backwards. Two visibility fixes, both deliberately conservative:
   - `_company_specificity_note()` in `yfinance_news.py` reports how many articles actually name the company ("0 of 1 article(s) above explicitly name TMPV / Tata Motors Passenger Vehicles"). It **counts rather than labels individual articles on purpose** — an article may use a name we did not resolve (TMPV is written "Tata Motors" in the press), so per-article tagging would produce confident mislabels.
   - `route_to_vendor`'s merge pass now appends a coverage note when a merged vendor fails, so partial coverage is stated rather than hidden. Sentiment analysts already get this via `<stocktwits unavailable>` placeholders; news now does too. Without it, a thin single-vendor result reads to the analyst as "little news exists" instead of "one source was down".

India-RSS returning nothing for TMPV is genuine, not a matching bug: "Tata Motors" appears in **0** of today's 588 pooled articles, consistent with RSS latest-feeds only carrying ~24–48h.

**Suite: 4 failed, 226 passed** under `-m unit` — same ADX/DMI baseline. Graphify resynced (1553 nodes / 2985 edges / 108 communities).

**Still open:**
- GDELT remains blocked for this IP from testing bursts; the retry/spacing fixes are verified by unit tests and by live log output, but a clean live GDELT fetch has not been observed since the block. Re-check when it decays.
- `message_tool.log` truncates `[Data]` entries at 4000 chars with a sha256 stub (6 truncated in the TMPV run), so a full hallucination audit from the log alone is not possible for large fundamentals payloads.
- Cross-vendor de-duplication still not implemented.

### Follow-up 4: Google News vendor, NSE filings, StockTwits-as-news (2026-08-11)

Root fix for the news path. Each candidate source was measured before anything was written.

**Vendor comparison, measured 2026-08-11:**

| Source | Result for Indian tickers |
|---|---|
| Google News RSS search | **71** articles "Laurus Labs", **100** "Tata Motors Passenger Vehicles" |
| NSE corporate filings | Works — board meetings, announcements, corporate actions |
| Alpha Vantage NEWS_SENTIMENT | **Rejects Indian tickers**: `Invalid ticker format: TMPV.BSE` |
| Finnhub company-news | **HTTP 401 on every symbol** including AAPL |

**1. `google_news.py` — new primary company-news vendor.** Google News RSS *search*: arbitrary query, explicit `after:`/`before:` date range, India edition, no key. This is the only company-news source that is a search rather than a capped feed (Yahoo, ~12 max) or a throttled API (GDELT). The endpoint was **already in the codebase** in `india_news_feeds`, but aimed at a generic `india stock market when:1d` query — the mechanism existed and was simply never pointed at the company. Chain is now `google_news,yfinance,gdelt,alpha_vantage,finnhub`; `merged_news_vendors` is `["google_news", "yfinance"]`. GDELT is deliberately **not** merged: merging calls a vendor on every fetch and a throttled GDELT answers slowly (~13s/attempt), which would add ~45s per fetch while blocked. Three quality filters: publisher moved out of the `"Headline - Publisher"` title into the source field, redundant summaries blanked (Google's description is the headline repeated), and regional-language headlines dropped by a *proportional* Latin-script test (a naive non-ASCII test would discard legitimate headlines containing `₹`). Tests: `tests/test_google_news.py`.

Verified on the exact failing case — TMPV.NS went from **1 article (about Mahindra)** to **33 headings / 17.5k chars**, including "PV sales rise 59% to 63,760 units" and "Q1 Results: Earnings Call Scheduled for Aug 13".

**2. `nse_announcements.py` — exchange filings as a deterministic pre-fetch.** Every other source reports events second-hand; this is the filing itself. Requires cookie priming from the NSE homepage before its JSON API responds. Wired into `news_analyst` with prompt language stating that **a filing date outranks any date inferred from news or social posts**. Concrete justification: the TMPV run inferred "results on 12th August" from a Reddit comment; NSE's board-meeting filing says **13-Aug-2026**. Degrades to a placeholder on any failure. Tests: `tests/test_nse_announcements.py`.

**3. StockTwits added to the news analyst as an explicitly unverified lead source.** For Indian tickers its stream is heavily populated by news-wire accounts and it repeatedly carried material news the wire feeds missed entirely (TMPV: JLR margin-guidance cut, July PV sales, Sanand flooding). The prompt block marks it UNVERIFIED, requires attribution to social chatter, forbids overriding an exchange filing or dated article, and forbids computing sentiment from it (that is the sentiment analyst's job). Toggle: `news_include_stocktwits` / `news_stocktwits_limit`. The whole section is omitted when disabled or when the fetch returns a placeholder, so the model never sees an empty tag to explain.

**4. `rss.py` — shared RSS/Atom parsing** extracted from `india_news.py` so both fetchers use one parser. Fetching stays in each module so they cache and mock independently (the india_news tests patch `india_news.requests.get`).

**Finnhub is still broken.** The `.env` key loads correctly (40 chars, no whitespace, no system-env override) and Finnhub rejects it as `{"error":"Invalid API key"}` — including on `/quote`, a free-tier endpoint, so it is not a tier restriction. The key itself needs replacing.

**Also found:** both **Moneycontrol RSS feeds now return HTTP 403** (2 of 8 India feeds dead). Config comment corrected — it previously claimed all 8 were verified live. Live: Economic Times (76), CNBC-TV18 (200), Business Today (104), Google News India (100), Business Line (60), LiveMint (35).

**Suite: 4 failed, 247 passed** (`-m unit`) / **402 passed** unmarked — same ADX/DMI baseline, no regressions. Graphify resynced (1628 nodes / 3173 edges / 116 communities).

**Note for future edits:** `tests/test_dataflows_config.py` used to hardcode the news vendor chain string; it now derives from `DEFAULT_CONFIG` so re-ordering the chain no longer breaks an unrelated nested-update test.

### Follow-up 5: BLUEJET run audit (2026-08-11) — new sources validated, two merge bugs fixed

First run with the Google News / NSE-filings / StockTwits-as-news work in place. It validated the whole chain and exposed two bugs introduced by merging.

**Working as designed:**
- Google News delivered **30 company articles** (news_report.md 40KB vs TMPV's 20KB): Q1 FY27 results, ₹800cr QIP at ₹531.70 floor, ₹1,000cr/3yr capex, Motilal Oswal Buy TP ₹710, ICICI Buy TP ₹680, FII-outflow flag.
- NSE filings rendered all three sections, and the analyst **used them as intended** — it wrote "Q1 FY27 Results (Reported 03-Aug-2026; **NSE filing is authoritative for date**)", exactly the precedence the prompt asks for.
- StockTwits-as-news behaved **exactly** as the guardrail intends: every social claim is attributed and hedged, e.g. "(social wire, 04-Aug — uncorroborated, but consistent with company commentary…)" and "(social wire @wegro — uncorroborated lead…)". No social claim was promoted to fact.
- Reddit returned an honest zero (no false positives) — the `_post_mentions_ticker` fix holding.
- Ticker resolution worked: bare `BLUEJET` resolved to `BLUEJET.NS`; MFI 37.4 on the 0–100 scale; snapshot and bulk-deals each fetched once.
- No hallucination: ₹531.70, ₹710, ₹680, ₹2930M, ₹780M all trace to the tool log.

**Bug 1 — empty vendor messages were merged as content.** `_is_vendor_error_result` did not recognise yfinance's `"No news found for BLUEJET.NS between …"`, so under merging it counted as a successful payload and was concatenated **directly beneath 30 real articles**, ending the company-news block with a flat statement that no news existed. It also suppressed the partial-coverage note, since a "successful" vendor is never counted as failed. This was latent under first-wins (an unmatched empty message only delayed fallback) and only became harmful once merging landed. Fixed by replacing the ad-hoc conditions with an `_EMPTY_RESULT_PREFIXES` tuple that also covers `"no google news found"` and `"error fetching"`. Tests: `test_empty_vendor_message_is_not_merged_as_content`, plus a parametrised recogniser test and a guard that real content is not misclassified.

**Bug 2 — StockTwits fetched twice per run.** The sentiment analyst requests `limit=30`, the news analyst was requesting `limit=20`; `fetch_stocktwits_messages` is `lru_cache`d on `(ticker, limit, timeout)`, so the differing limit was a cache miss and cost a second real network call for a subset of the same data. `news_stocktwits_limit` now defaults to 30 so the second call is a cache hit.

Verified post-fix on the same ticker/window: 30 Google News articles, no stray "No news found", coverage note correctly present.

**Suite: 4 failed, 409 passed** — same ADX/DMI baseline. Graphify resynced (1631 nodes / 3182 edges).

**Known cosmetic issue, not fixed:** the run's log directory is `logs/BLUEJET/` (raw user input) while the analysis correctly used `BLUEJET.NS`. Ticker resolution happens after the log path is chosen, so running the same company as `BLUEJET` and as `BLUEJET.NS` writes to two different directories and splits the memory/reflection history. Harmless for a single run; worth unifying if per-ticker history matters.

### Follow-up 6: one resolved ticker identity per run (2026-08-11)

Fixes the split-identity issue noted at the end of Follow-up 5. It was **wider than just the log directory** — ticker resolution happened inside `create_initial_state()`, i.e. *after* every other identity had already been derived from the raw user input.

Everything that keyed off the unresolved ticker:
- `cli/main.py` — the results/log directory (`results/BLUEJET/` while analysing `BLUEJET.NS`)
- `trading_graph.propagate()` — `self.ticker` (names the state-log directory), the checkpoint thread id, and `_resolve_pending_entries`
- `trading_graph._run_graph()` — `memory_log.get_past_context()` and `memory_log.store_decision()`

The memory-log consequence was the real one: a run could **read its history under one name and write it under another**, so deferred reflection never saw its own prior decisions when the ticker was typed differently between runs.

**Fix — resolve once, at each entry point, before anything derives an identity from it:**
- `cli/main.py`: `resolved_ticker` computed before `results_dir` is built, then used for the results path, `create_initial_state`, the spinner, the saved-report folder and `save_report_to_disk`.
- `trading_graph.propagate()`: `company_name = resolve_ticker_symbol(...)` on the first line, so `self.ticker`, pending entries, the checkpoint id, the memory log and `_run_graph` all inherit the resolved form. One line covers the whole programmatic path.

`resolve_ticker_symbol` is `lru_cache`d, so `create_initial_state`'s own call is a cache hit returning the identical value — no extra network round-trip, and no way for the two to disagree.

**Also fixed while here:** `cli/main.py` built its results path from the ticker **without** `safe_ticker_component()`, the only results-path construction site missing that validation (`trading_graph.py` already applied it). Now applied — verified that `../../etc/passwd` raises rather than escaping the results directory.

**Also improved:** the CLI now reports resolution when it changes the symbol — `"Selected ticker: BLUEJET (resolved to BLUEJET.NS)"` — since the entire run, every report and the results directory use the resolved form.

Verified: `BLUEJET` and `BLUEJET.NS` now both produce `results/BLUEJET.NS/2026-08-11`. Tests: `tests/test_ticker_identity_consistency.py` (6 tests, covering resolution before identity assignment, memory-log read/write agreement, pending entries, initial state, the already-suffixed case, and fail-open on an unresolvable ticker).

**Suite: 4 failed, 415 passed** — same ADX/DMI baseline. Graphify resynced (1642 nodes / 3228 edges).

### Follow-up 7: log-noise cleanup (2026-08-11)

A BLUEJET run completed correctly and produced a good report, but printed ~45 lines of alarming failure text. None of it indicated a real problem. That is worse than useless — noise that fires on every run trains you to ignore the log, so the one line that matters gets skipped too. All three sources diagnosed and fixed; **no behaviour changed, only which failures are real.**

**1. `HTTP Error 404: Quote not found for symbol: BLUEJET`** — this was ticker resolution *working*. `resolve_ticker_symbol` probes Yahoo with `BLUEJET`, then `BLUEJET.NS`, and stops at the first hit; the bare-symbol miss is the expected answer. yfinance logs each miss to **stderr itself** (confirmed by capturing stderr — our own handler was already at debug), so every run using a bare ticker opened with a 404 despite resolving fine. Fixed with a `_muted_logger("yfinance")` context manager around the probe loop only, restoring the previous level in a `finally` so a leak can never permanently hide real yfinance errors.

**2. 42 lines of `Reddit JSON fetch failed: Expecting value: line 2 column 5 (char 5)`** — two compounding causes:
   - **Root cause of the parse error:** `old.reddit.com` answers **HTTP 200 with an HTML body**. The `{403, 429}` guard doesn't catch it (status is 200), `raise_for_status()` passes, and `.json()` then fails at "line 2 column 5" — which is literally the `<` of `<!DOCTYPE html>` on the second line. (`www.reddit.com` returns a clean 403 and was always skipped silently.) Now detected up front by `_json_payload_or_none()`, which checks status *and* Content-Type, so a block reads as a block.
   - **Root cause of the volume:** the fallback ran on a legitimate zero result. `if not posts: posts = _fetch_subreddit_json(...)` treated "PRAW ran and found nothing" the same as "PRAW unavailable", so every quiet ticker retried a dead public API across all 7 subreddits — 6 failed requests each. An authenticated PRAW query that *ran* is now authoritative; the JSON path is reserved for the case it was written for (no credentials), where it logs one honest line naming the missing env vars.

   Measured after: **42 warning lines → 0**, with the same correct result (`<no Reddit posts found mentioning BLUEJET.NS ...>`).

**3. Moneycontrol 403 ×2** — both feeds **removed** from `india_news_feeds`. They return HTTP 403 (Moneycontrol blocks this User-Agent), contributed zero articles, and cost a request, a timeout budget and a warning on every run. Pool is 6 feeds / ~560 articles, RSS warnings now 0. URLs are recorded in the config comment if Moneycontrol ever unblocks.

Tests: `tests/test_log_noise.py` (8 tests) covering mute/restore including on exception, the HTML-200 detection, the 403 case, genuine JSON still parsing, PRAW-zero not triggering the fallback, and the no-credentials path still using it.

**Suite: 4 failed, 423 passed** — same ADX/DMI baseline. Graphify resynced (1658 nodes / 3270 edges).

Note: `tests/test_reddit_fetcher.py::test_reddit_fetcher_uses_json_fallback_when_praw_unavailable` needed a realistic `Content-Type` header on its mock response, since the fetcher now uses that header to distinguish a real payload from Reddit's HTML block page.

### Follow-up 8: `[Data]` payloads missing from the audit log (2026-08-11)

Found while counting BLUEJET's news sources. The run logged **26 `[Tool Call]` lines but only 16 `[Data]` lines**, and the 16 map exactly onto the LLM's own ReAct calls (get_stock_data, get_indicators ×8, fundamentals, balance sheet ×2, cashflow ×2, income statement ×2) — which take a different code path. **All 10 deterministic pre-fetches recorded that they ran but not what they returned:** the market snapshot, get_news, get_global_news, both StockTwits calls, Reddit, India RSS, NSE filings and bulk deals.

**Root cause — a regression from fix #8 earlier in this session.** `run_analysis` replaces `MessageBuffer.add_tool_call` on the instance with `save_tool_call_decorator`'s wrapper, so that wrapper *is* `add_tool_call` for every caller. The wrapper never returned `added` (bare `return` on the dedup branch, implicit `None` on the success branch). Fix #8 had gated the `[Data]` write on that return value:

```python
is_new_call = message_buffer.add_tool_call(name, args)   # always None
if is_new_call:                                          # always False
    message_buffer.add_message("Data", str(result))      # never runs
```

So instead of *deduping* the `[Data]` lines, it suppressed them entirely for every pre-fetch. Fixed by returning `added` on both branches.

**Why the tests missed it:** `test_audit_call_data_message_not_duplicated_on_repeat_chunk` and friends exercise `MessageBuffer` **directly, undecorated**, where `add_tool_call` correctly returns a bool. The decorator is applied only inside `run_analysis`, which has no unit test. New `tests/test_tool_call_decorator.py` reproduces the decorator locally and asserts the return value survives it, that each distinct pre-fetch gets its `[Data]` line, and that repeats are still suppressed.

**Impact:** no effect on analysis quality or on any report — the data still reached the prompts, and reports were correct. The damage was purely to auditability: the LAURUSLABS hallucination audit earlier in this session worked by tracing report claims back to `[Data]` payloads, and that had silently stopped being possible for exactly the sources that matter most (news, filings, social).

**Suite: 4 failed, 427 passed** — same ADX/DMI baseline. Graphify resynced.

### Follow-up 9: token-reduction port from a sibling TradingAgents repo (2026-08-11)

User supplied a (garbled/OCR'd) change document from a similar TradingAgents fork describing 12 token-reduction changes, and asked for them to be adapted to this repo — explicitly authorizing improvisation since the repos have diverged. Read every touched file's *current* state first via graphify + Read before changing anything, since several of the 12 target files had already been substantially rewritten earlier in this session (market_analyst.py, news_analyst.py, sentiment_analyst.py all had prior fixes this doc's author's repo never had).

**Skipped entirely, on the user's explicit instruction:** change #1 (alpha_vantage_news.py cap + compact format). Confirmed earlier this session that Alpha Vantage rejects Indian tickers outright (`Invalid ticker format: TMPV.BSE`), so this vendor never fires for this repo's actual traffic — the user said to ignore it rather than spend effort compacting a response that's never returned.

**#2 — sentiment_analyst.py News Block dedupe.** sentiment_analyst and news_analyst both fetch the identical ticker + `company_news_lookback_days` window, so sentiment_report was duplicating ~30 articles news_report already carried. Replaced the disk/state-facing `### News Block` with a one-line pointer note (`_article_count()` helper counts headings for the note's article-count claim). The LLM's own prompt is untouched (still reasons over the full block) and `audit_tool_calls` still logs the full result — only the copy that gets resent whole into `state["sentiment_report"]` (which itself gets resent into all 5 debate/risk nodes) was trimmed.

**#3-5 — `news_synthesis`.** The real lever. news_analyst's prompt now explicitly requires a self-sufficient compact format — narrative + `### Coverage` (one bullet per material item, `[source, date]: highlight`) + `### Bullish Points` / `### Bearish Points` — because its *entire* output now replaces the 5 nodes' access to news. Adapted the "1-2 bullets per article, full coverage of every article" instruction from the source doc: with 5 pre-fetched blocks (~105 items on a rich run), literal per-article bullets wouldn't compress much, so company-specific items (Google News, NSE filings, social wire — the sources nothing else can recover) get full coverage while the prompt explicitly instructs merging near-duplicate macro/global headlines (the Hormuz/oil-price repetition observed on the BLUEJET and TMPV runs) into one bullet instead of five. `result.content` is stored as `news_synthesis`; `news_report` (raw blocks + the same analysis) is unchanged, still the disk/CLI record and hallucination-audit trail. Added the field to `AgentState` and `create_initial_state`. Measured live: **174 chars vs 23,960** for the full report on the same identical run — a ~137x reduction in what 5 separate LLM calls now resend per round.

**#6-10 — switch to `news_synthesis` + static/dynamic prompt-cache split, across bull_researcher, bear_researcher, aggressive/neutral/conservative_debator.** Two independent changes per file:
- `news_report = state["news_report"]` → `state["news_synthesis"]` (one-line diff, matching the source doc exactly).
- Each prompt split into `static_context` (role framing + all 4 reports — byte-identical across every round of a debate) and `dynamic_context` (history + opponents' latest arguments — changes every round), concatenated in that exact order to reproduce the original single-string prompt. For the 3 risk debators, `trader_investment_plan` also moved into `static_context`, per the source doc's explicit note — the trader runs once before the risk debate starts, so its decision doesn't change across rounds either.
- Each risk debator only reads its *other two* opponents' responses, never its own current response (an output, not an input) — worth knowing if extending this pattern, since a test that assumed all three opponent markers land in every debator's dynamic block would be wrong for all three files.

**#11 — `tradingagents/agents/utils/prompt_caching.py` (new file).** `invoke_with_cache_breakpoint(llm, static, dynamic)`: for `ChatAnthropic` (confirmed `NormalizedChatAnthropic` subclasses it, so `isinstance` works), sends a `HumanMessage` with two text blocks, `cache_control: {"type": "ephemeral"}` on the static one only. Every other provider — this repo's default is DeepSeek, confirmed via `default_config.py` — gets `llm.invoke(static + dynamic)`, byte-identical to the pre-split behavior. Documented the real caveat: Anthropic's minimum cacheable block size is model-dependent (~1024-2048 tokens); a thin static block on an early debate round may not actually get cached even with the breakpoint set — not an error, just no benefit that round.

**#12 — market_analyst.py `get_indicators` removal, WITH the source doc's own caveat resolved rather than accepted.** The source doc flagged that `get_indicators` returns day-by-day indicator history while the verified snapshot only had a single latest value, and suggested holding off or fixing both together. Fixed both together: added a `TREND_INDICATORS` (`rsi`, `macd`, `macds`, `macdh` — the momentum indicators where direction matters, not the full 13-indicator `SNAPSHOT_INDICATORS` list, which would have recreated the exact bloat this is meant to avoid) + `TREND_WINDOW_DAYS` (10 sessions) section in `market_data_validator.build_verified_market_snapshot`, via new `_calculate_trend_history()`. Verified live on TMPV.NS: RSI 37.7→55.2 and MACD histogram crossing negative-to-positive around session 3 — a visible crossover, exactly what would otherwise have been lost. Only then removed `get_indicators` from market_analyst.py's `tools` list, the `_create_tool_nodes()["market"]` `ToolNode` registration, and the now-unused import in `trading_graph.py`; rewrote the prompt instruction accordingly. `get_stock_data` remains available for raw OHLCV beyond the snapshot's own window.

**Verification:** full suite before starting (baseline: 4 pre-existing ADX/DMI failures, unrelated) → **467 passed, 4 failed** after all 12 (10 implemented + 1 skipped + re-verified baseline) changes, same baseline, zero regressions. Two live end-to-end checks beyond unit mocks: (1) `news_analyst` → `bull_researcher`, confirming `news_synthesis` (174 chars) reaches the bull prompt while `news_report`'s raw `prefetched_company_news` marker does not; (2) `market_analyst`, confirming `bind_tools` receives only `['get_stock_data']` and `market_report` contains the new `Indicator Trend` section. New test files: `test_news_synthesis.py`, `test_prompt_caching.py`, `test_debate_static_dynamic_split.py`, plus extensions to `test_market_data_validator.py`; updated `test_evidence_guardrails.py` and `test_tool_routing.py` for the two intentional wording/behavior changes.

**One test-writing pitfall worth remembering:** don't assert "RSI must increase as price increases" — RSI is a momentum oscillator and legitimately dips on a local pullback during an overall uptrend. Test date-ordering directly (`_calculate_trend_history`'s own `dates` list) instead of trying to derive directional guarantees from real indicator math.

Graphify resynced (1727 nodes / 3407 edges / 103 communities).
