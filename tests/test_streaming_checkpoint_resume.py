"""Guard for propagate_streaming()'s checkpoint-resume wiring.

propagate_streaming, not propagate, is the ONLY path api.worker actually
calls (execute_run always passes on_token for the live view), so
checkpoint_enabled had zero effect on a real run until this was wired in
here too. Mirrors tests/test_checkpoint_resume.py's toy-graph approach, but
drives it through TradingAgentsGraph.propagate_streaming() itself so the
wiring -- not just the checkpointer primitive -- is under test.

The crash/resume count trick: a 2-node graph (analyst +1, trader +10) that
crashes at trader after analyst succeeds should resume at count=11
(analyst ran once, trader ran once). If a "resume" secretly re-ran analyst
too, the count would be 12 instead -- this is what actually caught the real
bug during development: the original checkpoint_enabled code in
_run_graph() always passed a fresh initial state instead of None on resume,
so LangGraph treated it as new input and re-ran every already-completed
node, checkpoint file or not.
"""

from typing import TypedDict
from unittest.mock import patch

import pytest
from langgraph.graph import END, StateGraph

from tradingagents.graph.checkpointer import checkpoint_step, get_checkpointer, has_checkpoint
from tradingagents.graph.trading_graph import TradingAgentsGraph


class _ToyState(TypedDict):
    count: int


class _StubPropagator:
    def create_initial_state(self, *_args, **_kwargs):
        return {"count": 0}

    def get_graph_args(self, *_args, **_kwargs):
        return {"stream_mode": "values", "config": {}}


class _StubMemoryLog:
    def get_past_context(self, *_args, **_kwargs):
        return ""

    def get_pending_entries(self, *_args, **_kwargs):
        return []


def _build_workflow(crash_flag: dict):
    def node_a(state):
        return {"count": state["count"] + 1}

    def node_b(state):
        if crash_flag["on"]:
            raise RuntimeError("simulated network drop")
        return {"count": state["count"] + 10}

    builder = StateGraph(_ToyState)
    builder.add_node("analyst", node_a)
    builder.add_node("trader", node_b)
    builder.set_entry_point("analyst")
    builder.add_edge("analyst", "trader")
    builder.add_edge("trader", END)
    return builder


def _graph(tmp_path, crash_flag: dict, checkpoint_enabled: bool):
    workflow = _build_workflow(crash_flag)
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.workflow = workflow
    graph.graph = workflow.compile()
    graph.propagator = _StubPropagator()
    graph.config = {
        "checkpoint_enabled": checkpoint_enabled,
        "data_cache_dir": str(tmp_path),
    }
    graph.debug = False
    graph.memory_log = _StubMemoryLog()
    graph._checkpointer_ctx = None
    graph.ticker = None
    graph._log_state = lambda *_args, **_kwargs: None
    return graph


@pytest.mark.unit
def test_a_crashed_run_resumes_without_rerunning_completed_nodes(tmp_path):
    crash_flag = {"on": True}
    graph = _graph(tmp_path, crash_flag, checkpoint_enabled=True)

    with patch(
        "tradingagents.graph.trading_graph.resolve_ticker_symbol",
        return_value="TESTCO",
    ):
        with pytest.raises(RuntimeError, match="simulated network drop"):
            graph.propagate_streaming("TESTCO", "2026-08-26")

        assert has_checkpoint(str(tmp_path), "TESTCO", "2026-08-26")
        assert checkpoint_step(str(tmp_path), "TESTCO", "2026-08-26") == 1  # analyst done

        crash_flag["on"] = False
        result = graph.propagate_streaming("TESTCO", "2026-08-26")

    # 0 +1 (analyst, run 1) +10 (trader, run 2) = 11. A secretly-re-run
    # analyst would make this 12 -- see module docstring.
    assert result["count"] == 11
    # Completed successfully: the checkpoint is cleared so a later, unrelated
    # run for this same ticker+date doesn't see stale state.
    assert not has_checkpoint(str(tmp_path), "TESTCO", "2026-08-26")


