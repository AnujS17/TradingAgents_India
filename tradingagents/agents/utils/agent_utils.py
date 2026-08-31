import contextlib
import functools
import logging
import re
import time
from typing import Any, Mapping, Optional

import yfinance as yf
from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)
from tradingagents.agents.utils.market_data_validation_tools import (
    get_verified_market_snapshot
)

logger = logging.getLogger(__name__)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Applied to every agent whose output reaches the saved report —
    analysts, researchers, debaters, research manager, trader, and
    portfolio manager — so a non-English run produces a fully localized
    report rather than a mix of languages.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


# report_style has three values:
#
#   "detailed" — no length guidance at all (the default; byte-identical to
#                the original prompts).
#   "balanced" — the fast profile. Length discipline, but the two STRUCTURAL
#                allowances that concise removed are restored.
#   "concise"  — maximum trim. Retained and still tested, but no longer used
#                by --fast; see below.
#
# Why "balanced" exists. On SIEMENS.NS 2026-08-12 the concise profile did not
# merely shorten the write-up, it changed the conclusion: the news template's
# "8 bullets MAXIMUM" cap evicted the 07-Apr-2025 Demerger filing in favour of
# a fresher headline, and "No markdown table" deleted the one place the
# detailed run tagged its rows "(separate entity)". With the disqualifying
# fact gone, the run credited a demerged sister company's +70% profit to
# SIEMENS.NS as a bullish point.
#
# So the fix is not mainly about word count — it is those two structural
# allowances. "balanced" keeps the tables and raises the coverage-bullet cap,
# and scales the word budgets by _BALANCED_WORD_SCALE on top.
_BALANCED_WORD_SCALE = 2.5


def get_report_style() -> str:
    from tradingagents.dataflows.config import get_config
    return get_config().get("report_style", "detailed")


def is_length_limited() -> bool:
    """True when the prompt should carry an explicit word budget."""
    return get_report_style() in ("concise", "balanced")


def keeps_markdown_tables() -> bool:
    """Whether the summary table survives.

    Only "concise" drops it. The table is compact for what it carries and is
    where per-item qualifiers (entity, recency, confidence) actually live.
    """
    return get_report_style() != "concise"


def scale_word_budget(concise_words: int) -> int:
    """Scale a concise-tuned word budget for the active style."""
    if get_report_style() == "balanced":
        return int(concise_words * _BALANCED_WORD_SCALE)
    return concise_words


def get_brevity_instruction(max_words: int) -> str:
    """Return a hard length limit for free-text agents when length is limited.

    Returns "" for the default "detailed" style, so no extra tokens are used
    and existing behaviour is byte-identical.

    An explicit NUMBER matters: the word "concise" alone is a soft hint that
    models routinely ignore, especially when a surrounding prompt also asks
    for comprehensive analysis and a markdown table. Wall-clock time for a
    run is dominated by output-token generation, so the word budget here is
    the main quality/speed dial for the five free-text debate agents
    (bull, bear, aggressive, neutral, conservative) — none of which had any
    length guidance at all before, and which together are 5 of the ~12 LLM
    calls in a run.
    """
    if not is_length_limited():
        return ""
    budget = scale_word_budget(max_words)
    # "No markdown tables" is deliberately dropped under balanced — a debate
    # agent that wants to tabulate a comparison should be allowed to.
    table_clause = "" if keeps_markdown_tables() else " No markdown tables."
    return (
        f" HARD LIMIT: {budget} words maximum. Lead with your conclusion, "
        "then only the evidence that actually supports it. No preamble, no "
        "recap of what other analysts said." + table_clause
    )


