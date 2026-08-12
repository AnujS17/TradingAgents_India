"""report_style ("detailed" vs "concise") threading through the 4 analyst prompts.

"concise" is what the fast/platform profile (default_config.get_fast_config)
requests — a shorter write-up asked of the model means less generation
wall-time. The default ("detailed") must reproduce the exact prior prompt
text unchanged, and the evidence/citation guardrails in every prompt must be
present in BOTH modes — trimming verbosity must never trim accuracy discipline.
"""

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from tradingagents.agents.analysts.fundamentals_analyst import create_fundamentals_analyst
from tradingagents.agents.analysts.market_analyst import create_market_analyst
from tradingagents.agents.analysts.news_analyst import create_news_analyst
from tradingagents.agents.analysts.sentiment_analyst import create_sentiment_analyst
from tradingagents.dataflows.config import get_config, set_config
from tradingagents.default_config import DEFAULT_CONFIG


@pytest.fixture(autouse=True)
def reset_config():
    set_config(dict(DEFAULT_CONFIG))
    yield
    set_config(dict(DEFAULT_CONFIG))


class CapturingToolLLM:
    """bind_tools()-style LLM that records the system prompt text it was given."""

    def __init__(self):
        self.captured_system_message = None

    def bind_tools(self, tools):
        def _invoke(prompt_value):
            # `prompt | llm.bind_tools(tools)` feeds this a ChatPromptValue
            # (the pipe's output), not a plain message list — .to_messages()
            # is required to get at the formatted system message.
            messages = prompt_value.to_messages()
            self.captured_system_message = messages[0].content
            return AIMessage(content="report")

        return RunnableLambda(_invoke)


class CapturingPlainLLM:
    def __init__(self):
        self.captured_prompt = None
        # Same text under the name the bind_tools-style stub uses, so tests
        # asserting on the system prompt read the same way for every analyst.
        self.captured_system_message = None

    def invoke(self, messages):
        self.captured_prompt = messages[0].content if isinstance(messages, list) else messages
        self.captured_system_message = self.captured_prompt
        return AIMessage(content="report")


def _stub_fundamentals_prefetches(monkeypatch):
    """Keep the fundamentals analyst offline.

    It now pre-fetches 8 blocks (bulk deals, the overview, and all three
    statements in BOTH frequencies) instead of leaving them to a ReAct loop,
    so an unstubbed call would make 8 real network requests per test.
    """
    monkeypatch.setattr(
        "tradingagents.agents.analysts.fundamentals_analyst.fetch_promoter_bulk_deals",
        lambda ticker, curr_date: "bulk deal block",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.fundamentals_analyst.get_fundamentals.func",
        lambda ticker, curr_date: "fundamentals overview",
    )
    for tool in ("get_income_statement", "get_balance_sheet", "get_cashflow"):
        monkeypatch.setattr(
            f"tradingagents.agents.analysts.fundamentals_analyst.{tool}.func",
            lambda ticker, freq, curr_date, _t=tool: f"{_t} {freq} block",
        )


def _state():
    return {
        "messages": [("human", "ORCL")],
        # Each analyst reads its OWN channel now (parallel execution);
        # seeding only "messages" leaves them empty -> KeyError.
        "market_messages": [("human", "ORCL")],
        "sentiment_messages": [("human", "ORCL")],
        "news_messages": [("human", "ORCL")],
        "fundamentals_messages": [("human", "ORCL")],
        "company_of_interest": "ORCL",
        "trade_date": "2026-06-03",
        "asset_type": "stock",
        "instrument_context": "The instrument to analyze is `ORCL`.",
    }


# --- market_analyst ---------------------------------------------------


@pytest.mark.unit
def test_market_analyst_detailed_is_unchanged_default():
    llm = CapturingToolLLM()
    create_market_analyst(llm)(_state())

    assert "Write a very detailed and nuanced report of the trends you observe." in llm.captured_system_message