@pytest.mark.unit
def test_checkpointing_off_by_default_leaves_no_checkpoint_and_reruns_from_scratch(tmp_path):
    """The opt-in flag must actually gate the feature: with it off (the
    default), a crash leaves nothing behind, and the next call starts over
    -- exactly today's pre-existing behavior, unaffected by this change."""
    crash_flag = {"on": True}
    graph = _graph(tmp_path, crash_flag, checkpoint_enabled=False)

    with patch(
        "tradingagents.graph.trading_graph.resolve_ticker_symbol",
        return_value="TESTCO",
    ):
        with pytest.raises(RuntimeError, match="simulated network drop"):
            graph.propagate_streaming("TESTCO", "2026-08-26")

        assert not has_checkpoint(str(tmp_path), "TESTCO", "2026-08-26")

        crash_flag["on"] = False
        result = graph.propagate_streaming("TESTCO", "2026-08-26")

    # A full, independent restart: 0 +1 (analyst) +10 (trader) = 11.
    assert result["count"] == 11


class _ToyStateWithDecision(TypedDict):
    count: int
    final_trade_decision: str


def _build_decision_workflow(crash_flag: dict):
    """Same shape as _build_workflow, plus a final_trade_decision key --
    _run_graph() (unlike propagate_streaming) reads that key directly to
    feed memory_log.store_decision and process_signal."""

    def node_a(state):
        return {"count": state["count"] + 1}

    def node_b(state):
        if crash_flag["on"]:
            raise RuntimeError("simulated network drop")
        return {"count": state["count"] + 10, "final_trade_decision": "Hold"}

    builder = StateGraph(_ToyStateWithDecision)
    builder.add_node("analyst", node_a)
    builder.add_node("trader", node_b)
    builder.set_entry_point("analyst")
    builder.add_edge("analyst", "trader")
    builder.add_edge("trader", END)
    return builder


class _StubSignalProcessor:
    def process_signal(self, full_signal):
        return full_signal


@pytest.mark.unit
def test_run_graph_also_resumes_without_rerunning_completed_nodes(tmp_path):
    """_run_graph() is propagate()'s (non-streaming) execution path -- this
    is the bug fix verified directly: it used to always pass a fresh
    init_agent_state to graph.invoke(), even when a checkpoint already
    existed, which made LangGraph re-run every already-completed node on
    every 'resume' (see module docstring for how the count trick catches
    this)."""
    crash_flag = {"on": True}
    workflow = _build_decision_workflow(crash_flag)

    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.workflow = workflow
    graph.propagator = _StubPropagator()
    graph.config = {"checkpoint_enabled": True, "data_cache_dir": str(tmp_path)}
    graph.debug = False
    graph.memory_log = _StubMemoryLog()
    graph.memory_log.store_decision = lambda **_kwargs: None
    graph.signal_processor = _StubSignalProcessor()
    graph._log_state = lambda *_args, **_kwargs: None

    with get_checkpointer(str(tmp_path), "TESTCO") as saver:
        graph.graph = workflow.compile(checkpointer=saver)
        with pytest.raises(RuntimeError, match="simulated network drop"):
            graph._run_graph("TESTCO", "2026-08-26")

    assert has_checkpoint(str(tmp_path), "TESTCO", "2026-08-26")
    assert checkpoint_step(str(tmp_path), "TESTCO", "2026-08-26") == 1  # analyst done

    crash_flag["on"] = False
    with get_checkpointer(str(tmp_path), "TESTCO") as saver:
        graph.graph = workflow.compile(checkpointer=saver)
        final_state, _signal = graph._run_graph("TESTCO", "2026-08-26")

    assert final_state["count"] == 11  # not 12 -- see module docstring
    assert not has_checkpoint(str(tmp_path), "TESTCO", "2026-08-26")


