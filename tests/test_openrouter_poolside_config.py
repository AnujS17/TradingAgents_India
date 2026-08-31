import pytest

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import (
    TradingAgentsGraph,
    apply_openrouter_variant,
)
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

    assert kwargs["extra_body"]["reasoning"] == {"effort": "xhigh", "exclude": True}
    assert "reasoning" not in kwargs
    assert "reasoning_effort" not in kwargs
    assert kwargs["max_completion_tokens"] == 8192
    assert kwargs["temperature"] == 0.2
    assert kwargs["top_p"] == 0.9


def _openrouter_graph(**overrides):
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {**DEFAULT_CONFIG, "llm_provider": "openrouter", **overrides}
    return graph


@pytest.mark.unit
def test_openrouter_routing_excludes_the_one_schema_incapable_endpoint():
    """gpt-5.6-luna is served by 7 first-party endpoints, 6 of which
    support structured_outputs. Amazon Bedrock is the sole exception, and a
    host without structured_outputs implements JSON *mode* only -- valid
    JSON with the schema never compiled into a decoding grammar, so nothing
    forbids {"rationale": ""}."""
    kwargs = TradingAgentsGraph._get_provider_kwargs(_openrouter_graph())

    assert kwargs["extra_body"]["provider"] == {"ignore": ["amazon-bedrock"]}


@pytest.mark.unit
def test_open_weight_filters_are_off_for_a_first_party_model():
    """Both filters are FATAL for gpt-5.6-luna and must stay empty while it
    is the configured model (verified live):
      quantizations ["bf16","fp8"] -> 404 "No endpoints found for the
        request with quantization" (all 7 endpoints report "unknown")
      only [deepseek hosts]        -> 404 "No allowed providers are
        available for the selected model"
    They are retained as keys, with the measured DeepSeek values preserved
    in default_config.py's comments, so reverting to an open-weight model
    is a copy-paste rather than a re-measurement."""
    from tradingagents.default_config import DEFAULT_CONFIG as CFG

    assert CFG["deep_think_llm"] == "openai/gpt-5.6-luna"
    assert CFG["quick_think_llm"] == "openai/gpt-5.6-luna"
    assert CFG["openrouter_quantizations"] == []
    assert CFG["openrouter_only_providers"] == []


@pytest.mark.unit
def test_reverting_to_an_open_weight_model_restores_both_filters():
    """The filters are config, not hardcoded to the current model -- a
    revert repopulates them and they flow straight through."""
    kwargs = TradingAgentsGraph._get_provider_kwargs(
        _openrouter_graph(
            deep_think_llm="deepseek/deepseek-v4-flash-0731",
            openrouter_quantizations=["bf16", "fp8"],
            openrouter_only_providers=["deepinfra", "morph"],
            openrouter_ignore_providers=[],
        )
    )

    assert kwargs["extra_body"]["provider"] == {
        "quantizations": ["bf16", "fp8"],
        "only": ["deepinfra", "morph"],
    }


@pytest.mark.unit
def test_require_parameters_is_never_sent():
    """OpenRouter's require_parameters is the *intended* way to demand
    schema enforcement, but it matches against each endpoint's ADVERTISED
    parameters, and langchain unavoidably sends max_completion_tokens
    (ChatOpenAI rewrites max_tokens to it) and parallel_tool_calls
    (with_structured_output's tool-calling path) -- neither of which ANY
    endpoint advertises. Sending it matches zero endpoints and fails every
    call with 404 "No endpoints found that can handle the requested
    parameters", killing whole runs rather than degrading one field.
    Verified by capturing the real request body off the wire."""
    kwargs = TradingAgentsGraph._get_provider_kwargs(_openrouter_graph())

    assert "require_parameters" not in kwargs["extra_body"]["provider"]


@pytest.mark.unit
def test_exacto_is_off_by_default():
    """Measured 2026-08-31: alone it routed to Relace (fp4, no
    response_format at all); with the quantization filter it still
    produced a 3-char strategic_actions and ran ~180s vs ~65s. It is a
    SORT, not a filter -- it reorders candidates without removing bad
    ones, so it cannot close this gap."""
    from tradingagents.default_config import DEFAULT_CONFIG as CFG

    assert CFG["openrouter_exacto"] is False
    assert apply_openrouter_variant(
        CFG["quick_think_llm"], "openrouter", CFG["openrouter_exacto"]
    ) == CFG["quick_think_llm"]


