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
    "TRADINGAGENTS_OPENROUTER_EXACTO": "openrouter_exacto",
    "TRADINGAGENTS_OPENROUTER_QUANTIZATIONS": "openrouter_quantizations",
    "TRADINGAGENTS_OPENROUTER_ONLY_PROVIDERS": "openrouter_only_providers",
    "TRADINGAGENTS_OPENROUTER_IGNORE_PROVIDERS": "openrouter_ignore_providers",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_OHLCV_CACHE_FRESHNESS_CHECK": "ohlcv_cache_freshness_check",
    "TRADINGAGENTS_OHLCV_CACHE_RECHECK_SECONDS": "ohlcv_cache_recheck_seconds",
    "TRADINGAGENTS_BALANCED_WORD_SCALE": "balanced_word_scale",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    "TRADINGAGENTS_LLM_TEMPERATURE":      "llm_temperature",
    "TRADINGAGENTS_LLM_SEED":             "llm_seed",
    "TRADINGAGENTS_LLM_TIMEOUT_SECONDS":  "llm_timeout_seconds",
}


def _coerce(value: str, reference):
    if isinstance(reference, bool):
        return value.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    # List-valued settings (openrouter_quantizations) arrive from the
    # environment as one comma-separated string. An empty element is
    # dropped rather than passed through as "", which OpenRouter would
    # reject as an unknown quantization level.
    if isinstance(reference, list):
        return [item.strip() for item in value.split(",") if item.strip()]
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
    "llm_provider": "openrouter",
    # gpt-5.6-luna, via OpenRouter (2026-08-31). Not in capabilities.py's
    # DeepSeek/MiniMax-specific tables, so it falls to _DEFAULT there
    # (tool_choice/json_mode/json_schema all True, function-calling).
    #
    # Chosen over deepseek-v4-flash-0731 to remove the provider lottery at
    # the source rather than filter it. deepseek-v4-flash-0731 is served by
    # 29 independent upstreams of which 8 cannot enforce a JSON Schema and
    # six run fp4; gpt-5.6-luna is served by 7, ALL first-party (OpenAI /
    # Azure / Amazon Bedrock), and only Bedrock lacks structured_outputs --
    # one stable exclusion instead of a filter that has to track a roster
    # OpenRouter changes without notice.
    #
    # Measured 2026-08-31 on the real Research Manager path, 5 trials each:
    #   deepseek-v4-flash-0731  1/5 collapsed, 48-85s, prose 382-1530 chars
    #   gpt-5.6-luna            0/5 collapsed,  8-9s,  prose 1001-1329 chars
    # Roughly 9x faster with far tighter variance. It is dearer per call
    # (~$0.0055 vs ~$0.0014 measured): input is cheaper ($0.10 vs $0.14/M)
    # but output costs more ($0.60 vs $0.28/M), and reasoning tokens bill as
    # output. Add provider sort "price" to reach OpenAI's cheaper Flex tier
    # if that matters more than latency.
    #
    # Revert to "deepseek/deepseek-v4-flash-0731" (both keys) to go back --
    # but see openrouter_quantizations below, which MUST be repopulated at
    # the same time or the open-weight fp4 hosts come back with it.
    "deep_think_llm": "openai/gpt-5.6-luna",
    "quick_think_llm": "openai/gpt-5.6-luna",
    "backend_url": None,


    # Provider-specific thinking configuration
    "google_thinking_level": None,
    "openai_reasoning_effort": None,
    "anthropic_effort": None,
    # Lowered from "xhigh" (2026-08-25) to test the fastest possible run
    # time: xhigh's per-call latency is highly variable under real provider
    # load (BDL run, same day: one single call took 6m51s), which is most
    # of why a "fast" (~4 min estimate) run took 14 min. "low" is the
    # lowest tier every OpenRouter reasoning-capable model recognises
    # (unlike "minimal", which not every model/provider combination
    # supports) -- applies to both deep_think_llm and quick_think_llm,
    # since both share this same _get_provider_kwargs() output. Revert to
    # "xhigh" (or try "medium"/"high" in between) if this trades away too
    # much analysis quality for the speed.
    "openrouter_reasoning_effort": "high",
    # Raised from 8192 (2026-08-31). Reasoning tokens bill against this
    # SAME budget as the answer -- `reasoning.exclude=True` only hides them
    # from the response body, it does not stop them consuming the cap. A
    # measured call spent 5885 of 6771 completion tokens on reasoning (87%),
    # leaving the prose fields to fit in what remained; every arm of the
    # routing comparison also threw a LengthFinishReasonError at 8192.
    # Raising the ceiling costs nothing on its own -- billing is on tokens
    # actually produced, not on the cap.
    "openrouter_max_completion_tokens": 32768,
    "openrouter_temperature": 0.2,
    "openrouter_top_p": 0.9,

    # --- OpenRouter provider routing (2026-08-31) -------------------------
    # OpenRouter routes one model slug across MANY independent upstream
    # hosts. For deepseek-v4-flash-0731 there were 29 on 2026-08-31, and
    # they are not equivalent:
    #
    #   * 8 of the 29 cannot enforce a JSON Schema. Three advertise no
    #     `response_format` at all (Relace, BaseTen, CoreWeave); five more
    #     support `response_format` but NOT `structured_outputs`
    #     (DigitalOcean, StreamLake, GMICloud, Novita, and DeepSeek's own
    #     endpoint). The second group implements JSON *mode*: valid JSON is
    #     guaranteed, the schema is not compiled into a decoding grammar.
    #     A schema-less grammar cannot forbid "" for a required string, so
    #     the model may return {"rationale": ""} -- syntactically perfect,
    #     semantically empty.
    #   * Quantization ranges from bf16 (Morph only) through fp8 to fp4
    #     (Sail Research, Relace, Ambient, Inceptron, Reka, AtlasCloud).
    #     OpenRouter's own docs: "Quantized models may exhibit degraded
    #     performance for certain prompts."
    #
    # That is the mechanism behind the empty Research Manager / Portfolio
    # Manager reports observed 2026-08-29..30 (KAYNES, LENSKART, SAIL --
    # `**Rationale**: ...`, `**Executive Summary**: (placeholder)`), which
    # began after the 2026-08-26 switch from the direct `deepseek` provider
    # to `openrouter`. Reproduced live at roughly a 1-in-5 rate per prose
    # field, on both the flash and the pro model, so it is a routing
    # property rather than a weak-model property.
    #
    # EMPTY on purpose while the model is gpt-5.6-luna. A quantization
    # filter only means something for an open-weight model served by many
    # third parties at different precisions. All 7 first-party gpt-5.6-luna
    # endpoints report quantization "unknown", so ["bf16","fp8"] matches
    # NONE of them and every call fails:
    #   HTTP 404 "No endpoints found for the request with quantization"
    # (verified live before shipping this switch).
    #
    # Repopulate with ["bf16","fp8"] if reverting to an open-weight model
    # such as deepseek-v4-flash-0731, where it excludes six fp4 hosts.
    "openrouter_quantizations": [],
    # Hosts to exclude by name. gpt-5.6-luna's 7 endpoints are all
    # first-party and 6 of the 7 support structured_outputs; Amazon Bedrock
    # is the sole exception, and a host without structured_outputs
    # implements JSON *mode* only -- valid JSON with the schema never
    # compiled into a decoding grammar, so nothing forbids
    # {"rationale": ""}. One stable exclusion replaces the roster-tracking
    # allowlist the open-weight model needed.
    "openrouter_ignore_providers": ["amazon-bedrock"],
    # EMPTY on purpose while the model is gpt-5.6-luna: the names below are
    # DeepSeek hosts and none of them serve this model, so a non-empty
    # value here fails every call with
    #   HTTP 404 "No allowed providers are available for the selected model"
    # (verified live before shipping this switch). Kept as a key, with the
    # measured list preserved in this comment, so reverting to an
    # open-weight model is a copy-paste rather than a re-measurement:
    #   ["openinference", "akashml", "deepinfra", "morph",
    #    "parasail", "mancer2", "nextbit"]
    # -- the bf16/fp8 hosts advertising ALL of structured_outputs, seed,
    # tools and tool_choice (measured 2026-08-31 via
    # /api/v1/models/<slug>/endpoints).
    #
    # This exists because the principled filter does NOT work here.
    # OpenRouter's `require_parameters: true` is the intended way to demand
    # schema enforcement, but it matches the request against each
    # endpoint's ADVERTISED parameter list, and langchain unavoidably sends
    # two parameters that NO endpoint advertises: `max_completion_tokens`
    # (ChatOpenAI rewrites max_tokens to this) and `parallel_tool_calls`
    # (added by with_structured_output's tool-calling path). The match set
    # is therefore always empty and every call fails with
    #   HTTP 404 "No endpoints found that can handle the requested
    #   parameters."
    # Confirmed by capturing the real request body off the wire, not
    # inferred. So the capability guarantee has to be spelled out by name.
    #
    # Quantization filtering alone is NOT sufficient: CoreWeave, BaseTen,
    # StreamLake, GMICloud and Novita are all fp8 yet lack
    # structured_outputs, and a host without it implements JSON *mode*
    # only -- valid JSON, schema not compiled into a decoding grammar, so
    # nothing forbids {"rationale": ""}.
    #
    # STALENESS: this is a point-in-time snapshot of a roster OpenRouter
    # changes without notice. Re-check with:
    #   curl -s https://openrouter.ai/api/v1/models/<model-slug>/endpoints
    # Set to [] to fall back to quantization filtering alone.
    "openrouter_only_providers": [],
    # OFF by default. `:exacto` is OpenRouter's quality-first variant,
    # ranking upstreams by tool-calling telemetry -- which sounds ideal
    # here, since with_structured_output() drives structured output through
    # tool calling. Measured on 2026-08-31 it did not hold up:
    #   * on its own it routed to Relace -- fp4, and one of the three hosts
    #     with no response_format support whatsoever, i.e. the single worst
    #     destination for this workload;
    #   * paired with the quantization filter it still produced a collapsed
    #     field (strategic_actions = 3 chars) and ran ~180s against ~65s
    #     for the filter alone.
    # It is a SORT, not a filter: it reorders candidates but never removes
    # a bad one, which is why it cannot close this gap. Kept as a config
    # key so it can be re-tested later without a code change.
    "openrouter_exacto": False,

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

    # Per-request ceiling on every LLM call, applied to every provider by
    # TradingAgentsGraph._get_provider_kwargs (all provider clients accept
    # a `timeout` passthrough kwarg -- see llm_clients/*.py). Previously
    # unset, so a single call had no upper bound: one non-streaming
    # structured-output call (Research Manager/Trader/Portfolio Manager,
    # via invoke_structured_or_freetext) sat waiting on the provider for
    # 5m29s on 2026-08-24, and cooperative cancellation (should_stop, see
    # propagate_streaming) only gets a chance to run between the graph's
    # own streamed chunks -- a non-streaming call that never returns means
    # neither a chunk nor a checkpoint. Set None to restore no timeout.
    #
    # First set to 30 (2026-08-25), which turned out too tight:
    # openrouter_reasoning_effort defaults to "xhigh" below, and an xhigh
    # response can legitimately take well over 30s to produce its first
    # byte (reasoning happens before content streams) -- HINDALCO 2026-08-25
    # failed a real, working run after 2m38s of retries hitting that
    # ceiling on ordinary responses, not a hang. 90s gives real xhigh calls
    # room to finish while still catching a genuinely stuck call (the
    # original incident) many times over.
    "llm_timeout_seconds": 90,

    # Freeze fetched news/social/filings per (ticker, analysis date) so a
    # re-run replays identical inputs. See dataflows/snapshot_cache.py for the
    # measurement that motivated it. Set False (or pass --refresh) to pull
    # fresh data; a different analysis date is a different key either way, so
    # daily runs are unaffected.
    "snapshot_cache_enabled": True,

    # --- OHLCV cache freshness (dataflows/stockstats_utils.py) -------------
    # load_ohlcv keys its price cache on (symbol, today) and would otherwise
    # reuse it for the WHOLE day, pinning every later run to whatever the
    # vendor had published at the first fetch of that day.
    #
    # Two real incidents, both silent:
    #   * KAYNES.NS 2026-08-31 -- a 16:38 IST run (an hour after the 15:30
    #     close) wrote a cache whose last row was 08-28, because yfinance had
    #     not yet published the 08-31 bar. Every later run that day reused it,
    #     so a 19:51 IST run analysed three-day-old prices and never saw a
    #     -6.5% session (3943 -> 3685). The file was byte-identical to the
    #     previous day's, which is how it went unnoticed.
    #   * ITC.NS 2026-09-02 -- a 16:11 IST run analysed the 08-31 close of
    #     255.50 while the stock had closed at 266.60 on 09-01 and 266.30 on
    #     09-02. The recommended entry was never fillable at any point after
    #     the analysis was produced.
    #
    # When True, a cache that does not reach the requested date is re-checked
    # against the vendor once the recheck window below has elapsed, and a
    # cache whose newest row carries no usable Close is refetched outright
    # (see _cache_covers_date). Set False to restore the original
    # "reuse the file for the whole day, unconditionally" behaviour -- which
    # is what the two incidents above ran on.
    "ohlcv_cache_freshness_check": True,
    # How long a cache that does NOT reach the requested date is trusted
    # before the vendor is asked again. Bounds the retry rate so a genuine
    # holiday, a suspended scrip or a delisting cannot turn every call into a
    # fresh download, while still letting a run started shortly after the
    # close pick that session up once the vendor publishes it. Lower it to
    # catch a just-published bar sooner, at the cost of more vendor calls.
    "ohlcv_cache_recheck_seconds": 30 * 60,

    # Multiplier applied to the concise-tuned word budgets when report_style
    # is "balanced" (agent_utils.scale_word_budget). See _BALANCED_WORD_SCALE
    # there for the ITC.NS measurement behind the 2.5 -> 4.0 raise: the cap
    # compressed the reasoning agents 3-3.5x while barely touching the
    # data-dumping ones, so it was spending its whole budget cut on judgement.
    # Lower it to buy wall-clock back, at a measurable cost in analysis depth.
    "balanced_word_scale": 4.0,

    # ON since 2026-08-31. A run takes 4-14 minutes and a transient provider
    # disconnect part-way through used to throw all of it away: KAYNES on
    # 2026-08-31 lost two consecutive attempts at ~8 minutes each to
    #   RemoteProtocolError: peer closed connection without sending complete
    #   message body (incomplete chunked read)
    # -- OpenRouter dropping the response stream mid-body. That class of
    # failure cannot be retried at the HTTP client either: once the body has
    # started arriving the request has already "succeeded" as far as the
    # OpenAI SDK is concerned, so its own max_retries never engages. Resuming
    # from the last completed node is the only layer that helps.
    #
    # The machinery for it was already built and tested (checkpointer.py,
    # test_checkpoint_resume.py, test_streaming_checkpoint_resume.py, and the
    # resume branch of propagate_streaming) and merely left switched off --
    # this was the one setting in this file carrying no rationale at all.
    # api/worker.py already surfaces "you may be able to resume it" on
    # failure, which was untrue while this was False.
    #
    # Cost of having it on: a small per-ticker SQLite file under
    # data_cache_dir/checkpoints. A normal (resume=False) run clears any
    # stale checkpoint for its ticker+date before starting and clears its own
    # on success, so these do not accumulate across successful runs.
    "checkpoint_enabled": True,
    "output_language": "English",

    # Debate and discussion settings
    "max_debate_rounds": 2,
    "max_risk_discuss_rounds": 2,
    "max_recur_limit": 180,
    "analyst_concurrency_limit": 1,

    # News / data fetching parameters
    "news_article_limit": 30,
    # Lowered from 20 (2026-08-25): the get_global_news vendor below
    # (yfinance) can return generic, not-India-specific trending content
    # when its query doesn't match well (see tool_vendors.get_global_news
    # comment) -- a small cap bounds how much of that can dilute the
    # prompt, without pretending the content itself is filtered.
    "global_news_article_limit": 5,
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
    #
    # Short, real phrases -- not descriptive sentences. GDELT ORs every entry
    # here into ONE query as an exact quoted phrase; a 6-9 word descriptive
    # phrase like the old "RBI monetary policy repo rate India interest
    # rates" essentially never appears verbatim in prose, so GDELT returned
    # nothing and the vendor chain fell through to Yahoo's fuzzy search,
    # which -- with no good match for that wording either -- degraded to
    # generic trending Yahoo Finance content (oil, the dollar, gas prices),
    # none of it India-specific. Every phrase below is 2-4 words, the way
    # Indian financial media actually writes it, so it has a real chance of
    # matching an actual headline instead of silently degrading.
    #
    # Covers the structural drivers that move Indian equities: RBI policy/
    # rate cycle, index-level moves, FII/DII positioning, the rupee, fiscal
    # policy, and the macro indicators (inflation, GDP, PMI) that set the
    # backdrop for all of them.
    # -----------------------------------------------------------------------
    # Capped around 20: GDELT ORs every entry into one query, and past ~20-25
    # clauses a DOC API query risks the same "too complex" rejection the
    # OR-parenthesization fix (see gdelt_news.py) was already written to
    # avoid; yfinance walks this same list one query per entry as its own
    # fallback, so an unbounded list also means an unbounded worst-case
    # number of sequential search calls there.
      "global_news_queries": [
        "RBI repo rate",
        "RBI monetary policy",
        "Nifty 50",
        "Sensex",
        "Bank Nifty",
        "FII outflows",
        "DII buying",
        "foreign portfolio investors India",
        "rupee depreciation",
        "forex reserves India",
        "Union Budget India",
        "GST reform",
        "fiscal deficit India",
        "India inflation CPI",
        "India GDP growth",
        "manufacturing PMI India",
        "India trade deficit",
        "SEBI regulation",
        "mutual fund inflows India",
        "India IPO market",
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
    #   3. alpha_vantage - REJECTS Indian tickers outright ("Invalid ticker
    #      format: TMPV.BSE"); useful only for US-listed symbols.
    #   4. finnhub - free tier is US/major-market-centric.
    #
    # gdelt REMOVED from the chain 2026-09-05. It had been kept as a
    # fallback despite throttling, on the theory that a throttled fallback
    # still beats no fallback. Measurement says otherwise: it is now
    # failing constantly, and a throttled attempt is not free.
    #
    #   * Every observed attempt over 2026-09-04..05 returned HTTP 429 and
    #     gave up after both retries -- 2 full give-up sequences in a single
    #     ITC.NS run, contributing ZERO articles.
    #   * Checked directly on 2026-09-05, the two global-news chains
    #     "gdelt,yfinance,alpha_vantage,finnhub" and
    #     "alpha_vantage,yfinance,finnhub" returned byte-identical output
    #     (968 chars) -- i.e. gdelt contributed nothing either way.
    #   * The cost is real: gdelt_max_retries=2 with
    #     gdelt_retry_base_delay=5.0 means 5s + 10s of sleeping plus up to
    #     three gdelt_timeout_seconds=15 attempts, so a fully throttled
    #     fetch burns ~45s of wall clock to return nothing. That is paid
    #     BEFORE any LLM call, on the critical path.
    #
    # Being third in the chain made this worse, not better: it is only
    # reached when google_news AND yfinance have both already failed --
    # exactly the moment a run can least afford another 45s of dead time
    # before falling through to alpha_vantage.
    #
    # The gdelt_* tuning knobs below are deliberately LEFT IN PLACE so
    # re-adding is a one-word edit to this string. Re-add when GDELT's rate
    # limiting eases; it remains the only genuinely global web-news search
    # in the set, and the reason it was ever here has not changed.
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
        "news_data":            "google_news,yfinance,alpha_vantage,finnhub",
    },

    # Tool-level overrides (takes precedence over category-level above)
    #
    # get_global_news -- history, 2026-08-25, two iterations:
    #
    # 1. Originally "gdelt,yfinance,alpha_vantage,finnhub", with yfinance
    #    also in merged_news_vendors below (fine for get_news, where
    #    merging google_news+yfinance is genuinely additive). For
    #    get_global_news specifically that meant route_to_vendor's merge
    #    pass called ONLY yfinance (the sole chain entry intersecting
    #    merged_news_vendors), always "succeeded" (yf.Search() never
    #    errors, it just returns SOMETHING), and returned immediately --
    #    GDELT, first in the chain, was never actually attempted in a real
    #    run despite appearing to be.
    # 2. Swapped yfinance for india_rss (the India RSS pool, already
    #    filtered by india_news.py's _MACRO_TERMS) to fix that and to stop
    #    yf.Search()'s generic trending content (confirmed live: querying
    #    "RBI repo rate" still returned Strait-of-Hormuz crude-oil
    #    headlines) from reaching the prompt. This worked, but GDELT is
    #    also just rate-limited in practice right now, so it fell straight
    #    to india_rss -- which duplicated news_analyst.py's OWN separate
    #    fetch_global_india_news() call verbatim, wasting prompt tokens on
    #    two copies of the same block under different headings.
    #
    # 3. alpha_vantage promoted to primary (2026-08-25): its NEWS_SENTIMENT
    #    endpoint is purpose-built for exactly this ("global market news &
    #    sentiment... financial markets, economy, M&A, IPOs" -- see its own
    #    docstring in alpha_vantage_news.py), unlike yfinance's Search,
    #    which ignores whatever query it's given. It was already wired in
    #    as the SECOND fallback the whole time, but yfinance (first) never
    #    errors -- it always returns some string -- so alpha_vantage was
    #    never actually reached either, same shape of problem as GDELT
    #    before it. Not in merged_news_vendors, so no merge-bypass risk in
    #    either position. Its free tier is capped (25 requests/day,
    #    documented in the technical_indicators comment above) --
    #    AlphaVantageRateLimitError is caught explicitly by
    #    interface._invoke_vendor and falls through to yfinance, so
    #    exhausting it degrades rather than breaks a run.
    "tool_vendors": {
        "get_global_news": "alpha_vantage,yfinance,finnhub",
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
    # Restored to 2 (2026-09-03), matching DEFAULT_CONFIG and the baseline.
    #
    # At 1, the bull/bear exchange is bull -> bear and stops. The bull never
    # answers the bear, so an unsupported bull claim reaches the Research
    # Manager unchallenged. ITC.NS 2026-09-02 is the worked example: the bull
    # asserted "multi-year support at 253-255" (sourced, unattributed, from a
    # StockTwits post; the stock had not traded there since 2022) and that
    # claim became the load-bearing pillar of a Buy-the-dip Overweight. The
    # SAME ticker at 2 rounds gave the bull a second turn, in which it had to
    # engage the bear directly and conceded the honest version -- "that's the
    # lowest print in the 13-month dataset" -- arguing fundamental value
    # instead. Underweight, with reachable levels.
    #
    # This was the single biggest wall-clock lever, and giving it up is a
    # deliberate trade. It is affordable now for a reason that did not hold
    # when the profile was written: the analyst phase runs concurrently
    # (below) and the provider switch cut per-call latency roughly 9x, so a
    # full run measured 3m57s even before this. Speed now comes from
    # concurrency and a faster model rather than from truncating the
    # reasoning, which is the only one of the three that was ever free.
    #
    # Set TRADINGAGENTS_MAX_DEBATE_ROUNDS=1 to go back if latency matters
    # more than the verdict -- but re-run the ITC/SIEMENS scorecard first.
    #
    # NOT re-assigned here, deliberately. This function used to hardcode
    # `config["max_debate_rounds"] = 2` at this point, which runs AFTER
    # _apply_env_overrides has already populated DEFAULT_CONFIG -- so the
    # escape hatch the comment above advertises silently did nothing for
    # anyone on the fast profile (which is the API's and the web UI's
    # default, i.e. every real user). Verified: with
    # TRADINGAGENTS_MAX_DEBATE_ROUNDS=1 set, DEFAULT_CONFIG read 1 and
    # get_fast_config() still returned 2.
    #
    # Inheriting the deep-copied value instead keeps the intended default
    # (fast == DEFAULT == 2) while letting the env var actually reach the
    # graph. Do not re-add an assignment here without also giving the
    # override somewhere else to land.
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
