import contextlib
import functools
import logging
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


# Suffixes tried, in order, when a bare ticker (e.g. "RELIANCE" instead of
# "RELIANCE.NS") doesn't resolve on yfinance. NSE first — it's the more
# liquid of the two exchanges for most dual-listed Indian names.
_INDIA_EXCHANGE_SUFFIXES = (".NS", ".BO")


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
    suffixes for bare stock symbols. Best-effort: any failure (network,
    rate limit) returns the ticker unchanged rather than blocking the run.
    """
    normalized = ticker.strip().upper()
    if asset_type == "crypto" or "." in normalized or "-" in normalized:
        return normalized

    # A 404 on a probe candidate is the expected answer, not an error: this
    # loop asks Yahoo "does BLUEJET exist? BLUEJET.NS? BLUEJET.BO?" and stops
    # at the first hit. yfinance logs each miss to stderr itself, so a normal
    # resolution printed an alarming
    # `HTTP Error 404: ... Quote not found for symbol: BLUEJET` at the top of
    # every run that used a bare ticker, even though resolution then
    # succeeded (observed on the BLUEJET run, 2026-08-11). Silence yfinance
    # for the duration of the probe only, and restore it afterwards so real
    # yfinance problems elsewhere are still reported.
    with _muted_logger("yfinance"):
        for candidate in (normalized, *(f"{normalized}{suffix}" for suffix in _INDIA_EXCHANGE_SUFFIXES)):
            try:
                info = yf.Ticker(candidate).info or {}
            except Exception as exc:  # noqa: BLE001 — fail open, never block the run
                logger.debug("Ticker resolution check failed for %s: %s", candidate, exc)
                continue
            if info.get("previousClose") is not None:
                return candidate

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


def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add a context-anchored placeholder.

        The placeholder must not be a bare ``"Continue"``: some
        OpenAI-compatible providers interpret that literally as the user task
        and produce output about the word "continue" instead of analysing the
        instrument (#888). Anchoring it to the resolved instrument context and
        date keeps the next analyst on-task even if the provider treats the
        placeholder as a standalone request.
        """
        messages = state["messages"]
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        instrument_context = get_instrument_context_from_state(state)
        trade_date = state.get("trade_date", "the requested date")
        placeholder = HumanMessage(
            content=(
                f"Proceed with your assigned analysis for this workflow. "
                f"{instrument_context} The analysis date is {trade_date}."
            )
        )
        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
