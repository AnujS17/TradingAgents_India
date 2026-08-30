from .alpha_vantage_common import _cached_api_request


def _filter_reports_by_date(result, curr_date: str):
    """Filter annualReports/quarterlyReports to exclude entries after curr_date.

    Prevents look-ahead bias by removing fiscal periods that end after
    the simulation's current date.

    Returns a NEW dict rather than mutating ``result`` in place: ``result``
    now commonly comes straight out of _cached_api_request's lru_cache, which
    hands back the SAME dict object on every hit. An in-place filter used to
    be harmless when every call got a fresh dict from a live request; against
    a cached object it would permanently shrink the shared cache entry on the
    first call (and re-filter an already-filtered entry against a second
    curr_date on the next), corrupting it for every later caller.
    """
    if not curr_date or not isinstance(result, dict):
        return result
    filtered = dict(result)
    for key in ("annualReports", "quarterlyReports"):
        if key in filtered:
            filtered[key] = [
                r for r in filtered[key]
                if r.get("fiscalDateEnding", "") <= curr_date
            ]
    return filtered


def get_fundamentals(ticker: str, curr_date: str = None) -> str:
    """
    Retrieve comprehensive fundamental data for a given ticker symbol using Alpha Vantage.

    Args:
        ticker (str): Ticker symbol of the company
        curr_date (str): Current date you are trading at, yyyy-mm-dd (not used for Alpha Vantage)

    Returns:
        str: Company overview data including financial ratios and key metrics
    """
    return _cached_api_request("OVERVIEW", (("symbol", ticker),))


# freq is accepted (the caller -- fundamentals_analyst.py's pre-fetch --
# always passes both "annual" and "quarterly") but never reaches the API:
# Alpha Vantage's BALANCE_SHEET/CASH_FLOW/INCOME_STATEMENT endpoints return
# annualReports AND quarterlyReports together in one response regardless of
# any parameter, so the two freq calls were always fetching the identical
# resource twice. Routing both through the shared _cached_api_request cache
# collapses that same-run duplicate into one live call (same cache key),
# on top of making a same-day re-run replay instead of re-fetch.
def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str = None):
    """Retrieve balance sheet data for a given ticker symbol using Alpha Vantage."""
    result = _cached_api_request("BALANCE_SHEET", (("symbol", ticker),))
    return _filter_reports_by_date(result, curr_date)


def get_cashflow(ticker: str, freq: str = "quarterly", curr_date: str = None):
    """Retrieve cash flow statement data for a given ticker symbol using Alpha Vantage."""
    result = _cached_api_request("CASH_FLOW", (("symbol", ticker),))
    return _filter_reports_by_date(result, curr_date)


def get_income_statement(ticker: str, freq: str = "quarterly", curr_date: str = None):
    """Retrieve income statement data for a given ticker symbol using Alpha Vantage."""
    result = _cached_api_request("INCOME_STATEMENT", (("symbol", ticker),))
    return _filter_reports_by_date(result, curr_date)

