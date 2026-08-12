import copy
import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_OPENROUTER_REASONING_EFFORT": "openrouter_reasoning_effort",
    "TRADINGAGENTS_OPENROUTER_MAX_COMPLETION_TOKENS": "openrouter_max_completion_tokens",
    "TRADINGAGENTS_OPENROUTER_TEMPERATURE": "openrouter_temperature",
    "TRADINGAGENTS_OPENROUTER_TOP_P": "openrouter_top_p",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    "TRADINGAGENTS_LLM_TEMPERATURE":      "llm_temperature",
    "TRADINGAGENTS_LLM_SEED":             "llm_seed",
}


def _coerce(value: str, reference):
    if isinstance(reference, bool):
        return value.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        config[key] = _coerce(raw, config.get(key))
    return config


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    "memory_log_max_entries": None,

    # LLM settings
    "llm_provider": "deepseek",
    "deep_think_llm": "deepseek-v4-flash",
    "quick_think_llm": "deepseek-v4-flash",
    "backend_url": None,

    # Provider-specific thinking configuration
    "google_thinking_level": None,
    "openai_reasoning_effort": None,
    "anthropic_effort": None,
    "openrouter_reasoning_effort": "xhigh",
    "openrouter_max_completion_tokens": 8192,
    "openrouter_temperature": 0.2,
    "openrouter_top_p": 0.9,

    # Sampling controls, applied to every provider by
    # TradingAgentsGraph._get_provider_kwargs. Before these existed only
    # openrouter set temperature, so every other provider sampled at its own
    # default (~1.0) with no seed and identical runs returned opposite
    # verdicts (LICI.NS 2026-08-11: two default runs 12 minutes apart gave
    # HOLD then BUY).
    #
    # 0.2 rather than 0.0 deliberately: the bull/bear and 3-way risk debates
    # are adversarial, and a fully greedy decode makes the opposing agents
    # converge on near-identical phrasing, which weakens the disagreement the
    # structure exists to produce. Set to 0.0 if you want maximum determinism
    # and are willing to trade that.
    #
    # Seeds are honoured by OpenAI-compatible endpoints; Anthropic and Google
    # expose no seed parameter, so temperature is the only lever there. NO
    # provider guarantees bitwise reproducibility even with both set.
    "llm_temperature": 0.2,
    "llm_seed": 42,

    # Freeze fetched news/social/filings per (ticker, analysis date) so a
    # re-run replays identical inputs. See dataflows/snapshot_cache.py for the
    # measurement that motivated it. Set False (or pass --refresh) to pull
    # fresh data; a different analysis date is a different key either way, so
    # daily runs are unaffected.
    "snapshot_cache_enabled": True,

    "checkpoint_enabled": False,
    "output_language": "English",

    # Debate and discussion settings
    "max_debate_rounds": 2,
    "max_risk_discuss_rounds": 2,
    "max_recur_limit": 180,
    "analyst_concurrency_limit": 1,

    # News / data fetching parameters
    "news_article_limit": 30,
    "global_news_article_limit": 20,
    "global_news_lookback_days": 7,

    # Hard ceiling on tokens the model may GENERATE per call. None = no cap
    # (previous behaviour for every provider except openrouter, which had its
    # own openrouter_max_completion_tokens).
    #
    # This is the only DETERMINISTIC lever on run time. Wall-clock is
    # dominated by output-token generation, not input size or network: a
    # measured default run produced ~8,400 words (~11k tokens) of analyst
    # prose alone, before the 8 debate/manager calls, and at a typical
    # ~30-50 tok/s that alone is most of a 10-minute run. Prompt wording
    # ("be concise") is only a request a model may ignore; max_tokens is
    # enforced by the API.
    #
    # Deliberately set as a generous SAFETY CEILING, not the primary lever:
    # the concise prompts target ~250-350 words (~350-470 tokens), so a
    # compliant response never reaches the cap and is never truncated
    # mid-sentence. It only stops a runaway. This matters most for the
    # structured-output agents (sentiment, research manager, trader,
    # portfolio manager) — truncated JSON fails to parse, falls back to a
    # SECOND full free-text call, and would make a run slower, not faster.
    "max_output_tokens": None,

    # "detailed" (default) reproduces the original verbose report-writing
    # instructions verbatim in every analyst prompt. "concise" is read by
    # market/fundamentals/news/sentiment analysts to request a shorter
    # write-up instead — see get_fast_config() below. Evidence/citation
    # discipline in those prompts is separate instruction text, not gated by
    # this flag, so accuracy guardrails are identical either way.
    "report_style": "detailed",

    # None = use tradingagents.dataflows.reddit.DEFAULT_SUBREDDITS (all 7).
    # get_fast_config() narrows this to the top 3 by subscriber count.
    "reddit_subreddits": None,

    # How far back company-specific news is collected. Deliberately much
    # wider than the 7-day global window: Indian mid- and small-caps get
    # sparse English-language coverage, so a 7-day window routinely returned
    # "no news found" for companies that did have material recent news.
    # LAURUSLABS.BO on 2026-08-10 is the worked example — Yahoo carried a
    # Q1 FY27 earnings-call report dated 2026-07-24 (17 days back, the single
    # most decision-relevant item available), and the 7-day window discarded
    # it, leaving the news and sentiment analysts with nothing to reason from.
    # Articles stay newest-first and each is dated in the prompt, so the
    # analyst can still weight recency itself.
    "company_news_lookback_days": 30,

    # News vendors whose results are UNIONED rather than first-wins.
    # route_to_vendor normally returns the first vendor that succeeds and
    # stops, so a thin yfinance response (Yahoo caps company news at ~12
    # articles regardless of the count requested) became the entire news
    # picture for a run and gdelt/alpha_vantage/finnhub were never consulted.
    # These two are unioned because both are no-key and complementary: GDELT
    # is a broad global web-news index, Yahoo carries the exchange-linked
    # company wire. alpha_vantage and finnhub stay fallback-only — they need
    # API keys and are US-market-centric, so merging them adds latency and
    # key-exhaustion risk for little India coverage.
    # Cost: both vendors are called on every news fetch instead of one.
    # google_news + yfinance are unioned: the search source supplies breadth,
    # Yahoo supplies the exchange-linked company wire. gdelt is deliberately
    # NOT merged — merging calls a vendor on every news fetch, and GDELT
    # answers a throttled request slowly (~13s each, measured), so including
    # it would add ~45s per fetch while blocked. It stays in the chain as a
    # fallback for when the other two return nothing.
    "merged_news_vendors": ["google_news", "yfinance"],

    # GDELT throttling (HTTP 429) is common and, being first in the vendor
    # chain, silently cost us the best source on every throttled call.
    #
    # Cost when throttled, MEASURED (2026-08-10), not estimated: ~45s for a
    # fully-throttled fetch, not the ~6s of backoff alone. GDELT does not
    # reject fast while throttling — each attempt itself stalls ~13s, near
    # the timeout — so the real cost is 3 slow requests plus 2s+4s of sleep.
    # Results are cached per (method, args), so this is paid at most once per
    # distinct fetch per run, and route_to_vendor still falls back to
    # yfinance afterwards.
    #
    # Tuning: set gdelt_max_retries to 0 to restore the previous fast-fail
    # behaviour (GDELT skipped the moment it throttles), or lower
    # gdelt_timeout_seconds to bound each individual attempt.
    #
    # base_delay MUST stay >= 5.0: GDELT documents "one request every 5
    # seconds", so the earlier 2.0 produced 2s/4s waits that were both under
    # its own floor and therefore guaranteed to be refused again. A retry
    # schedule below the documented limit is not a retry, it is three
    # guaranteed failures.
    "gdelt_max_retries": 2,
    "gdelt_retry_base_delay": 5.0,
    "gdelt_timeout_seconds": 15,

    # Minimum spacing between any two GDELT requests, process-wide. A run
    # issues get_news + get_global_news, and merging means GDELT is hit on
    # every news fetch — unspaced that is a burst, and bursts earn a sustained
    # block rather than a single retryable 429. Set to 0 to disable.
    "gdelt_min_request_interval": 5.0,

    # -----------------------------------------------------------------------
    # India-market focused global news queries.
    # These target the macro and structural drivers that move Indian
    # equities: RBI policy/rate cycle, Nifty/Sensex-level flows, INR moves,
    # FII/DII positioning, and Budget/GST/regulatory catalysts.
    # -----------------------------------------------------------------------
      "global_news_queries": [
        "RBI monetary policy repo rate India interest rates",
        "Nifty Sensex index rally correction FII selling",
        "rupee INR depreciation exchange rate RBI intervention",
        "FII DII flows Indian equities institutional buying selling",
        "Union Budget GST regulatory reform India economy",
    ],

    # -----------------------------------------------------------------------
    # Supplemental India financial-news RSS feeds (no API key required).
    # Consumed by tradingagents.dataflows.india_news for promoter-action,
    # regulatory, and sector context that global finance vendors often lag
    # on.
    #
    # Health check 2026-08-11, article counts in parentheses: Economic Times
    # (76), CNBC-TV18 (200), Business Today (104), Google News India (100),
    # Business Line (60), LiveMint (35).
    #
    # Both Moneycontrol feeds were REMOVED: they return HTTP 403 (Moneycontrol
    # blocks this User-Agent) and contributed zero articles while logging a
    # warning on every single run. A permanently-blocked feed is pure cost —
    # a request, a timeout budget and a scary log line for nothing. Re-add
    # them if Moneycontrol stops blocking; the URLs were
    # http://www.moneycontrol.com/rss/latestnews.xml and
    # https://www.moneycontrol.com/rss/results.xml. The original
    # Business Standard and Financial Express feed URLs both went dead
    # (403 / 410) and were replaced with LiveMint and CNBC-TV18 below —
    # both confirmed live with genuinely relevant content. Source
    # legitimacy: all mainstream, established Indian financial/business
    # press (Network18, Times Group, HT Media, The Hindu Group, India
    # Today Group) plus Google News as a resilient, broadly-sourced
    # aggregator — no fringe/unverified outlets.
    # -----------------------------------------------------------------------
    "india_news_feeds": [
        {"name": "Economic Times", "url": "https://economictimes.indiatimes.com/rssfeedsdefault.cms"},
        {"name": "LiveMint Markets", "url": "https://www.livemint.com/rss/markets"},
        {"name": "CNBC-TV18 Market", "url": "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml"},
        {"name": "Business Line", "url": "https://www.thehindubusinessline.com/feeder/default.rss"},
        {"name": "Business Today Markets", "url": "https://www.businesstoday.in/rss/markets"},
        {"name": "Google News India Markets", "url": "https://news.google.com/rss/search?q=india+stock+market+when:1d&hl=en-IN&gl=IN&ceid=IN:en"},
    ],
    "india_news_article_limit": 8,

    # NSE corporate filings (no key). Exchange-filed board meetings, results
    # dates and corporate actions — the authoritative version of events that
    # news and social sources only report second-hand. Worked example: the
    # TMPV.NS run inferred "results on 12th August" from a Reddit comment;
    # NSE's own board-meeting filing says 13-Aug-2026.
    "nse_announcement_limit": 6,
    "nse_timeout_seconds": 15,
    "google_news_timeout_seconds": 15,
    "global_india_news_article_limit": 10,

    # -----------------------------------------------------------------------
    # Promoter/large-holder bulk-deal activity (NSE, no API key required).
    # Consumed by tradingagents.dataflows.india_insider as a proxy for
    # insider/promoter activity, since India's SEBI disclosure regime isn't
    # exposed by yfinance the way US Form-4 data is. Verified live and
    # working during implementation (unlike the india_news_feeds RSS URLs,
    # which are unverified).
    # -----------------------------------------------------------------------
    "promoter_bulk_deals_limit": 15,

    # -----------------------------------------------------------------------
    # Data vendor configuration
    # news_data uses a comma-separated fallback chain, ordered for India
    # coverage. Order changed 2026-08-11 after measuring each vendor against
    # the two runs that reported "no company news":
    #   1. google_news - RSS *search*: arbitrary query, explicit date range,
    #      India edition, no key. Measured 71 articles for "Laurus Labs" and
    #      100 for "Tata Motors Passenger Vehicles" over 30 days, versus the
    #      single competitor story yfinance returned for TMPV.NS. Promoted to
    #      primary because it is the only company-news source that is a search
    #      rather than a capped feed or a throttled API.
    #   2. yfinance - Yahoo per-symbol feed; hard-capped near 12 articles
    #      regardless of the count requested, and its ticker feed mixes in
    #      sector/peer stories (see _company_specificity_note).
    #   3. gdelt - genuinely global web-news API and the only other true
    #      search, but demoted: it throttles aggressively (HTTP 429 plus a
    #      200-with-plain-text form) and can stay blocked for long stretches,
    #      so it cannot be depended on for company news.
    #   4. alpha_vantage - REJECTS Indian tickers outright ("Invalid ticker
    #      format: TMPV.BSE"); useful only for US-listed symbols.
    #   5. finnhub - free tier is US/major-market-centric.
    #
    # technical_indicators defaults to yfinance (local stockstats computation,
    # no external quota) because the free Alpha Vantage key is capped at
    # 25 requests/day / 1 req/sec, and a single market-analyst pass requests
    # ~10+ indicators — enough to exhaust that quota on its own. alpha_vantage
    # remains available as an automatic fallback for premium-key users.
    # -----------------------------------------------------------------------
    "data_vendors": {
        "core_stock_apis":      "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data":     "yfinance",
        "news_data":            "google_news,yfinance,gdelt,alpha_vantage,finnhub",
    },

    # Tool-level overrides (takes precedence over category-level above)
    "tool_vendors": {
        "get_global_news": "gdelt,yfinance,alpha_vantage,finnhub",
    },

    # Benchmark — SPY is the fallback for tickers with no exchange suffix.
    # NSE (.NS) and BSE (.BO) tickers already resolve to ^NSEI/^BSESN via
    # benchmark_map below with no config change needed; only set
    # benchmark_ticker to force one fixed benchmark across all runs.
    "benchmark_ticker": None,
    "benchmark_map": {
        ".NS":  "^NSEI",
        ".BO":  "^BSESN",
        ".T":   "^N225",
        ".HK":  "^HSI",
        ".L":   "^FTSE",
        ".TO":  "^GSPTSE",
        ".AX":  "^AXJO",
        "":     "SPY",
    },
})


