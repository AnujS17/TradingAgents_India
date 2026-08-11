"""Debate/risk nodes: news_synthesis over news_report, and the static/dynamic
prompt-cache split.

Verifies two things for each of the 5 nodes (bull, bear, aggressive, neutral,
conservative):

1. They read state["news_synthesis"] (compact) instead of state["news_report"]
   (the full raw-blocks-plus-analysis version, which used to be re-embedded
   into every one of these nodes on every debate round).
2. invoke_with_cache_breakpoint is called with a static/dynamic split where
   the reports (and, for risk debators, the trader's decision) land in the
   STATIC half — the half Anthropic actually caches — and only debate
   history / opponents' latest arguments land in the dynamic half.
"""

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.risk_mgmt.aggressive_debator import create_aggressive_debator
from tradingagents.agents.risk_mgmt.neutral_debator import create_neutral_debator
from tradingagents.agents.risk_mgmt.conservative_debator import create_conservative_debator


class FakeResponse:
    def __init__(self, content="argument text"):
        self.content = content


def _investment_state(**overrides):
    base = {
        "company_of_interest": "ORCL",
        "asset_type": "stock",
        "instrument_context": "The instrument to analyze is `ORCL`.",
        "market_report": "MARKET_MARKER",
        "sentiment_report": "SENTIMENT_MARKER",
        "news_report": "FULL_NEWS_REPORT_MARKER_should_not_appear",
        "news_synthesis": "COMPACT_NEWS_SYNTHESIS_MARKER",
        "fundamentals_report": "FUNDAMENTALS_MARKER",
        "investment_debate_state": {
            "history": "HISTORY_MARKER",
            "bull_history": "",
            "bear_history": "",
            "current_response": "OPPONENT_ARGUMENT_MARKER",
            "count": 0,
        },
    }
    base.update(overrides)
    return base


def _risk_state(**overrides):
    base = {
        "company_of_interest": "ORCL",
        "asset_type": "stock",
        "instrument_context": "The instrument to analyze is `ORCL`.",
        "market_report": "MARKET_MARKER",
        "sentiment_report": "SENTIMENT_MARKER",
        "news_report": "FULL_NEWS_REPORT_MARKER_should_not_appear",
        "news_synthesis": "COMPACT_NEWS_SYNTHESIS_MARKER",
        "fundamentals_report": "FUNDAMENTALS_MARKER",
        "trader_investment_plan": "TRADER_DECISION_MARKER",
        "risk_debate_state": {
            "history": "HISTORY_MARKER",
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "latest_speaker": "",
            "current_aggressive_response": "OPPONENT_A_MARKER",
            "current_conservative_response": "OPPONENT_C_MARKER",
            "current_neutral_response": "OPPONENT_N_MARKER",
            "count": 0,
        },
    }
    base.update(overrides)
    return base


INVESTMENT_NODES = [
    ("bull_researcher", create_bull_researcher, _investment_state),
    ("bear_researcher", create_bear_researcher, _investment_state),
]

RISK_NODES = [
    ("aggressive_debator", create_aggressive_debator, _risk_state),
    ("neutral_debator", create_neutral_debator, _risk_state),
    ("conservative_debator", create_conservative_debator, _risk_state),
]

MODULE_PATHS = {
    "bull_researcher": "tradingagents.agents.researchers.bull_researcher",
    "bear_researcher": "tradingagents.agents.researchers.bear_researcher",
    "aggressive_debator": "tradingagents.agents.risk_mgmt.aggressive_debator",
    "neutral_debator": "tradingagents.agents.risk_mgmt.neutral_debator",
    "conservative_debator": "tradingagents.agents.risk_mgmt.conservative_debator",
}


@pytest.mark.unit
@pytest.mark.parametrize("name,factory,state_fn", INVESTMENT_NODES + RISK_NODES)
def test_reads_news_synthesis_not_news_report(name, factory, state_fn, monkeypatch):
    captured = {}

    def fake_breakpoint(llm, static_context, dynamic_context):
        captured["static"] = static_context
        captured["dynamic"] = dynamic_context
        return FakeResponse()

    monkeypatch.setattr(f"{MODULE_PATHS[name]}.invoke_with_cache_breakpoint", fake_breakpoint)

    factory(MagicMock())(state_fn())

    combined = captured["static"] + captured["dynamic"]
    assert "COMPACT_NEWS_SYNTHESIS_MARKER" in combined
    assert "FULL_NEWS_REPORT_MARKER_should_not_appear" not in combined