@pytest.mark.unit
def test_provider_routing_survives_an_unset_reasoning_effort():
    """Regression guard: extra_body used to be created inside `if effort:`,
    so clearing the reasoning effort silently dropped the routing block
    with it -- reopening the bug this whole change exists to close."""
    kwargs = TradingAgentsGraph._get_provider_kwargs(
        _openrouter_graph(openrouter_reasoning_effort=None)
    )

    assert "reasoning" not in kwargs["extra_body"]
    assert kwargs["extra_body"]["provider"]["ignore"] == ["amazon-bedrock"]


@pytest.mark.unit
def test_routing_block_is_omitted_entirely_when_every_knob_is_off():
    kwargs = TradingAgentsGraph._get_provider_kwargs(
        _openrouter_graph(
            openrouter_quantizations=[],
            openrouter_only_providers=[],
            openrouter_ignore_providers=[],
        )
    )

    assert "provider" not in kwargs.get("extra_body", {})


@pytest.mark.unit
def test_non_openrouter_providers_get_no_routing_block():
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {**DEFAULT_CONFIG, "llm_provider": "deepseek"}

    kwargs = TradingAgentsGraph._get_provider_kwargs(graph)

    assert "extra_body" not in kwargs


@pytest.mark.unit
@pytest.mark.parametrize(
    "model,provider,exacto,expected",
    [
        # The real default: a bare slug picks up the variant.
        ("deepseek/deepseek-v4-flash-0731", "openrouter", True,
         "deepseek/deepseek-v4-flash-0731:exacto"),
        # Variants do not stack, and the catalog really ships a :free slug --
        # appending would produce "...:free:exacto", which is not a model.
        ("poolside/laguna-m.1:free", "openrouter", True, "poolside/laguna-m.1:free"),
        ("deepseek/deepseek-v4-pro-0813:exacto", "openrouter", True,
         "deepseek/deepseek-v4-pro-0813:exacto"),
        # :exacto is an OpenRouter concept; other providers' slugs are theirs.
        ("deepseek-v4-flash", "deepseek", True, "deepseek-v4-flash"),
        ("deepseek/deepseek-v4-flash-0731", "openrouter", False,
         "deepseek/deepseek-v4-flash-0731"),
        ("", "openrouter", True, ""),
    ],
)
def test_apply_openrouter_variant(model, provider, exacto, expected):
    assert apply_openrouter_variant(model, provider, exacto) == expected


@pytest.mark.unit
def test_quantizations_env_override_parses_a_comma_separated_list():
    """_coerce previously handled bool/int/float/str only, so a list-valued
    setting would have come back as the raw string and been sent to
    OpenRouter as one nonsense quantization level."""
    from tradingagents.default_config import _coerce

    assert _coerce("bf16, fp8 ,", ["bf16", "fp8"]) == ["bf16", "fp8"]
    assert _coerce("bf16", []) == ["bf16"]


@pytest.mark.unit
def test_openrouter_catalog_leads_with_the_configured_default_model():
    """The catalog used to offer only Poolside models, so the CLI could not
    select the model DEFAULT_CONFIG actually runs -- the two contradicted
    each other. Whatever leads these lists should be what a run uses by
    default, or the picker quietly steers users off it."""
    quick_ids = [model_id for _, model_id in get_model_options("openrouter", "quick")]
    deep_ids = [model_id for _, model_id in get_model_options("openrouter", "deep")]

    assert quick_ids[0] == DEFAULT_CONFIG["quick_think_llm"] == "openai/gpt-5.6-luna"
    assert deep_ids[0] == DEFAULT_CONFIG["deep_think_llm"] == "openai/gpt-5.6-luna"
    # The open-weight alternative stays reachable, and Poolside is retained.
    assert "deepseek/deepseek-v4-flash-0731" in quick_ids
    assert "poolside/laguna-m.1:free" in quick_ids


@pytest.mark.unit
def test_checkpointing_is_enabled_so_a_dropped_stream_can_resume():
    """A run is 4-14 minutes; KAYNES lost two consecutive attempts at ~8
    minutes each on 2026-08-31 to a mid-body RemoteProtocolError from the
    provider. That cannot be retried at the HTTP layer -- the response has
    already begun, so the SDK's own retries never engage -- and with
    checkpointing off there was nothing to resume from either, despite
    api/worker.py telling the user they might be able to."""
    assert DEFAULT_CONFIG["checkpoint_enabled"] is True