# -----------------------------------------------------------------------
# Fast platform profile — trims wall-clock time for interactive/retail-
# platform use where a 10+ minute run is unacceptable, while keeping every
# accuracy/evidence guardrail from DEFAULT_CONFIG intact: the citation,
# "don't invent numbers", and filing-over-rumor precedence instructions in
# each analyst prompt are separate text, untouched by anything below.
#
# Opt-in and additive: DEFAULT_CONFIG is never mutated, and nothing here
# applies unless a caller explicitly requests get_fast_config(). What
# changed and why:
#
#   * max_debate_rounds / max_risk_discuss_rounds: 2 -> 1. This is the
#     single biggest lever: it halves the two sequential debate phases from
#     4+6=10 LLM calls to 2+3=5. Each call in a debate must wait for the
#     previous one to finish (no parallelism is possible there by graph
#     structure), so this trims wall-clock time directly, not just cost.
#     At 1 round the bull/bear debate is still a full argument-and-rebuttal
#     exchange (bear responds to the specific bull argument, not a vacuum),
#     and the risk debate still gives all 3 analysts one full turn each —
#     what's cut is the second iteration, not the debate itself.
#   * report_style: "concise" — the analyst prompts request a shorter
#     write-up. Shorter requested output means less generation wall-time,
#     and is what a retail-platform UI actually wants over an exhaustive
#     research report.
#
# THE INVARIANT (revised 2026-08-12): fast mode changes only how the work is
# SCHEDULED. It must not change what the model sees, nor how much it writes.
#
# The earlier version of this profile also shortened the output
# (`report_style = "concise"`, `max_output_tokens = 1400`). That was removed
# because **for an LLM, output length IS reasoning depth** — the model reasons
# in the tokens it writes, so a word cap does not merely compress the write-up,
# it forces a SELECTION, and qualifying facts lose to newsworthy ones.
#
# The worked example, SIEMENS.NS 2026-08-12 (fast 11:00 vs detailed 11:16, one
# debate round each, identical data — so the cap was the only variable):
#   * The concise news template allows "8 bullets MAXIMUM, one line each" and
#     forbids the summary table. The fast run's Coverage hit exactly 8.
#   * The 07-Apr-2025 Demerger filing lost its slot to a fresher headline,
#     while "Siemens Energy gas-turbine backlog ~70 GW" kept one.
#   * With the disqualifying fact gone, the fast run then wrote, as a BULLISH
#     point: "Sister co Siemens Energy India Q1 profit +70% signals group
#     demand strength" — crediting a company that was demerged away in 2025.
#   * The detailed run had room for the demerger bullet AND the table, tagged
#     its rows "(separate entity)", and inverted the inference: the ecosystem
#     is booming "yet Siemens Limited's core profit is falling".
#
# One line each is enough to ASSERT a fact but not to QUALIFY it. That is the
# whole difference. Restoring full-length prompts costs wall-clock and buys
# back the reasoning; the user chose depth over latency.
#
# Article caps (news/global/india), the reddit_subreddits narrowing and the
# gdelt removal used to live here and violated that. They were reverted on
# 2026-08-12 after the SIEMENS.NS comparison: input size is not what costs
# wall-clock time (output generation is — see PERF_HANDOFF.md), so starving
# the inputs bought very little speed while making fast and detailed runs
# genuinely incomparable. If you are tempted to re-add an input trim to buy
# latency, measure it first; the last set was not worth what it cost.
#
# The one asymmetry that remains is unavoidable and is NOT a data trim:
# analysts run concurrently rather than chained.
# -----------------------------------------------------------------------