@pytest.mark.unit
def test_market_analyst_concise_requests_shorter_writeup():
    set_config({**DEFAULT_CONFIG, "report_style": "concise"})
    llm = CapturingToolLLM()
    create_market_analyst(llm)(_state())

    # An explicit numeric limit, not the word "concise" — models reliably
    # ignore soft wording, and a measured detailed run produced ~2,100 words
    # from this agent.
    assert "HARD LIMIT: 250 words maximum" in llm.captured_system_message
    assert "very detailed and nuanced" not in llm.captured_system_message
    # Markdown tables are token-expensive for what they add at this length.
    assert "append a Markdown table" not in llm.captured_system_message


@pytest.mark.unit
@pytest.mark.parametrize("style", ["detailed", "concise"])
def test_market_analyst_evidence_guardrails_present_in_both_styles(style):
    set_config({**DEFAULT_CONFIG, "report_style": style})
    llm = CapturingToolLLM()
    create_market_analyst(llm)(_state())

    text = llm.captured_system_message
    assert "Treat the snapshot as the source of truth" in text
    assert "flag the discrepancy rather than inventing" in text
    assert "Provide specific, actionable insights with supporting evidence" in text


# --- fundamentals_analyst ----------------------------------------------


@pytest.mark.unit
def test_fundamentals_analyst_detailed_is_unchanged_default(monkeypatch):
    _stub_fundamentals_prefetches(monkeypatch)
    llm = CapturingPlainLLM()
    create_fundamentals_analyst(llm)(_state())

    assert "Make sure to include as much detail as possible" in llm.captured_system_message


@pytest.mark.unit
def test_fundamentals_analyst_concise_requests_shorter_writeup(monkeypatch):
    _stub_fundamentals_prefetches(monkeypatch)
    set_config({**DEFAULT_CONFIG, "report_style": "concise"})
    llm = CapturingPlainLLM()
    create_fundamentals_analyst(llm)(_state())

    assert "HARD LIMIT: 250 words maximum" in llm.captured_system_message
    assert "as much detail as possible" not in llm.captured_system_message
    assert "append a Markdown table" not in llm.captured_system_message


@pytest.mark.unit
@pytest.mark.parametrize("style", ["detailed", "concise"])
def test_fundamentals_analyst_evidence_phrase_present_in_both_styles(style, monkeypatch):
    # Pinned by test_evidence_guardrails.py too; re-asserted here since this
    # file is what actually exercises the report_style branch.
    _stub_fundamentals_prefetches(monkeypatch)
    set_config({**DEFAULT_CONFIG, "report_style": style})
    llm = CapturingPlainLLM()
    create_fundamentals_analyst(llm)(_state())

    assert "Provide specific, actionable insights with supporting evidence" in llm.captured_system_message
    # Both obligations added with the pre-fetch must survive in BOTH styles —
    # they are accuracy discipline, not verbosity (see module docstring).
    assert "a single quarter is not a trend" in llm.captured_system_message
    assert "State what a forward multiple assumes" in llm.captured_system_message
    assert "cannot be reconciled" in llm.captured_system_message


# --- news_analyst --------------------------------------------------------


def _news_state_with_stubs(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.get_news.func",
        lambda ticker, start_date, end_date: "company news",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.get_global_news.func",
        lambda curr_date: "global news",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_global_india_news",
        lambda: "india news",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_corporate_announcements",
        lambda ticker, curr_date: "filings",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_stocktwits_messages",
        lambda ticker, limit=30: "social wire",
    )
    return _state()


@pytest.mark.unit
def test_news_analyst_detailed_asks_for_full_bullish_bearish_coverage(monkeypatch):
    llm = CapturingPlainLLM()
    create_news_analyst(llm)(_news_state_with_stubs(monkeypatch))

    text = llm.captured_prompt
    assert "A brief narrative (3-6 sentences)" in text
    assert "up to 3 bullets" not in text


@pytest.mark.unit
def test_news_analyst_concise_caps_bullish_bearish_and_shortens_narrative(monkeypatch):
    set_config({**DEFAULT_CONFIG, "report_style": "concise"})
    llm = CapturingPlainLLM()
    create_news_analyst(llm)(_news_state_with_stubs(monkeypatch))

    text = llm.captured_prompt
    assert "A brief narrative (2-3 sentences)" in text
    assert "up to 3 bullets" in text
    assert "HARD LIMIT: 300 words maximum" in text
    assert "8 bullets MAXIMUM" in text
    assert "append a Markdown table" not in text


