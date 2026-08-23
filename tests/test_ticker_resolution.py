from unittest.mock import MagicMock, patch

import pytest

from tradingagents.agents.utils.agent_utils import TickerNotFoundError, resolve_ticker_symbol
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
def test_raises_when_confirmed_absent_on_both_exchanges():
    # NSE and BSE both genuinely answered (no exception, just no
    # previousClose) -- this is a real "not found", so it must error, not
    # silently fall back to a possibly-wrong-country ticker.
    resolve_ticker_symbol.cache_clear()
    with patch(
        "tradingagents.agents.utils.agent_utils.yf.Ticker",
        side_effect=_fake_ticker({}),
    ):
        with pytest.raises(TickerNotFoundError, match="TOTALLYFAKEXYZ"):
            resolve_ticker_symbol("TOTALLYFAKEXYZ", "stock")


@pytest.mark.unit
def test_never_resolves_to_a_bare_ticker_even_when_it_would_succeed():
    # The exact bug this guards: "HAL" is a real NYSE ticker (Halliburton)
    # and "MCX" collides with an unrelated US-listed symbol. The bare form
    # must never be probed or returned for a stock -- only .NS/.BO count.
    responses = {
        "HAL": {"longName": "Halliburton Company", "previousClose": 38.0},  # must be ignored
        "HAL.NS": {},
        "HAL.BO": {},
    }
    resolve_ticker_symbol.cache_clear()
    with patch(
        "tradingagents.agents.utils.agent_utils.yf.Ticker",
        side_effect=_fake_ticker(responses),
    ) as mock_ticker:
        with pytest.raises(TickerNotFoundError, match="HAL"):
            resolve_ticker_symbol("HAL", "stock")

    # The bare "HAL" candidate must never even have been queried.
    queried = {call.args[0] for call in mock_ticker.call_args_list}
    assert "HAL" not in queried
    assert queried == {"HAL.NS", "HAL.BO"}


@pytest.mark.unit
def test_fails_open_when_every_probe_raises():
    # Total network/API trouble (not a "not found" answer) must still not
    # block the run -- fall back to the input unchanged, same as before.
    def _always_raises(_symbol):
        raise ConnectionError("yfinance unreachable")

    resolve_ticker_symbol.cache_clear()
    with patch(
        "tradingagents.agents.utils.agent_utils.yf.Ticker",
        side_effect=_always_raises,
    ):
        assert resolve_ticker_symbol("RELIANCE", "stock") == "RELIANCE"


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