def get_fast_config() -> dict:
    """Return a deep copy of DEFAULT_CONFIG with the fast platform profile applied.

    Deep-copied (not a shallow ``{**DEFAULT_CONFIG, **overrides}`` spread) so
    the nested ``data_vendors``/``tool_vendors`` dicts can never be mutated on
    DEFAULT_CONFIG itself, and so a future top-level override cannot silently
    clobber sibling keys inside them (replacing the whole ``data_vendors``
    dict would also delete ``core_stock_apis``/``technical_indicators``/
    ``fundamental_data``, breaking price and fundamentals data entirely).

    Every key set below affects output length or scheduling only. No key here
    reduces the data fetched — see the invariant above.
    """
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    # Run the four analysts concurrently instead of chained. They are
    # independent (each needs only ticker + date, none reads another's
    # report) and each now owns its own message channel, so this is a pure
    # latency win: the analyst phase collapses from the sum of four LLM
    # round-trips to roughly the slowest one. Set back to 1 to restore the
    # sequential chain.
    #
    # This is now the ONLY lever left, and deliberately so. `report_style =
    # "concise"` and `max_output_tokens = 1400` used to live here and were
    # removed on 2026-08-12 — see the note below.
    config["analyst_concurrency_limit"] = 4
    # "balanced", not "concise": length discipline, but the coverage-bullet cap
    # is raised and the summary tables are kept. Those two structural
    # allowances — not raw word count — are what the SIEMENS.NS demerger
    # failure actually turned on. See agent_utils._BALANCED_WORD_SCALE.
    config["report_style"] = "balanced"
    return config
