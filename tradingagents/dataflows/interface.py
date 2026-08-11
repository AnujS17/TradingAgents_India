from typing import Annotated
import requests

from .pandas_ta_indicators import get_indicators_ta

# Import from vendor-specific modules
from .y_finance import (
    get_YFin_data_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .yfinance_news import get_news_yfinance, get_global_news_yfinance
from .finnhub_news import get_news as get_finnhub_news, get_global_news as get_finnhub_global_news
from .gdelt_news import get_news as get_gdelt_news, get_global_news as get_gdelt_global_news
from .google_news import get_news as get_google_news
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
    get_indicator as get_alpha_vantage_indicator,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_income_statement as get_alpha_vantage_income_statement,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news,
)
from .alpha_vantage_common import AlphaVantageRateLimitError

# Configuration and routing logic
from .config import get_config

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    }
}

VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
    "finnhub",
    "gdelt",
    "google_news",
    "pandas_ta",
]

NEWS_METHODS = frozenset({"get_news", "get_global_news"})

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
        "pandas_ta": get_indicators_ta,
    },
    # fundamental_data
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
    },
    # news_data
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "finnhub": get_finnhub_news,
        "gdelt": get_gdelt_news,
        # google_news is company-news only: the RSS search endpoint needs a
        # subject to search for, so there is no get_global_news counterpart.
        "google_news": get_google_news,
        "yfinance": get_news_yfinance,
    },
    "get_global_news": {
        "alpha_vantage": get_alpha_vantage_global_news,
        "finnhub": get_finnhub_global_news,
        "gdelt": get_gdelt_global_news,
        "yfinance": get_global_news_yfinance,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

def _resolve_impl(method: str, vendor: str):
    """Return the callable for ``vendor``, or None when it offers no impl."""
    vendor_impl = VENDOR_METHODS[method].get(vendor)
    if vendor_impl is None:
        return None
    return vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl


def _invoke_vendor(method: str, vendor: str, impl_func, args, kwargs):
    """Call one vendor implementation, translating failures uniformly.

    Returns ``(succeeded, payload)``. On success ``payload`` is the vendor's
    result. On failure ``payload`` is an error string to remember, or None to
    skip the vendor without recording anything.

    This is shared by both the merge pass and the fallback pass on purpose.
    The two used to carry separate copies of this logic, and the copies drifted:
    the merge pass caught only AlphaVantageRateLimitError, so any vendor raising
    a network error there would have crashed the run rather than falling back.
    """
    try:
        result = impl_func(*args, **kwargs)
    except AlphaVantageRateLimitError:
        # Skip silently, preserving long-standing behaviour: a rate-limited
        # vendor is not a data error worth surfacing to the analyst.
        return False, None
    except requests.exceptions.RequestException as exc:
        # Must come before the bare ValueError clause below:
        # requests.exceptions.JSONDecodeError (a malformed/empty response
        # body, e.g. GDELT returning "" instead of JSON) is BOTH a
        # RequestException and a ValueError. Python matches except
        # clauses in source order, not MRO, so with ValueError listed
        # first this fell into the "missing API key" branch below,
        # didn't match that message pattern, and re-raised — crashing
        # the whole run instead of falling back to the next vendor.
        if method in NEWS_METHODS:
            return False, f"Error fetching {method} from {vendor}: {exc}"
        raise
    except ValueError as exc:
        if "environment variable is not set" in str(exc):
            return False, None
        raise

    if isinstance(result, str) and _is_vendor_error_result(result):
        return False, result
    return True, result


def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',') if v.strip()]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Build fallback chain: primary vendors first, then remaining available vendors
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    last_error_result = None

    # News vendors listed in `merged_news_vendors` are UNIONED instead of
    # first-wins, so a thin response from one vendor no longer becomes the
    # whole news picture for the run. Defaults to empty when the key is
    # absent, which keeps first-wins behaviour for any config that predates
    # this setting; DEFAULT_CONFIG supplies the real value.
    # Gated on NEWS_METHODS here rather than at the merge block alone: the
    # fallback loop below skips whatever is in `merge_vendors`, so leaving it
    # populated for a non-news method would skip those vendors in the loop
    # while the merge pass never ran — silently dropping every configured
    # vendor for e.g. get_stock_data.
    merged_vendors = set(get_config().get("merged_news_vendors") or ())
    merge_vendors = (
        [v for v in primary_vendors if v in merged_vendors]
        if method in NEWS_METHODS
        else []
    )

    if merge_vendors:
        merged_results = []
        failed_vendors = []
        for vendor in merge_vendors:
            impl_func = _resolve_impl(method, vendor)
            if impl_func is None:
                continue
            ok, payload = _invoke_vendor(method, vendor, impl_func, args, kwargs)
            if ok:
                merged_results.append(payload)
            else:
                failed_vendors.append(vendor)
                if payload is not None:
                    last_error_result = payload
        if merged_results:
            blocks = [str(result) for result in merged_results]
            if failed_vendors:
                # Surface partial coverage. Silently returning only the
                # surviving vendor is how a throttled GDELT became invisible:
                # the analyst saw a thin yfinance-only result and read it as
                # "little news exists" rather than "one source was down", and
                # reported the absence as a finding. Sentiment analysts already
                # get this signal via "<stocktwits unavailable>" placeholders;
                # news deserves the same.
                blocks.append(
                    f"_Coverage note: {', '.join(failed_vendors)} returned no usable "
                    "result for this fetch (unavailable or rate limited), so the news "
                    "above is from the remaining source(s) only. Treat absence of "
                    "company news as unconfirmed rather than as evidence that none "
                    "exists._"
                )
            return "\n\n".join(blocks)

    for vendor in fallback_vendors:
        if vendor in merge_vendors:
            continue  # already attempted in the merge pass above
        if vendor not in VENDOR_METHODS[method]:
            continue

        impl_func = _resolve_impl(method, vendor)
        if impl_func is None:
            continue

        ok, payload = _invoke_vendor(method, vendor, impl_func, args, kwargs)
        if ok:
            return payload
        if payload is not None:
            last_error_result = payload

    if last_error_result is not None:
        return last_error_result

    raise RuntimeError(f"No available vendor for '{method}'")


def _is_vendor_error_result(result: str) -> bool:
    """Return True for vendor responses that should trigger fallback.

    Some data vendors return user-facing error strings instead of raising
    exceptions, for example Alpha Vantage CSV endpoints can return no rows for
    an indicator. Treat those as fallback-worthy so the next configured vendor
    gets a chance before the analyst sees an empty-data error.
    """
    normalized = result.strip().lower()
    return (
        normalized.startswith(_EMPTY_RESULT_PREFIXES)
        or "no relevant articles found" in normalized
    )


# Prefixes marking "this vendor ran fine but has nothing", as distinct from a
# real payload. Getting this list wrong is not cosmetic: under first-wins an
# unmatched empty message merely delayed the fallback, but under merging it is
# treated as content and concatenated into the prompt. Observed live on the
# BLUEJET run (2026-08-11) — yfinance's "No news found for BLUEJET.NS between
# ..." was appended verbatim directly beneath 30 real Google News articles, so
# the block ended with a flat statement that no news existed. It also
# suppressed the partial-coverage note, because a vendor that "succeeded" is
# not counted as failed.
_EMPTY_RESULT_PREFIXES = (
    "error:",
    "error retrieving",
    "error fetching",
    "<no ",
    "no news found",
    "no google news found",
    "no finnhub ",
    "no gdelt ",
)
