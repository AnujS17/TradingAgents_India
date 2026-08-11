"""One resolved ticker identity per run, across every path that keys off it.

Ticker resolution used to happen inside create_initial_state(), i.e. after the
results directory, memory-log key and checkpoint id had already been derived
from the raw user input. A run typed as "BLUEJET" therefore analysed
BLUEJET.NS while filing its logs, memory entries and checkpoint under
"BLUEJET" — the same company under two identities depending on how it was
typed, splitting the per-ticker history that deferred reflection reads back
(observed on the BLUEJET run, 2026-08-11).
"""

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.agents.utils.agent_utils import resolve_ticker_symbol
from tradingagents.graph.trading_graph import TradingAgentsGraph


@pytest.fixture(autouse=True)
def _clear_resolution_cache():
    resolve_ticker_symbol.cache_clear()
    yield
    resolve_ticker_symbol.cache_clear()


def _graph_with_stubs():
    """A TradingAgentsGraph with only the pieces propagate() touches."""
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {"checkpoint_enabled": False, "results_dir": "results"}
    graph.debug = False
    graph.memory_log = MagicMock()
    graph.memory_log.get_past_context.return_value = ""
    graph.propagator = MagicMock()
    graph.propagator.get_graph_args.return_value = {}
    graph.graph = MagicMock()
    graph.graph.invoke.return_value = {"final_trade_decision": "HOLD"}
    graph._log_state = MagicMock()
    graph._resolve_pending_entries = MagicMock()
    graph.process_signal = MagicMock(return_value="HOLD")
    graph._checkpointer_ctx = None  # propagate()'s finally-block reads this
    return graph


@pytest.mark.unit
def test_propagate_resolves_ticker_before_setting_identity():
    graph = _graph_with_stubs()

    with patch(
        "tradingagents.graph.trading_graph.resolve_ticker_symbol",
        return_value="BLUEJET.NS",
    ):
        graph.propagate("BLUEJET", "2026-08-11")

    assert graph.ticker == "BLUEJET.NS"


@pytest.mark.unit
def test_memory_log_is_keyed_on_the_resolved_ticker():
    # get_past_context and store_decision must agree, or a run reads back its
    # own history under one name and writes it under another.
    graph = _graph_with_stubs()

    with patch(
        "tradingagents.graph.trading_graph.resolve_ticker_symbol",
        return_value="BLUEJET.NS",
    ):
        graph.propagate("BLUEJET", "2026-08-11")

    graph.memory_log.get_past_context.assert_called_once_with("BLUEJET.NS")
    assert graph.memory_log.store_decision.call_args.kwargs["ticker"] == "BLUEJET.NS"


@pytest.mark.unit
def test_pending_entries_resolved_under_the_resolved_ticker():
    graph = _graph_with_stubs()

    with patch(
        "tradingagents.graph.trading_graph.resolve_ticker_symbol",
        return_value="BLUEJET.NS",
    ):
        graph.propagate("BLUEJET", "2026-08-11")

    graph._resolve_pending_entries.assert_called_once_with("BLUEJET.NS")


@pytest.mark.unit
def test_initial_state_receives_the_resolved_ticker():
    graph = _graph_with_stubs()

    with patch(
        "tradingagents.graph.trading_graph.resolve_ticker_symbol",
        return_value="BLUEJET.NS",
    ):
        graph.propagate("BLUEJET", "2026-08-11")

    assert graph.propagator.create_initial_state.call_args.args[0] == "BLUEJET.NS"


@pytest.mark.unit
def test_already_suffixed_ticker_is_unchanged():
    # Typing the resolved form must land on the same identity as typing the
    # bare form — that equivalence is the whole point.
    graph = _graph_with_stubs()

    with patch(
        "tradingagents.graph.trading_graph.resolve_ticker_symbol",
        return_value="BLUEJET.NS",
    ):
        graph.propagate("BLUEJET.NS", "2026-08-11")

    assert graph.ticker == "BLUEJET.NS"
    graph.memory_log.get_past_context.assert_called_once_with("BLUEJET.NS")


@pytest.mark.unit
def test_unresolvable_ticker_falls_back_to_input_without_crashing():
    # resolve_ticker_symbol fails open (network down, unknown symbol); the run
    # must continue under the typed name rather than abort.
    graph = _graph_with_stubs()

    with patch(
        "tradingagents.graph.trading_graph.resolve_ticker_symbol",
        return_value="WEIRDTICK",
    ):
        graph.propagate("WEIRDTICK", "2026-08-11")

    assert graph.ticker == "WEIRDTICK"