@pytest.mark.unit
@pytest.mark.parametrize("style", ["detailed", "concise"])
def test_news_analyst_grounding_guardrails_present_in_both_styles(style, monkeypatch):
    set_config({**DEFAULT_CONFIG, "report_style": style})
    llm = CapturingPlainLLM()
    create_news_analyst(llm)(_news_state_with_stubs(monkeypatch))

    text = llm.captured_prompt
    assert "Pre-fetched news data is provided below" in text
    assert "ground your report only in it" in text
    assert "Do not call or imply additional news tools were used" in text
    assert "<prefetched_company_news>" in text


# --- sentiment_analyst -----------------------------------------------


def _sentiment_state_with_stubs(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.get_news.func",
        lambda ticker, start_date, end_date: "news block",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.fetch_stocktwits_messages",
        lambda ticker, limit=30: "stocktwits block",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.fetch_reddit_posts",
        lambda ticker, subreddits=None: "reddit block",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.fetch_ticker_india_news",
        lambda ticker: "india news block",
    )
    return _state()


class FreeTextSentimentLLM:
    def __init__(self):
        self.captured_prompt = None

    def with_structured_output(self, schema):
        raise AttributeError("no structured output in this fake")

    def invoke(self, messages):
        self.captured_prompt = messages[0].content
        return AIMessage(content="Neutral, low confidence.")


@pytest.mark.unit
def test_sentiment_analyst_detailed_asks_for_full_narrative(monkeypatch):
    llm = FreeTextSentimentLLM()
    create_sentiment_analyst(llm)(_sentiment_state_with_stubs(monkeypatch))

    assert "Full source-by-source breakdown" in llm.captured_prompt


@pytest.mark.unit
def test_sentiment_analyst_concise_shortens_narrative_request(monkeypatch):
    set_config({**DEFAULT_CONFIG, "report_style": "concise"})
    llm = FreeTextSentimentLLM()
    create_sentiment_analyst(llm)(_sentiment_state_with_stubs(monkeypatch))

    text = llm.captured_prompt
    assert "Full source-by-source breakdown" not in text
    assert "concise source-by-source read" in text


@pytest.mark.unit
@pytest.mark.parametrize("style", ["detailed", "concise"])
def test_sentiment_analyst_data_quality_guardrails_present_in_both_styles(style, monkeypatch):
    set_config({**DEFAULT_CONFIG, "report_style": style})
    llm = FreeTextSentimentLLM()
    create_sentiment_analyst(llm)(_sentiment_state_with_stubs(monkeypatch))

    text = llm.captured_prompt
    assert "base rates on the actual message count" in text
    assert "Be honest about data limits" in text


@pytest.mark.unit
def test_sentiment_analyst_reddit_source_line_reflects_narrowed_subreddits(monkeypatch):
    set_config({**DEFAULT_CONFIG, "reddit_subreddits": ["IndianStockMarket", "IndiaInvestments"]})
    captured = {}

    def fake_fetch(ticker, subreddits=None):
        captured["subreddits"] = subreddits
        return "reddit block"

    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.get_news.func",
        lambda ticker, start_date, end_date: "news",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.fetch_stocktwits_messages",
        lambda ticker, limit=30: "stocktwits",
    )
    monkeypatch.setattr("tradingagents.agents.analysts.sentiment_analyst.fetch_reddit_posts", fake_fetch)
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.fetch_ticker_india_news",
        lambda ticker: "india news",
    )

    llm = FreeTextSentimentLLM()
    create_sentiment_analyst(llm)(_state())

    assert captured["subreddits"] == ("IndianStockMarket", "IndiaInvestments")
    assert "r/IndianStockMarket" in llm.captured_prompt
    assert "r/IndianStreetBets" not in llm.captured_prompt  # narrowed out, must not still be claimed