def get_india_market_instruction(scope: str = "general") -> str:
    """Return a compact India-market lens for prompts.

    The snippets are intentionally short so they improve sector/market
    judgment without crowding out tool-grounding instructions.
    """
    instructions = {
        "market": (
            " India-market lens: interpret technical moves around RBI policy "
            "decisions, FII/DII flow shifts, Nifty/Sensex index rebalancing, "
            "and budget-cycle catalysts only when supported by price/indicator "
            "evidence."
        ),
        "fundamentals": (
            " India-market lens: emphasize promoter holding and pledging "
            "trends, related-party transactions, INR revenue/cost exposure, "
            "working-capital cycles, and valuation versus earnings growth in "
            "a high-growth, high-rate context."
        ),
        "news": (
            " India-market lens: prioritize material catalysts such as RBI "
            "rate decisions, Union Budget or GST changes, SEBI disclosure "
            "actions, FII/DII flow reversals, monsoon impact on rural demand, "
            "and promoter pledging news."
        ),
        "bull": (
            " India-market lens: support the bull case with strong domestic "
            "consumption trends, DII inflows offsetting FII selling, clean "
            "promoter holding, formalization/GST tailwinds, and earnings "
            "visibility when reports substantiate it."
        ),
        "bear": (
            " India-market lens: challenge promoter pledging or related-party "
            "red flags, INR depreciation risk, FII outflow vulnerability, "
            "monsoon-dependent earnings, valuation versus growth, and "
            "regulatory/SEBI overhang when evidence supports it."
        ),
        "trader": (
            " India-market lens: weigh RBI policy-day and budget-day event "
            "risk, FII/DII flow momentum, INR volatility, and position sizing "
            "around monsoon or election-driven sector swings."
        ),
        "sentiment": (
            " India-market lens: weigh retail-investor and financial-"
            "influencer buzz on Dalal Street platforms, FII/DII flow "
            "sentiment, and budget/monsoon narrative shifts against durable "
            "fundamentals-based conviction."
        ),
        "aggressive_risk": (
            " India-market lens: champion upside from domestic consumption "
            "growth, DII inflows, and formalization tailwinds; argue promoter "
            "concentration and valuation premiums are the cost of India's "
            "structural growth story."
        ),
        "conservative_risk": (
            " India-market lens: flag promoter pledging, related-party "
            "transactions, INR depreciation exposure, FII outflow risk, "
            "monsoon dependency, and regulatory/SEBI overhang as downside "
            "risks."
        ),
        "neutral_risk": (
            " India-market lens: balance domestic consumption and DII-flow "
            "support against FII outflow risk, INR volatility, "
            "promoter-pledging concerns, and budget/regulatory catalysts on "
            "both sides."
        ),
    }
    return instructions.get(scope, instructions["fundamentals"])


def _clean_identity_value(value: Any) -> Optional[str]:
    """Return a trimmed string, or None for empty / placeholder-ish values."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in {"none", "n/a", "nan", "null"}:
        return None
    return cleaned


# Suffixes tried, in order, for a bare ticker (e.g. "RELIANCE" instead of
# "RELIANCE.NS"). NSE first — it's the more liquid of the two exchanges for
# most dual-listed Indian names.
_INDIA_EXCHANGE_SUFFIXES = (".NS", ".BO")

# What actually makes a symbol "already exchange-qualified", used by
# resolve_ticker_symbol to decide whether to probe NSE/BSE at all.
#
# A DOT before a short alphabetic tail is Yahoo's exchange convention
# (.NS .BO .TO .L .HK .T .AX .DE .PA .SI ...), so any such tail counts
# without needing an exhaustive list of the world's venues. A HYPHEN,
# by contrast, only qualifies when it introduces a quote currency --
# BTC-USD, ETH-INR -- because hyphens are legal inside NSE symbols
# (BAJAJ-AUTO, M&M-derived names), which is precisely the collision that
# left BAJAJ-AUTO unresolved.
_QUOTE_CURRENCY_SUFFIXES = ("-USD", "-USDT", "-EUR", "-GBP", "-INR", "-BTC", "-ETH")
_EXCHANGE_SUFFIX_RE = re.compile(r"\.[A-Z]{1,4}$")


def _has_exchange_suffix(normalized: str) -> bool:
    """True when `normalized` already names a venue (or a crypto pair)."""
    if normalized.endswith(_QUOTE_CURRENCY_SUFFIXES):
        return True
    return bool(_EXCHANGE_SUFFIX_RE.search(normalized))

# Retry policy for each yfinance probe (both the .info quote check and the
# recent-history check below). Neither call is wrapped by stockstats_utils's
# yf_retry — that one only retries YFRateLimitError specifically, and what
# actually hit this (TORNTPOWER.NS, 2026-08-25) was a plain, untyped
# exception on a single unretried call, which fell through to .BO and
# silently accepted it for the entire run. yfinance's .info endpoint is
# unofficial/scraped, not a documented API, and informally throttles a
# single IP under sustained request volume rather than always failing with
# a clean, catchable rate-limit error -- a short retry absorbs exactly that
# kind of transient miss instead of treating it as "this exchange doesn't
# have the ticker."
_RESOLUTION_MAX_RETRIES = 2
_RESOLUTION_RETRY_BASE_DELAY = 1.0

# Window used to confirm a candidate has USABLE recent price history, not
# just a live quote. The actual bug: TORNTPOWER.BO's .info returned a valid
# previousClose (the quote endpoint works), but its OHLCV history was a
# single row from over a month earlier -- previousClose alone doesn't prove
# the history endpoint (what get_verified_market_snapshot / load_ohlcv
# actually build the analysis from) has anything recent to show. 5 calendar
# days comfortably covers every NSE/BSE holiday cluster without needing
# date-math against a trading calendar.
_RESOLUTION_HISTORY_CHECK_PERIOD = "5d"


def _probe_with_retry(func, max_retries: int = _RESOLUTION_MAX_RETRIES, base_delay: float = _RESOLUTION_RETRY_BASE_DELAY):
    """Retry a yfinance call on any exception, short linear backoff.

    Returns the call's result, or None once every attempt has failed --
    the caller treats None the same as a clean "not found" for this probe,
    not a hard error, since resolve_ticker_symbol's own contract is to try
    the next exchange (or fail open) rather than raise here.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 — network trouble, not a "not found" answer
            if attempt < max_retries:
                logger.debug(
                    "yfinance probe failed (attempt %s/%s): %s",
                    attempt + 1, max_retries + 1, exc,
                )
                time.sleep(base_delay * (attempt + 1))
            else:
                logger.debug(
                    "yfinance probe failed after %s attempts: %s",
                    max_retries + 1, exc,
                )
    return None


