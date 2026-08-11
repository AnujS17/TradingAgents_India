import pytest

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.llm_clients.model_catalog import get_model_options


@pytest.mark.unit
def test_default_config_uses_poolside_laguna_m1_openrouter():
    assert "openrouter_reasoning_effort" in DEFAULT_CONFIG
    assert "openrouter_max_completion_tokens" in DEFAULT_CONFIG


@pytest.mark.unit
def test_openrouter_kwargs_enable_reasoning_and_large_completion_budget():
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {
        **DEFAULT_CONFIG,
        "llm_provider": "openrouter",
        "openrouter_reasoning_effort": "xhigh",
        "openrouter_max_completion_tokens": 8192,
        "openrouter_temperature": 0.2,
        "openrouter_top_p": 0.9,
    }

    kwargs = TradingAgentsGraph._get_provider_kwargs(graph)

    assert kwargs["extra_body"] == {
        "reasoning": {"effort": "xhigh", "exclude": True}
    }
    assert "reasoning" not in kwargs
    assert "reasoning_effort" not in kwargs
    assert kwargs["max_completion_tokens"] == 8192
    assert kwargs["temperature"] == 0.2
    assert kwargs["top_p"] == 0.9


@pytest.mark.unit
def test_openrouter_catalog_surfaces_poolside_laguna_m1():
    quick_ids = [model_id for _, model_id in get_model_options("openrouter", "quick")]
    deep_ids = [model_id for _, model_id in get_model_options("openrouter", "deep")]

    assert quick_ids[0] == "poolside/laguna-m.1:free"
    assert deep_ids[0] == "poolside/laguna-m.1:free"
