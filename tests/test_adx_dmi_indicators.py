from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
from tradingagents.dataflows.y_finance import get_stock_stats_indicators_window


def _sample_ohlcv(rows=60):
    dates = pd.date_range("2026-03-01", periods=rows, freq="D")
    base = pd.Series(range(rows), dtype=float)
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": 100 + base,
            "High": 102 + base,
            "Low": 98 + base,
            "Close": 101 + base,
            "Volume": 1_000_000 + (base * 100),
        }
    )


@pytest.mark.unit
def test_yfinance_adx_is_supported():
    with patch("tradingagents.dataflows.y_finance.load_ohlcv", return_value=_sample_ohlcv()):
        result = get_stock_stats_indicators_window("MSFT", "adx", "2026-04-29", 5)

    assert "## ADX values" in result
    assert "Average Directional Index" in result
    assert "Indicator adx is not supported" not in result


@pytest.mark.unit
def test_yfinance_dmi_returns_directional_components():
    with patch("tradingagents.dataflows.y_finance.load_ohlcv", return_value=_sample_ohlcv()):
        result = get_stock_stats_indicators_window("MSFT", "dmi", "2026-04-29", 5)

    assert "## DMI (ADX, +DI, -DI) values" in result
    assert "ADX=" in result
    assert "+DI=" in result
    assert "-DI=" in result


@pytest.mark.unit
def test_alpha_vantage_adx_uses_adx_endpoint():
    csv = "time,ADX\n2026-04-28,27.5\n2026-04-29,29.1\n"

    with patch("tradingagents.dataflows.alpha_vantage_indicator._make_api_request", return_value=csv) as request:
        result = get_indicator("MSFT", "adx", "2026-04-29", 5)

    request.assert_called_once()
    assert request.call_args.args[0] == "ADX"
    assert "2026-04-29: 29.1" in result
    assert "Average Directional Index" in result


@pytest.mark.unit
def test_alpha_vantage_dmi_combines_adx_plus_di_minus_di():
    responses = {
        "ADX": "time,ADX\n2026-04-29,29.1\n",
        "PLUS_DI": "time,PLUS_DI\n2026-04-29,31.2\n",
        "MINUS_DI": "time,MINUS_DI\n2026-04-29,18.4\n",
    }

    with patch(
        "tradingagents.dataflows.alpha_vantage_indicator._make_api_request",
        side_effect=lambda function, params: responses[function],
    ) as request:
        result = get_indicator("MSFT", "dmi", "2026-04-29", 5)

    assert [call.args[0] for call in request.call_args_list] == ["ADX", "PLUS_DI", "MINUS_DI"]
    assert "2026-04-29: ADX=29.1 | +DI=31.2 | -DI=18.4" in result
    assert "Directional Movement Index" in result