def _build_tracked_workflow(crash_flag: dict, calls: list):
    """Like _build_workflow, but records which nodes actually executed --
    needed because a 2-node graph's final count alone can't tell "started
    fresh, analyst ran once" apart from "resumed, analyst's earlier run
    still counts" (both land on the same number). Call order is the only
    unambiguous signal that a node was skipped vs re-run."""

    def node_a(state):
        calls.append("analyst")
        return {"count": state["count"] + 1}

    def node_b(state):
        calls.append("trader")
        if crash_flag["on"]:
            raise RuntimeError("simulated network drop")
        return {"count": state["count"] + 10}

    builder = StateGraph(_ToyState)
    builder.add_node("analyst", node_a)
    builder.add_node("trader", node_b)
    builder.set_entry_point("analyst")
    builder.add_edge("analyst", "trader")
    builder.add_edge("trader", END)
    return builder


@pytest.mark.unit
def test_a_normal_non_resume_call_clears_a_stale_checkpoint_and_reruns_from_scratch(tmp_path):
    """resume defaults to False. That default has to actively clear any
    checkpoint left by an unrelated earlier attempt at this exact
    (ticker, date) -- otherwise a deliberate fresh run (e.g. re-running the
    same ticker+date to compare two models, a workflow this project's
    history leans on heavily) would silently and invisibly resume from
    stale state instead of genuinely starting over."""
    crash_flag = {"on": True}
    calls: list = []
    workflow = _build_tracked_workflow(crash_flag, calls)

    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.workflow = workflow
    graph.graph = workflow.compile()
    graph.propagator = _StubPropagator()
    graph.config = {"checkpoint_enabled": True, "data_cache_dir": str(tmp_path)}
    graph.debug = False
    graph.memory_log = _StubMemoryLog()
    graph._checkpointer_ctx = None
    graph.ticker = None
    graph._log_state = lambda *_args, **_kwargs: None

    with patch(
        "tradingagents.graph.trading_graph.resolve_ticker_symbol",
        return_value="TESTCO",
    ):
        with pytest.raises(RuntimeError, match="simulated network drop"):
            graph.propagate_streaming("TESTCO", "2026-08-26")

        assert has_checkpoint(str(tmp_path), "TESTCO", "2026-08-26")

        calls.clear()
        crash_flag["on"] = False
        graph.propagate_streaming("TESTCO", "2026-08-26")  # resume not passed -> default False

    # The checkpoint was cleared before this call, so it's a genuine fresh
    # start: analyst re-enters rather than being skipped.
    assert calls == ["analyst", "trader"]


@pytest.mark.unit
def test_an_explicit_resume_call_preserves_the_checkpoint_and_skips_completed_nodes(tmp_path):
    """The mirror image of the test above: resume=True must NOT clear the
    checkpoint, so the already-completed node is skipped."""
    crash_flag = {"on": True}
    calls: list = []
    workflow = _build_tracked_workflow(crash_flag, calls)

    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.workflow = workflow
    graph.graph = workflow.compile()
    graph.propagator = _StubPropagator()
    graph.config = {"checkpoint_enabled": True, "data_cache_dir": str(tmp_path)}
    graph.debug = False
    graph.memory_log = _StubMemoryLog()
    graph._checkpointer_ctx = None
    graph.ticker = None
    graph._log_state = lambda *_args, **_kwargs: None

    with patch(
        "tradingagents.graph.trading_graph.resolve_ticker_symbol",
        return_value="TESTCO",
    ):
        with pytest.raises(RuntimeError, match="simulated network drop"):
            graph.propagate_streaming("TESTCO", "2026-08-26")

        calls.clear()
        crash_flag["on"] = False
        graph.propagate_streaming("TESTCO", "2026-08-26", resume=True)

    assert calls == ["trader"]  # analyst skipped -- resumed from the checkpoint
