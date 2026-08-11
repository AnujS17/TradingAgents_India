from unittest.mock import MagicMock, patch

import pytest

from tradingagents.agents.utils.agent_utils import resolve_ticker_symbol
from tradingagents.graph.propagation import Propagator


def _fake_ticker(responses: dict):
    """responses: {symbol: info_dict_or_None}. Missing symbols get {} (no previousClose)."""

    def make(symbol):
        ticker = MagicMock()
        ticker.info = responses.get(symbol, {})
        return ticker

    return make


@pytest.mark.unit
def test_resolves_bare_ticker_to_ns_suffix():
    responses = {
        "RELIANCE": {},
        "RELIANCE.NS": {"longName": "Reliance Industries Limited", "previousClose": 1334.8},
    }
    with patch(
        "tradingagents.agents.utils.agent_utils.yf.Ticker",
        side_effect=_fake_ticker(responses),
    ):
        resolve_ticker_symbol.cache_clear()
        assert resolve_ticker_symbol("RELIANCE", "stock") == "RELIANCE.NS"


@pytest.mark.unit
def test_falls_back_to_bo_when_ns_also_fails():
    responses = {
        "SOMEBSEONLY": {},
        "SOMEBSEONLY.NS": {},
        "SOMEBSEONLY.BO": {"longName": "Some BSE-Only Co", "previousClose": 42.0},
    }
    with patch(
        "tradingagents.agents.utils.agent_utils.yf.Ticker",
        side_effect=_fake_ticker(responses),
    ):
        resolve_ticker_symbol.cache_clear()
        assert resolve_ticker_symbol("SOMEBSEONLY", "stock") == "SOMEBSEONLY.BO"


@pytest.mark.unit
def test_leaves_already_qualified_tickers_unchanged():
    resolve_ticker_symbol.cache_clear()
    # No yf.Ticker call should even happen for these — short-circuited before
    # any network attempt.
    with patch("tradingagents.agents.utils.agent_utils.yf.Ticker") as mock_ticker:
        assert resolve_ticker_symbol("CNC.TO", "stock") == "CNC.TO"
        assert resolve_ticker_symbol("BTC-USD", "crypto") == "BTC-USD"
        mock_ticker.assert_not_called()


@pytest.mark.unit
def test_leaves_crypto_unchanged_even_without_dash():
    resolve_ticker_symbol.cache_clear()
    with patch("tradingagents.agents.utils.agent_utils.yf.Ticker") as mock_ticker:
        assert resolve_ticker_symbol("BTC", "crypto") == "BTC"
        mock_ticker.assert_not_called()


@pytest.mark.unit
def test_falls_back_to_original_when_nothing_resolves():
    resolve_ticker_symbol.cache_clear()
    with patch(
        "tradingagents.agents.utils.agent_utils.yf.Ticker",
        side_effect=_fake_ticker({}),
    ):
        assert resolve_ticker_symbol("TOTALLYFAKEXYZ", "stock") == "TOTALLYFAKEXYZ"


@pytest.mark.unit
def test_create_initial_state_uses_resolved_ticker():
    responses = {
        "RELIANCE": {},
        "RELIANCE.NS": {"longName": "Reliance Industries Limited", "previousClose": 1334.8},
    }
    with patch(
        "tradingagents.agents.utils.agent_utils.yf.Ticker",
        side_effect=_fake_ticker(responses),
    ):
        resolve_ticker_symbol.cache_clear()
        state = Propagator().create_initial_state("RELIANCE", "2026-08-10")

    assert state["company_of_interest"] == "RELIANCE.NS"
    assert "RELIANCE.NS" in state["instrument_context"]