def _has_recent_history(candidate: str) -> bool:
    """True when ``candidate`` has at least one trading row in the last
    _RESOLUTION_HISTORY_CHECK_PERIOD -- confirms the history endpoint that
    the actual analysis is built from has something usable, not just that
    the quote endpoint answered.
    """
    history = _probe_with_retry(
        lambda: yf.Ticker(candidate).history(period=_RESOLUTION_HISTORY_CHECK_PERIOD)
    )
    return history is not None and not history.empty


class TickerNotFoundError(Exception):
    """Raised by resolve_ticker_symbol() when a bare stock ticker was
    confirmed absent on both NSE and BSE (not a network/API failure --
    both exchanges genuinely answered "no such ticker"). This is meant to
    propagate all the way out of the run: api/worker.py's existing
    broad exception handler already turns any uncaught exception into a
    clear failed-run error message, so raising here is the correct way
    to make this "return an error, don't proceed" (no new plumbing)."""


@contextlib.contextmanager
def _muted_logger(name: str, level: int = logging.CRITICAL):
    """Temporarily raise ``name``'s log level, restoring it on exit.

    Used to silence a third-party library while making calls whose failures
    are expected and handled here. Restores the previous level even if the
    body raises, so it can never leave a logger permanently muted.
    """
    target = logging.getLogger(name)
    previous = target.level
    target.setLevel(level)
    try:
        yield
    finally:
        target.setLevel(previous)