@pytest.mark.unit
def test_sentiment_analyst_defaults_to_all_seven_subreddits_when_unset(monkeypatch):
    from tradingagents.dataflows.reddit import DEFAULT_SUBREDDITS

    captured = {}

    def fake_fetch(ticker, subreddits=None):
        captured["subreddits"] = subreddits
        return "reddit block"

    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.get_news.func",
        lambda ticker, start_date, end_date: "news",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.fetch_stocktwits_messages",
        lambda ticker, limit=30: "stocktwits",
    )
    monkeypatch.setattr("tradingagents.agents.analysts.sentiment_analyst.fetch_reddit_posts", fake_fetch)
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.fetch_ticker_india_news",
        lambda ticker: "india news",
    )

    llm = FreeTextSentimentLLM()
    create_sentiment_analyst(llm)(_state())

    assert captured["subreddits"] == DEFAULT_SUBREDDITS


# --- "balanced" (the fast profile) ----------------------------------------
#
# SIEMENS.NS 2026-08-12: the concise profile did not merely shorten the news
# write-up, it changed the conclusion. Its "8 bullets MAXIMUM" cap evicted the
# 07-Apr-2025 Demerger filing in favour of a fresher headline, and "No markdown
# table" removed where the detailed run tagged rows "(separate entity)". With
# the disqualifying fact gone the run credited a demerged sister company's +70%
# profit to this ticker as a bullish point. "balanced" restores exactly those
# two structural allowances, plus a 2.5x word budget.


@pytest.mark.unit
def test_balanced_keeps_tables_and_concise_does_not():
    from tradingagents.agents.utils.agent_utils import keeps_markdown_tables

    for style, expected in (("detailed", True), ("balanced", True), ("concise", False)):
        set_config({**DEFAULT_CONFIG, "report_style": style})
        assert keeps_markdown_tables() is expected, style


@pytest.mark.unit
def test_balanced_scales_word_budgets_above_concise():
    from tradingagents.agents.utils.agent_utils import scale_word_budget

    set_config({**DEFAULT_CONFIG, "report_style": "concise"})
    tight = scale_word_budget(250)
    set_config({**DEFAULT_CONFIG, "report_style": "balanced"})
    roomy = scale_word_budget(250)

    assert roomy > tight
    assert tight == 250


@pytest.mark.unit
def test_balanced_news_raises_the_coverage_bullet_cap(monkeypatch):
    """The 8-bullet cap is the specific mechanism that dropped the filing."""
    set_config({**DEFAULT_CONFIG, "report_style": "balanced"})
    llm = CapturingPlainLLM()
    create_news_analyst(llm)(_news_state_with_stubs(monkeypatch))

    text = llm.captured_system_message
    assert "20 bullets MAXIMUM" in text
    assert "8 bullets MAXIMUM" not in text


@pytest.mark.unit
def test_balanced_news_requires_an_entity_column(monkeypatch):
    """The table is where per-item entity attribution actually lives."""
    set_config({**DEFAULT_CONFIG, "report_style": "balanced"})
    llm = CapturingPlainLLM()
    create_news_analyst(llm)(_news_state_with_stubs(monkeypatch))

    text = llm.captured_system_message
    assert "identifying WHICH listed entity each item belongs to" in text
    assert "No markdown table." not in text


@pytest.mark.unit
@pytest.mark.parametrize("style", ["concise", "balanced"])
def test_corporate_action_filings_are_never_droppable(style, monkeypatch):
    """Unconditional in every length-limited style — a demerger filing is what
    makes the other figures comparable, and it is the first thing cut because
    it is not 'news'."""
    set_config({**DEFAULT_CONFIG, "report_style": style})
    llm = CapturingPlainLLM()
    create_news_analyst(llm)(_news_state_with_stubs(monkeypatch))

    text = llm.captured_system_message
    assert "Never drop an exchange filing that records a corporate action" in text
    assert "demerger, spin-off, merger" in text


@pytest.mark.unit
def test_fast_profile_uses_balanced_not_concise():
    from tradingagents.default_config import get_fast_config

    assert get_fast_config()["report_style"] == "balanced"
