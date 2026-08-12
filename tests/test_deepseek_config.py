import os

import pytest

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.llm_clients import create_llm_client
from tradingagents.llm_clients.api_key_env import get_api_key_env
from tradingagents.llm_clients.capabilities import get_capabilities
from tradingagents.llm_clients.model_catalog import get_model_options


@pytest.mark.unit
def test_default_config_uses_deepseek_v4_flash():
    assert DEFAULT_CONFIG["llm_provider"] == "deepseek"
    assert DEFAULT_CONFIG["deep_think_llm"] == "deepseek-v4-flash"
    assert DEFAULT_CONFIG["quick_think_llm"] == "deepseek-v4-flash"
    assert get_api_key_env("deepseek") == "DEEPSEEK_API_KEY"


@pytest.mark.unit
def test_deepseek_v4_flash_is_available_for_quick_and_deep():
    quick_ids = [model_id for _, model_id in get_model_options("deepseek", "quick")]
    deep_ids = [model_id for _, model_id in get_model_options("deepseek", "deep")]

    assert quick_ids[0] == "deepseek-v4-flash"
    assert deep_ids[0] == "deepseek-v4-flash"


@pytest.mark.unit
def test_deepseek_v4_flash_suppresses_tool_choice():
    caps = get_capabilities("deepseek-v4-flash")

    assert caps.supports_tool_choice is False
    assert caps.requires_reasoning_content_roundtrip is True


@pytest.mark.unit
def test_deepseek_default_provider_kwargs_are_sampling_only():
    """deepseek must pick up NO provider-specific feature flags.

    It used to get literally nothing. Sampling controls were added for every
    provider on 2026-08-12 (previously only openrouter set temperature, so
    every other provider sampled at its default ~1.0 with no seed and
    identical runs returned opposite verdicts). Those two keys are expected;
    anything beyond them means a provider-specific flag has leaked in.
    """
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = DEFAULT_CONFIG.copy()

    kwargs = TradingAgentsGraph._get_provider_kwargs(graph)

    assert kwargs == {
        "temperature": DEFAULT_CONFIG["llm_temperature"],
        "seed": DEFAULT_CONFIG["llm_seed"],
    }


@pytest.mark.unit
def test_sampling_controls_can_be_disabled():
    """Setting either to None restores the provider's own default."""
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {**DEFAULT_CONFIG, "llm_temperature": None, "llm_seed": None}

    assert TradingAgentsGraph._get_provider_kwargs(graph) == {}


@pytest.mark.unit
def test_deepseek_client_uses_deepseek_base_url(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    llm = create_llm_client(
        provider="deepseek",
        model="deepseek-v4-flash",
    ).get_llm()

    assert str(llm.openai_api_base).rstrip("/") == "https://api.deepseek.com"
