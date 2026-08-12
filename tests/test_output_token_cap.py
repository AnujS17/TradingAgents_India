"""max_output_tokens — the only deterministic lever on run wall-clock time.

Run time is dominated by output-token GENERATION, not input size: a measured
default run produced ~8,400 words (~11k tokens) of analyst prose before the
8 debate/manager calls even start, and at typical provider speeds that alone
accounts for most of a 10-minute run. Before this, no provider except
openrouter had any output cap at all, so "be concise" in a prompt was the
only thing limiting length — and models routinely ignore it.

These tests pin the wiring end to end: config -> _get_provider_kwargs ->
client passthrough -> the actual model object. A break anywhere in that chain
is silent (the kwarg is just dropped) and would reproduce the original
"the flag exists but changes nothing" bug.
"""

import os

import pytest

from tradingagents.default_config import DEFAULT_CONFIG, get_fast_config
from tradingagents.graph.trading_graph import TradingAgentsGraph


def _provider_kwargs(config: dict) -> dict:
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = config
    return graph._get_provider_kwargs()


@pytest.mark.unit
def test_default_config_sets_no_cap():
    # Unchanged behaviour for anyone not opting into fast mode.
    assert DEFAULT_CONFIG["max_output_tokens"] is None
    assert "max_tokens" not in _provider_kwargs(dict(DEFAULT_CONFIG))


def _capped_config():
    """A config with an explicit cap, for exercising the per-provider mapping.

    These tests used to read the value off get_fast_config(). The fast profile
    no longer sets it, but the mapping itself still has to work for anyone who
    does set it deliberately.
    """
    return {**DEFAULT_CONFIG, "max_output_tokens": 1400}


@pytest.mark.unit
def test_fast_config_no_longer_caps_output():
    """The cap was removed from the fast profile on 2026-08-12.

    Output length is reasoning depth for an LLM, so capping it made fast runs
    reason less, not merely write less — see the note in default_config.py and
    the SIEMENS.NS demerger case.
    """
    assert get_fast_config()["max_output_tokens"] is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "provider", ["deepseek", "openai", "xai", "qwen", "glm", "minimax", "ollama"]
)
def test_openai_compatible_providers_get_max_tokens(provider):
    config = {**_capped_config(), "llm_provider": provider}

    assert _provider_kwargs(config)["max_tokens"] == 1400


@pytest.mark.unit
def test_anthropic_gets_max_tokens():
    config = {**_capped_config(), "llm_provider": "anthropic"}

    assert _provider_kwargs(config)["max_tokens"] == 1400


@pytest.mark.unit
def test_google_gets_its_own_parameter_name():
    # Gemini's SDK spells this max_output_tokens, not max_tokens — passing
    # the wrong name would be silently ignored rather than erroring.
    config = {**_capped_config(), "llm_provider": "google"}
    kwargs = _provider_kwargs(config)

    assert kwargs["max_output_tokens"] == 1400
    assert "max_tokens" not in kwargs


@pytest.mark.unit
def test_openrouter_is_excluded_to_avoid_two_competing_caps():
    # openrouter already has openrouter_max_completion_tokens; setting both
    # would be ambiguous about which one the provider honours.
    config = {**_capped_config(), "llm_provider": "openrouter"}
    kwargs = _provider_kwargs(config)

    assert "max_tokens" not in kwargs
    assert kwargs["max_completion_tokens"] == DEFAULT_CONFIG["openrouter_max_completion_tokens"]


@pytest.mark.unit
def test_cap_actually_reaches_the_deepseek_model_object(monkeypatch):
    # The end of the chain: openai_client's _PASSTHROUGH_KWARGS must include
    # max_tokens or it is dropped between the client and langchain, and the
    # cap would silently do nothing on the DEFAULT provider.
    from tradingagents.llm_clients.openai_client import OpenAIClient

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    llm = OpenAIClient(
        "deepseek-v4-flash", provider="deepseek", max_tokens=1400, api_key="test-key"
    ).get_llm()

    assert llm.max_tokens == 1400