@functools.lru_cache(maxsize=256)
def resolve_ticker_symbol(ticker: str, asset_type: str = "stock") -> str:
    """Resolve a possibly-unsuffixed ticker to the symbol yfinance actually serves.

    Every data-fetching function in this codebase (get_verified_market_snapshot,
    fetch_ticker_india_news, fetch_promoter_bulk_deals, fetch_stocktwits_messages,
    fetch_reddit_posts, get_news, ...) reads its ticker from
    ``state["company_of_interest"]``, which is set once from raw user input at
    graph start and never updated. If a user types "RELIANCE" instead of
    "RELIANCE.NS", every one of those pre-fetches fails identically and
    permanently for the whole run — even after an LLM's own tool call
    self-corrects to the right suffix, the deterministic pre-fetches never see
    that correction, because they don't reason about the ticker at all; they
    just read the fixed state value (#reliance-run-2026-08-10). Calling this
    once at graph-init time, before ``company_of_interest`` is set, fixes the
    problem at its single source instead of requiring every analyst to
    rediscover the right suffix independently.

    Already-qualified tickers (containing "." or "-", e.g. "CNC.TO", "BTC-USD")
    and crypto assets are returned unchanged — this only guesses NSE/BSE
    suffixes for bare stock symbols.

    Only NSE (.NS) and BSE (.BO) are ever tried or accepted for a stock —
    the bare, unsuffixed ticker is deliberately NEVER checked or returned
    as a resolved answer. It used to be tried first, which meant any bare
    ticker that also happens to be a real symbol on a different exchange
    (e.g. "HAL" is Halliburton on NYSE; "MCX" is a separate US-listed
    company) silently resolved to that WRONG company before NSE/BSE were
    ever tried, and the whole run then analyzed it. This tool analyzes
    Indian-listed equities only; a foreign collision is never an
    acceptable answer.

    Raises TickerNotFoundError if the ticker was confirmed absent on both
    NSE and BSE (both exchanges genuinely answered "not found" or "no
    usable recent history" — not a network error) — this is intentional
    and meant to fail the run loudly rather than proceed with an
    unresolved or foreign ticker.

    Best-effort only for genuine infrastructure trouble: if every probe
    raised (total network/API failure, so NSE/BSE were never actually
    checked), returns the ticker unchanged rather than blocking the run
    over something that isn't a "this ticker doesn't exist" answer at all.

    Each probe is retried a few times before being treated as unavailable
    (_probe_with_retry), and a candidate must have BOTH a live quote
    (previousClose) AND actual recent price history (_has_recent_history)
    to be accepted — not quote data alone. TORNTPOWER.NS, 2026-08-25: a
    single unretried .info call failed transiently, fell through to .BO,
    whose quote endpoint answered fine but whose OHLCV history was one row
    from over a month earlier — get_verified_market_snapshot then built an
    entire technical read (and the trader's entry price) on that stale
    print, undetected, because previousClose alone doesn't prove the
    history endpoint has anything current.
    """
    normalized = ticker.strip().upper()
    # A hyphen used to short-circuit here alongside a dot, to pass through
    # crypto pairs like BTC-USD untouched. But hyphens are perfectly legal
    # INSIDE an NSE symbol -- BAJAJ-AUTO is the textbook case -- so a real
    # Indian ticker was read as "already exchange-qualified", never had .NS
    # appended, and yfinance answered "possibly delisted; no timezone found"
    # for it while BAJAJ-AUTO.NS returns 1241 rows. Observed 2026-08-29: the
    # verified market snapshot failed with "yfinance returned no data for
    # 'BAJAJ-AUTO'". Because every deterministic pre-fetch reads the same
    # resolved value (see this docstring's opening paragraph), that one
    # substitution degrades news, bulk deals, StockTwits and Reddit for the
    # whole run, not just the technical snapshot. It also defeated the
    # never-accept-a-bare-ticker protection below, which is bypassed
    # entirely when we return before reaching it.
    #
    # Only an EXCHANGE suffix means "already qualified", so test for one
    # rather than for punctuation. -USD and friends keep crypto working; a
    # trailing .NS/.BO/.TO/.L and so on keeps every already-qualified equity
    # working; a bare BAJAJ-AUTO now falls through to the NSE/BSE probe.
    if asset_type == "crypto" or _has_exchange_suffix(normalized):
        return normalized

    # A 404 on a probe candidate is the expected answer, not an error: this
    # loop asks Yahoo "does BLUEJET.NS exist? BLUEJET.BO?" and stops at the
    # first hit. yfinance logs each miss to stderr itself, so a normal
    # resolution printed an alarming
    # `HTTP Error 404: ... Quote not found for symbol: BLUEJET.NS` at the top
    # of every run, even though resolution then succeeded on the next
    # candidate (observed on the BLUEJET run, 2026-08-11). Silence yfinance
    # for the duration of the probe only, and restore it afterwards so real
    # yfinance problems elsewhere are still reported.
    checked_at_least_one_exchange = False
    with _muted_logger("yfinance"):
        for suffix in _INDIA_EXCHANGE_SUFFIXES:
            candidate = f"{normalized}{suffix}"
            info = _probe_with_retry(lambda c=candidate: yf.Ticker(c).info or {})
            if info is None:
                # Every retry failed -- couldn't get an answer at all from
                # this exchange, not a confirmed "not found". Try the next
                # suffix; this candidate never counts toward
                # checked_at_least_one_exchange.
                continue
            checked_at_least_one_exchange = True
            if info.get("previousClose") is None:
                continue
            if _has_recent_history(candidate):
                return candidate
            logger.debug(
                "%s has a live quote but no usable recent history; treating as unavailable",
                candidate,
            )

    if checked_at_least_one_exchange:
        raise TickerNotFoundError(
            f"'{normalized}' was not found on NSE or BSE. This tool only "
            "analyzes Indian-listed equities — check the ticker spelling, "
            "or the company may not be listed on NSE/BSE."
        )

    # Every probe raised — could not determine anything, not even a
    # confirmed "not found". Fail open rather than block the run over
    # infrastructure trouble this function cannot diagnose or fix.
    return normalized