@pytest.mark.unit
@pytest.mark.parametrize("name,factory,state_fn", INVESTMENT_NODES + RISK_NODES)
def test_reports_are_in_the_static_block(name, factory, state_fn, monkeypatch):
    captured = {}

    def fake_breakpoint(llm, static_context, dynamic_context):
        captured["static"] = static_context
        captured["dynamic"] = dynamic_context
        return FakeResponse()

    monkeypatch.setattr(f"{MODULE_PATHS[name]}.invoke_with_cache_breakpoint", fake_breakpoint)

    factory(MagicMock())(state_fn())

    for marker in ("MARKET_MARKER", "SENTIMENT_MARKER", "COMPACT_NEWS_SYNTHESIS_MARKER", "FUNDAMENTALS_MARKER"):
        assert marker in captured["static"], f"{marker} missing from static_context for {name}"
        assert marker not in captured["dynamic"], f"{marker} leaked into dynamic_context for {name}"


@pytest.mark.unit
@pytest.mark.parametrize("name,factory,state_fn", INVESTMENT_NODES)
def test_debate_history_and_opponent_argument_are_in_the_dynamic_block(name, factory, state_fn, monkeypatch):
    captured = {}

    def fake_breakpoint(llm, static_context, dynamic_context):
        captured["static"] = static_context
        captured["dynamic"] = dynamic_context
        return FakeResponse()

    monkeypatch.setattr(f"{MODULE_PATHS[name]}.invoke_with_cache_breakpoint", fake_breakpoint)

    factory(MagicMock())(state_fn())

    assert "HISTORY_MARKER" in captured["dynamic"]
    assert "OPPONENT_ARGUMENT_MARKER" in captured["dynamic"]
    assert "HISTORY_MARKER" not in captured["static"]


@pytest.mark.unit
@pytest.mark.parametrize("name,factory,state_fn", RISK_NODES)
def test_trader_decision_is_in_the_static_block_for_risk_debators(name, factory, state_fn, monkeypatch):
    # The trader runs once before the risk debate starts, so its decision is
    # identical across every round of the 3-way debate — it belongs in the
    # cached static block alongside the 4 reports, not resent fresh each round.
    captured = {}

    def fake_breakpoint(llm, static_context, dynamic_context):
        captured["static"] = static_context
        captured["dynamic"] = dynamic_context
        return FakeResponse()

    monkeypatch.setattr(f"{MODULE_PATHS[name]}.invoke_with_cache_breakpoint", fake_breakpoint)

    factory(MagicMock())(state_fn())

    assert "TRADER_DECISION_MARKER" in captured["static"]
    assert "TRADER_DECISION_MARKER" not in captured["dynamic"]


# Each risk debator reads the OTHER TWO analysts' latest responses, never
# its own (that's an output this node produces, not an input it reads) — the
# aggressive node's prompt never references current_aggressive_response.
OPPONENT_MARKERS_READ = {
    "aggressive_debator": ("OPPONENT_C_MARKER", "OPPONENT_N_MARKER"),
    "neutral_debator": ("OPPONENT_A_MARKER", "OPPONENT_C_MARKER"),
    "conservative_debator": ("OPPONENT_A_MARKER", "OPPONENT_N_MARKER"),
}


@pytest.mark.unit
@pytest.mark.parametrize("name,factory,state_fn", RISK_NODES)
def test_opponent_responses_are_in_the_dynamic_block_for_risk_debators(name, factory, state_fn, monkeypatch):
    captured = {}

    def fake_breakpoint(llm, static_context, dynamic_context):
        captured["static"] = static_context
        captured["dynamic"] = dynamic_context
        return FakeResponse()

    monkeypatch.setattr(f"{MODULE_PATHS[name]}.invoke_with_cache_breakpoint", fake_breakpoint)

    factory(MagicMock())(state_fn())

    for marker in OPPONENT_MARKERS_READ[name]:
        assert marker in captured["dynamic"]
        assert marker not in captured["static"]


@pytest.mark.unit
@pytest.mark.parametrize("name,factory,state_fn", INVESTMENT_NODES + RISK_NODES)
def test_static_plus_dynamic_is_used_via_the_cache_helper(name, factory, state_fn, monkeypatch):
    # Confirms the node actually calls invoke_with_cache_breakpoint (not a
    # bare llm.invoke(prompt)) and forwards its return value as the response.
    calls = []

    def fake_breakpoint(llm, static_context, dynamic_context):
        calls.append((static_context, dynamic_context))
        return FakeResponse(content="RESPONSE_MARKER")

    monkeypatch.setattr(f"{MODULE_PATHS[name]}.invoke_with_cache_breakpoint", fake_breakpoint)

    result = factory(MagicMock())(state_fn())

    assert len(calls) == 1
    debate_key = "investment_debate_state" if "investment_debate_state" in result else "risk_debate_state"
    assert "RESPONSE_MARKER" in str(result[debate_key])
