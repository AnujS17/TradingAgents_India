from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tradingagents.dataflows import y_finance


FAKE_FX_RATE = SimpleNamespace(from_currency="TWD", to_currency="USD", rate=0.0309, as_of="2026-06-01")


@pytest.fixture(autouse=True)
def reset_yfinance_caches():
    """Several tests below reuse ticker "UMC" with different mocked
    ``.info``/statement data. y_finance's fetchers are now lru_cache'd (see
    snapshot_cache.py), which is process-lifetime and args-only -- without
    clearing it between tests, a later test with the same ticker would
    silently read an earlier test's cached (and possibly stale) mock data
    instead of exercising its own, exactly the hazard
    test_india_news_fetcher.py's own reset_config fixture guards against."""
    y_finance._fetch_info_cached.cache_clear()
    y_finance._fetch_balance_sheet_csv.cache_clear()
    y_finance._fetch_cashflow_csv.cache_clear()
    y_finance._fetch_income_statement_csv.cache_clear()
    yield
    y_finance._fetch_info_cached.cache_clear()
    y_finance._fetch_balance_sheet_csv.cache_clear()
    y_finance._fetch_cashflow_csv.cache_clear()
    y_finance._fetch_income_statement_csv.cache_clear()


@pytest.mark.unit
def test_fundamentals_includes_statement_and_quote_currency_warning():
    ticker = MagicMock()
    ticker.info = {
        "longName": "United Microelectronics Corporation",
        "financialCurrency": "TWD",
        "currency": "USD",
        "totalRevenue": 240_700_000_000,
    }

    with patch("tradingagents.dataflows.y_finance.yf.Ticker", return_value=ticker), patch(
        "tradingagents.dataflows.fx_rates.fetch_fx_rate", return_value=FAKE_FX_RATE
    ):
        result = y_finance.get_fundamentals("UMC", "2026-06-01")

    assert "# Financial statement currency: TWD" in result
    assert "# Quote/price currency: USD" in result
    assert "not converted to USD" in result
    assert "Revenue (TTM): 240700000000" in result
    assert "1 TWD = 0.0309 USD" in result
    assert "as of 2026-06-01" in result


@pytest.mark.unit
def test_statement_output_includes_currency_warning_before_raw_csv_values():
    ticker = MagicMock()
    ticker.info = {"financialCurrency": "TWD", "currency": "USD"}
    ticker.balance_sheet = pd.DataFrame(
        {pd.Timestamp("2025-12-31"): [110_660_052_000]},
        index=["Cash And Cash Equivalents"],
    )

    with patch("tradingagents.dataflows.y_finance.yf.Ticker", return_value=ticker), patch(
        "tradingagents.dataflows.fx_rates.fetch_fx_rate", return_value=FAKE_FX_RATE
    ):
        result = y_finance.get_balance_sheet("UMC", freq="annual", curr_date="2026-06-01")

    assert "# Financial statement currency: TWD" in result
    assert "# Quote/price currency: USD" in result
    assert "raw financial statement values" in result
    assert "Cash And Cash Equivalents,110660052000" in result
    assert "1 TWD = 0.0309 USD" in result


@pytest.mark.unit
def test_currency_warning_notes_when_live_rate_unavailable():
    ticker = MagicMock()
    ticker.info = {
        "longName": "United Microelectronics Corporation",
        "financialCurrency": "TWD",
        "currency": "USD",
        "totalRevenue": 240_700_000_000,
    }

    with patch("tradingagents.dataflows.y_finance.yf.Ticker", return_value=ticker), patch(
        "tradingagents.dataflows.fx_rates.fetch_fx_rate", return_value=None
    ):
        result = y_finance.get_fundamentals("UMC", "2026-06-01")

    assert "# Financial statement currency: TWD" in result
    assert "could not be" in result
    assert "do not assume a 1:1 rate or invent a conversion" in result
