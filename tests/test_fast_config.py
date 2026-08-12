"""get_fast_config() — the opt-in fast/platform profile.

A single run through the default pipeline is 10+ minutes, unacceptable for
an interactive platform. get_fast_config() trims the two biggest levers
(debate depth, which is 10 sequential LLM calls by graph structure — no
parallelism is possible there — and report verbosity) plus narrower Reddit
scope and dropping GDELT, while leaving DEFAULT_CONFIG itself completely
untouched so existing behaviour is unaffected unless a caller opts in.
"""

import pytest

from tradingagents.default_config import DEFAULT_CONFIG, get_fast_config
from tradingagents.graph.conditional_logic import ConditionalLogic


@pytest.mark.unit
def test_fast_config_halves_debate_and_risk_rounds():
    fast = get_fast_config()

    assert fast["max_debate_rounds"] == 1
    assert fast["max_risk_discuss_rounds"] == 1
    assert DEFAULT_CONFIG["max_debate_rounds"] == 2
    assert DEFAULT_CONFIG["max_risk_discuss_rounds"] == 2


@pytest.mark.unit
def test_single_round_bull_bear_debate_is_a_full_exchange_not_a_dropped_side():
    # 1 round must still mean Bull argues AND Bear rebuts — not one side
    # skipped entirely, which would silently degrade the debate rather than
    # just shortening it.
    fast = get_fast_config()
    cl = ConditionalLogic(
        max_debate_rounds=fast["max_debate_rounds"],
        max_risk_discuss_rounds=fast["max_risk_discuss_rounds"],
    )
    state = {"investment_debate_state": {"count": 0, "current_response": ""}}

    speakers = []
    for _ in range(6):
        nxt = cl.should_continue_debate(state)
        if nxt == "Research Manager":
            break
        speakers.append(nxt)
        state["investment_debate_state"]["count"] += 1
        state["investment_debate_state"]["current_response"] = nxt.split()[0]

    assert speakers == ["Bull Researcher", "Bear Researcher"]


@pytest.mark.unit
def test_single_round_risk_debate_still_gives_all_three_analysts_a_turn():
    fast = get_fast_config()
    cl = ConditionalLogic(
        max_debate_rounds=fast["max_debate_rounds"],
        max_risk_discuss_rounds=fast["max_risk_discuss_rounds"],
    )
    state = {"risk_debate_state": {"count": 0, "latest_speaker": ""}}

    speakers = []
    for _ in range(8):
        nxt = cl.should_continue_risk_analysis(state)
        if nxt == "Portfolio Manager":
            break
        speakers.append(nxt)
        state["risk_debate_state"]["count"] += 1
        state["risk_debate_state"]["latest_speaker"] = nxt.split()[0]

    assert speakers == ["Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"]


@pytest.mark.unit
def test_fast_config_does_not_reduce_any_fetched_data():
    """The invariant: fast mode changes output length and scheduling, never
    how much data the model sees.

    Article caps, a narrowed reddit_subreddits list and a gdelt-stripped
    vendor chain all used to live in this profile. They were reverted on
    2026-08-12: input size is not what costs wall-clock (output generation
    is), so they bought little speed while making fast and detailed runs
    incomparable on quality. This test is what stops them coming back
    unnoticed.
    """
    fast = get_fast_config()

    for key in (
        "news_article_limit",
        "global_news_article_limit",
        "india_news_article_limit",
        "global_india_news_article_limit",
        "company_news_lookback_days",
        "reddit_subreddits",
        "data_vendors",
        "tool_vendors",
    ):
        assert fast[key] == DEFAULT_CONFIG[key], f"fast mode must not change {key}"

    # gdelt specifically: it is fallback-only, so dropping it is invisible
    # until a primary vendor fails and fast mode silently has no fallback.
    assert "gdelt" in fast["data_vendors"]["news_data"]


@pytest.mark.unit
def test_fast_config_only_changes_output_and_scheduling_keys():
    """Whitelist, so a new input-reducing key cannot be added silently."""
    fast = get_fast_config()
    changed = {k for k in DEFAULT_CONFIG if fast[k] != DEFAULT_CONFIG[k]}

    # report_style and max_output_tokens were removed on 2026-08-12: for an
    # LLM, output length IS reasoning depth, so shortening the write-up made
    # fast runs reason less rather than merely write less. Scheduling is the
    # only lever left.
    assert changed == {
        "max_debate_rounds",
        "max_risk_discuss_rounds",
        "analyst_concurrency_limit",
        "report_style",
    }
    # "balanced", never "concise" — concise is what dropped the demerger
    # filing and miscredited a separately-listed company's profit.
    assert get_fast_config()["report_style"] == "balanced"


@pytest.mark.unit
def test_fast_config_does_not_mutate_default_config():
    # get_fast_config must deep-copy: a shallow copy would let editing
    # fast["data_vendors"] silently corrupt DEFAULT_CONFIG's dict too, since
    # nested dicts are shared references under a shallow copy/spread.
    before = {
        "data_vendors": dict(DEFAULT_CONFIG["data_vendors"]),
        "tool_vendors": dict(DEFAULT_CONFIG["tool_vendors"]),
    }

    get_fast_config()

    assert DEFAULT_CONFIG["data_vendors"] == before["data_vendors"]
    assert DEFAULT_CONFIG["tool_vendors"] == before["tool_vendors"]
    assert DEFAULT_CONFIG["max_debate_rounds"] == 2
    assert DEFAULT_CONFIG["report_style"] == "detailed"


@pytest.mark.unit
def test_fast_config_preserves_sibling_keys_in_nested_dicts():
    # A shallow top-level override ({"data_vendors": {"news_data": ...}})
    # would silently replace the WHOLE data_vendors dict, deleting
    # core_stock_apis/technical_indicators/fundamental_data and breaking
    # price and fundamentals data entirely — a bug with no connection to the
    # actual goal (dropping gdelt from the news chain specifically).
    fast = get_fast_config()

    assert fast["data_vendors"]["core_stock_apis"] == DEFAULT_CONFIG["data_vendors"]["core_stock_apis"]
    assert fast["data_vendors"]["technical_indicators"] == DEFAULT_CONFIG["data_vendors"]["technical_indicators"]
    assert fast["data_vendors"]["fundamental_data"] == DEFAULT_CONFIG["data_vendors"]["fundamental_data"]


@pytest.mark.unit
def test_fast_config_two_calls_are_independent():
    # Each call must return its own deep copy — mutating one result must not
    # leak into a second call or back into DEFAULT_CONFIG.
    first = get_fast_config()
    first["data_vendors"]["news_data"] = "MUTATED"

    second = get_fast_config()

    assert second["data_vendors"]["news_data"] != "MUTATED"
