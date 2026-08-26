from unittest.mock import MagicMock, patch

import pytest

from tradingagents.agents.utils.agent_utils import TickerNotFoundError, resolve_ticker_symbol
from tradingagents.graph.propagation import Propagator


def _fake_ticker(responses: dict, history_map: dict | None = None):
    """responses: {symbol: info_dict}. Missing symbols get {} (no previousClose).

    history_map: {symbol: has_recent_history_bool}, for candidates whose
    history availability needs to diverge from the default. Missing symbols
    default to "has history iff previousClose is set" -- matching real
    yfinance's own correlation between a live quote and a history endpoint
    that returns rows, so tests written before the history check existed
    keep passing without every one of them needing an explicit entry.
    """
    history_map = history_map or {}

    def make(symbol):
        ticker = MagicMock()
        info = responses.get(symbol, {})
        ticker.info = info
        history = MagicMock()
        has_history = history_map.get(symbol, info.get("previousClose") is not None)
        history.empty = not has_history
        ticker.history.return_value = history
        return ticker

    return make


@pytest.fixture(autouse=True)
def _no_real_sleep():
    """Every probe now retries with real time.sleep() backoff -- stub it so
    tests that exercise the retry path (transient failures, total outage)
    don't actually wait."""
    with patch("tradingagents.agents.utils.agent_utils.time.sleep"):
        yield


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


@pytest.mark.unit
def test_rejects_a_quote_with_no_recent_history():
    """The actual bug: TORNTPOWER.NS (2026-08-25) failed transiently and
    fell through to TORNTPOWER.BO, whose quote endpoint answered fine
    (previousClose present) but whose OHLCV history was a single row from
    over a month earlier. get_verified_market_snapshot then built an
    entire technical read -- and the trader's entry price -- on that stale
    print. A live quote is no longer sufficient on its own; the candidate
    must also have recent history."""
    responses = {
        "GHOSTCO": {},
        "GHOSTCO.NS": {},
        "GHOSTCO.BO": {"longName": "Ghost Co", "previousClose": 100.0},
    }
    resolve_ticker_symbol.cache_clear()
    with patch(
        "tradingagents.agents.utils.agent_utils.yf.Ticker",
        # GHOSTCO.BO has a quote but no usable recent history.
        side_effect=_fake_ticker(responses, history_map={"GHOSTCO.BO": False}),
    ):
        with pytest.raises(TickerNotFoundError, match="GHOSTCO"):
            resolve_ticker_symbol("GHOSTCO", "stock")


@pytest.mark.unit
def test_accepts_a_candidate_with_both_quote_and_history():
    responses = {
        "GOODCO": {},
        "GOODCO.NS": {"longName": "Good Co", "previousClose": 50.0},
    }
    resolve_ticker_symbol.cache_clear()
    with patch(
        "tradingagents.agents.utils.agent_utils.yf.Ticker",
        side_effect=_fake_ticker(responses, history_map={"GOODCO.NS": True}),
    ):
        assert resolve_ticker_symbol("GOODCO", "stock") == "GOODCO.NS"


@pytest.mark.unit
def test_retries_a_transient_failure_before_falling_through():
    """A single unretried exception used to be enough to skip straight to
    .BO (the TORNTPOWER root cause). Confirms a candidate that fails once
    and succeeds on retry is still resolved on NSE, not abandoned."""
    calls = {"count": 0}
    good_info = {"longName": "Flaky Co", "previousClose": 10.0}

    def flaky_ticker(symbol):
        if symbol == "FLAKYCO.NS":
            calls["count"] += 1
            if calls["count"] == 1:
                raise ConnectionError("transient blip")
            ticker = MagicMock()
            ticker.info = good_info
            history = MagicMock()
            history.empty = False
            ticker.history.return_value = history
            return ticker
        ticker = MagicMock()
        ticker.info = {}
        return ticker

    resolve_ticker_symbol.cache_clear()
    with patch(
        "tradingagents.agents.utils.agent_utils.yf.Ticker",
        side_effect=flaky_ticker,
    ):
        assert resolve_ticker_symbol("FLAKYCO", "stock") == "FLAKYCO.NS"
    # 1 failed .info attempt + 1 successful .info retry + 1 successful
    # .history() call (a separate yf.Ticker() construction) = 3. The point
    # isn't the exact count, it's that the FIRST failure didn't end the
    # attempt -- resolution still landed on .NS, not .BO.
    assert calls["count"] == 3
