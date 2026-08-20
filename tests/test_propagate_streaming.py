"""Guard for TradingAgentsGraph.propagate_streaming's callback contract.

Does not call a real LLM provider -- self.graph is replaced with a fake
compiled graph yielding a fixed, hand-built sequence of (stream_mode,
chunk) tuples matching LangGraph's real shape for stream_mode=
["values", "messages"].
"""

from unittest.mock import patch

import pytest

from tradingagents.graph.trading_graph import TradingAgentsGraph


class _FakeMessageChunk:
    def __init__(self, content: str):
        self.content = content


class _FakeCompiledGraph:
    def __init__(self, chunks):
        self._chunks = chunks

    def stream(self, _initial_state, stream_mode=None, **_kwargs):
        for mode, payload in self._chunks:
            yield mode, payload


class _StubPropagator:
    def create_initial_state(self, *_args, **_kwargs):
        return {}

    def get_graph_args(self, *_args, **_kwargs):
        return {"stream_mode": "values", "config": {}}


class _StubMemoryLog:
    def get_past_context(self, *_args, **_kwargs):
        return ""

    def get_pending_entries(self, *_args, **_kwargs):
        # Real _resolve_pending_entries() returns immediately when this is
        # empty -- no benchmark/reflector/batch-write side effects to stub.
        return []


def _graph_with_stubs(chunks):
    """A TradingAgentsGraph with only the pieces propagate_streaming() touches.

    Mirrors the precedent in test_ticker_identity_consistency.py::_graph_with_stubs
    (instance-level monkeypatch of the disk-logging side effect), adapted for
    the new method. _log_state is stubbed out because it reads many
    final_trade_decision-shaped keys that are irrelevant to the streaming
    callback contract under test here -- propagate()'s own tests already
    cover its real behavior.
    """
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.graph = _FakeCompiledGraph(chunks)
    graph.propagator = _StubPropagator()
    graph.workflow = None
    graph.config = {}
    graph.debug = False
    graph.memory_log = _StubMemoryLog()
    graph._checkpointer_ctx = None
    graph.ticker = None
    graph._log_state = lambda *_args, **_kwargs: None
    return graph


@pytest.mark.unit
def test_on_token_fires_for_each_messages_chunk_with_node_and_delta():
    chunks = [
        ("values", {"market_report": ""}),
        ("messages", (_FakeMessageChunk("Bull"), {"langgraph_node": "bull_researcher"})),
        ("messages", (_FakeMessageChunk(" case"), {"langgraph_node": "bull_researcher"})),
        ("values", {"market_report": "final text"}),
    ]
    seen = []
    graph = _graph_with_stubs(chunks)

    with patch(
        "tradingagents.graph.trading_graph.resolve_ticker_symbol",
        return_value="TESTCO",
    ):
        result = graph.propagate_streaming(
            "TESTCO", "2026-08-19", on_token=lambda node, delta: seen.append((node, delta))
        )

    assert seen == [("bull_researcher", "Bull"), ("bull_researcher", " case")]
    assert result == {"market_report": "final text"}


@pytest.mark.unit
def test_on_token_failure_never_raises_into_propagate_streaming():
    chunks = [("messages", (_FakeMessageChunk("x"), {"langgraph_node": "n"}))]
    graph = _graph_with_stubs(chunks)

    def exploding_callback(_node, _delta):
        raise RuntimeError("db locked")

    with patch(
        "tradingagents.graph.trading_graph.resolve_ticker_symbol",
        return_value="TESTCO",
    ):
        # Must not raise, despite the callback exploding on every call.
        graph.propagate_streaming("TESTCO", "2026-08-19", on_token=exploding_callback)


@pytest.mark.unit
def test_on_token_none_behaves_like_no_callback_was_passed():
    chunks = [
        ("messages", (_FakeMessageChunk("x"), {"langgraph_node": "n"})),
        ("values", {"market_report": "done"}),
    ]
    graph = _graph_with_stubs(chunks)

    with patch(
        "tradingagents.graph.trading_graph.resolve_ticker_symbol",
        return_value="TESTCO",
    ):
        result = graph.propagate_streaming("TESTCO", "2026-08-19")  # no on_token

    assert result == {"market_report": "done"}
