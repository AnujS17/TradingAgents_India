from datetime import datetime
from .alpha_vantage_common import _make_api_request, _filter_csv_by_date_range

def get_stock(
    symbol: str,
    start_date: str,
    end_date: str
) -> str:
    """
    Returns raw daily OHLCV values filtered to the specified date range.

    Args:
        symbol: The name of the equity. For example: symbol=IBM
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        CSV string containing the daily time series data filtered to the date range.
    """
    # Parse dates to determine the range
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    today = datetime.now()

    # Choose outputsize based on whether the requested range is within the latest 100 days
    # Compact returns latest 100 data points, so check if start_date is recent enough
    days_from_today_to_start = (today - start_dt).days
    outputsize = "compact" if days_from_today_to_start < 100 else "full"

    params = {
        "symbol": symbol,
        "outputsize": outputsize,
        "datatype": "csv",
    }

    # TIME_SERIES_DAILY, not TIME_SERIES_DAILY_ADJUSTED: the adjusted
    # variant is gated behind Alpha Vantage's premium tier -- confirmed
    # live (2026-08-25), a free key gets back an "Information: this is a
    # premium endpoint" body instead of any stock data, meaning every
    # caller of this function (including get_stock_data's own
    # alpha_vantage vendor in dataflows/interface.py) was silently
    # non-functional. This is unadjusted (no split/dividend adjustment),
    # unlike yfinance's own auto_adjust=True history elsewhere in this
    # codebase -- a real but minor precision gap, and one that only
    # matters when this endpoint is actually reached (a yfinance outage),
    # for a name with a very recent split.
    response = _make_api_request("TIME_SERIES_DAILY", params)

    return _filter_csv_by_date_range(response, start_date, end_date)