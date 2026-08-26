"""llm_timeout_seconds -> `timeout` kwarg on every provider client.

Bounds a single LLM call's worst case. Before this, a non-streaming
structured-output call (Research Manager/Trader/Portfolio Manager) had no
upper bound, and cooperative cancellation (should_stop in
propagate_streaming) only gets a checkpoint between the graph's own
streamed chunks -- a call that never returns means no chunk, so no
checkpoint either. See default_config.py's llm_timeout_seconds comment.
"""

import pytest

from tradingagents.graph.trading_graph import TradingAgentsGraph


@pytest.mark.unit
def test_llm_timeout_is_forwarded_to_provider_kwargs():
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {"llm_provider": "deepseek", "llm_timeout_seconds": 30}

    kwargs = TradingAgentsGraph._get_provider_kwargs(graph)

    assert kwargs["timeout"] == 30.0


@pytest.mark.unit
def test_llm_timeout_applies_even_to_openrouter():
    # openrouter carves itself out of the shared temperature/top_p keys
    # (it has its own openrouter_temperature/_top_p) -- timeout must not
    # be caught by that same exclusion, since it isn't provider-specific.
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {"llm_provider": "openrouter", "llm_timeout_seconds": 30}

    kwargs = TradingAgentsGraph._get_provider_kwargs(graph)

    assert kwargs["timeout"] == 30.0


@pytest.mark.unit
def test_llm_timeout_disabled_when_none():
    """Setting it to None restores the provider's own (unbounded) default."""
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {"llm_provider": "deepseek", "llm_timeout_seconds": None}

    assert "timeout" not in TradingAgentsGraph._get_provider_kwargs(graph)