@functools.lru_cache(maxsize=256)
def resolve_instrument_identity(ticker: str) -> dict:
    """Resolve deterministic identity metadata (company name, sector, …) for a ticker.

    This exists to stop the pipeline from hallucinating a *different* company
    when a chart pattern suggests a different industry than the real one
    (#814): without a ground-truth name, the market analyst would pattern-match
    the price action to a narrative and invent an identity that then cascaded
    through every downstream agent.

    Best-effort by design: if yfinance is unavailable, rate-limited, or doesn't
    recognise the ticker, we return ``{}`` and the caller falls back to
    ticker-only context rather than failing before analysis starts. Cached so
    the lookup happens at most once per ticker per process.
    """
    try:
        info = yf.Ticker(ticker.upper()).info or {}
    except Exception as exc:  # noqa: BLE001 — fail open, never block the run
        logger.debug("Could not resolve instrument identity for %s: %s", ticker, exc)
        return {}

    identity: dict[str, str] = {}
    company_name = _clean_identity_value(info.get("longName")) or _clean_identity_value(
        info.get("shortName")
    )
    if company_name:
        identity["company_name"] = company_name
    for source_key, target_key in (
        ("sector", "sector"),
        ("industry", "industry"),
        ("exchange", "exchange"),
        ("quoteType", "quote_type"),
    ):
        value = _clean_identity_value(info.get(source_key))
        if value:
            identity[target_key] = value
    return identity


def build_instrument_context(
    ticker: str,
    asset_type: str = "stock",
    identity: Optional[Mapping[str, str]] = None,
) -> str:
    """Describe the exact instrument so agents preserve identity and ticker.

    When ``identity`` is provided (resolved deterministically via
    :func:`resolve_instrument_identity`), the company name and business
    classification are injected so agents anchor to the real company rather
    than pattern-matching the price chart to a wrong one (#814).
    """
    is_crypto = asset_type == "crypto"
    instrument_label = "asset" if is_crypto else "instrument"
    context = (
        f"The {instrument_label} to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.NS`, `.BO`, `.TO`, `.L`, `.HK`, `.T`, `-USD`)."
    )

    details = []
    if identity:
        name = identity.get("company_name") or identity.get("name")
        if name:
            details.append(f"{'Name' if is_crypto else 'Company'}: {name}")
        sector, industry = identity.get("sector"), identity.get("industry")
        if sector and industry:
            details.append(f"Business classification: {sector} / {industry}")
        elif sector:
            details.append(f"Sector: {sector}")
        elif industry:
            details.append(f"Industry: {industry}")
        if identity.get("exchange"):
            details.append(f"Exchange: {identity['exchange']}")

    if details:
        context += (
            f" Resolved identity: {'; '.join(details)}. "
            "Do not substitute a different company or ticker unless a tool "
            "result explicitly disproves this resolved identity."
        )

    if is_crypto:
        context += (
            " Treat it as a crypto asset rather than a company, and do not "
            "assume company fundamentals are available."
        )
    return context


def get_instrument_context_from_state(state: Mapping[str, Any]) -> str:
    """Return the instrument context for the current run.

    Prefers the identity-resolved context computed once at run start and
    stored on the state (see ``TradingAgentsGraph.resolve_instrument_context``).
    Falls back to a ticker-only context — with no network lookup — when the
    state was constructed without it (bare programmatic states, tests), so a
    consumer is never forced to make a yfinance call mid-graph.
    """
    context = state.get("instrument_context")
    if isinstance(context, str) and context.strip():
        return context
    return build_instrument_context(
        str(state["company_of_interest"]),
        state.get("asset_type", "stock"),
    )


def create_msg_delete(messages_key: str = "messages"):
    """Clear one analyst's message channel.

    ``messages_key`` exists because each analyst now owns a separate channel
    (see AgentState) so the four can run concurrently; clearing the shared
    ``messages`` channel would leave every analyst's own channel untouched
    and wipe an unrelated one.
    """
    def delete_messages(state):
        """Clear messages and add a context-anchored placeholder.

        The placeholder must not be a bare ``"Continue"``: some
        OpenAI-compatible providers interpret that literally as the user task
        and produce output about the word "continue" instead of analysing the
        instrument (#888). Anchoring it to the resolved instrument context and
        date keeps the next analyst on-task even if the provider treats the
        placeholder as a standalone request.
        """
        messages = state[messages_key]
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        instrument_context = get_instrument_context_from_state(state)
        trade_date = state.get("trade_date", "the requested date")
        placeholder = HumanMessage(
            content=(
                f"Proceed with your assigned analysis for this workflow. "
                f"{instrument_context} The analysis date is {trade_date}."
            )
        )
        return {messages_key: removal_operations + [placeholder]}

    return delete_messages


        
