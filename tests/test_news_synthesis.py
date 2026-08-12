"""news_synthesis field and the sentiment-analyst News Block dedupe.

Both changes attack the same problem: state["news_report"] and the sentiment
analyst's own duplicated news block were being resent, in full, into every
downstream LLM call that read them. news_report on a run with rich Google
News coverage runs ~40KB; the 5 debate/risk nodes (bull, bear, aggressive,
neutral, conservative) each used to re-embed all of it, every round.

news_synthesis is a compact bullets+points version of the same analysis,
built once by news_analyst and read by those 5 nodes instead. The sentiment
analyst's News Block became a pointer note for the same reason: news_analyst
already fetches the identical ticker/window.
"""

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from tradingagents.agents.analysts.news_analyst import create_news_analyst
from tradingagents.agents.analysts.sentiment_analyst import create_sentiment_analyst
from tradingagents.graph.propagation import Propagator


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


class PlainLLM:
    def invoke(self, messages):
        return AIMessage(content="### Coverage\n- [Reuters, 2026-06-01]: strong earnings\n\n### Bullish Points\n- revenue up\n\n### Bearish Points\n- margin pressure")


# --- news_analyst: news_synthesis field --------------------------------


@pytest.mark.unit
def test_news_synthesis_field_is_populated(monkeypatch):
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
        lambda: "india global news",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_corporate_announcements",
        lambda ticker, curr_date: "filings",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_stocktwits_messages",
        lambda ticker, limit=30: "social wire",
    )

    result = create_news_analyst(PlainLLM())(_state())

    assert "news_synthesis" in result
    # news_analyst now writes its own channel (parallel execution), so the
    # synthesis is compared against news_messages, not the shared channel.
    assert result["news_synthesis"] == result["news_messages"][0].content


@pytest.mark.unit
def test_news_synthesis_is_much_smaller_than_full_report(monkeypatch):
    # The whole point: news_synthesis must not carry the raw source blocks.
    big_block = "\n".join(f"### Article {i}\nSome long article body." for i in range(40))
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.get_news.func",
        lambda ticker, start_date, end_date: big_block,
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.get_global_news.func",
        lambda curr_date: big_block,
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_global_india_news",
        lambda: big_block,
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_corporate_announcements",
        lambda ticker, curr_date: big_block,
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_stocktwits_messages",
        lambda ticker, limit=30: big_block,
    )

    result = create_news_analyst(PlainLLM())(_state())

    assert len(result["news_synthesis"]) < len(result["news_report"]) / 5
    assert "Article 0" not in result["news_synthesis"]
    assert "Article 0" in result["news_report"]


@pytest.mark.unit
def test_news_report_still_contains_full_raw_blocks(monkeypatch):
    # news_report (saved to disk/CLI) must be unaffected — it is what a
    # hallucination audit traces claims back to.
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.get_news.func",
        lambda ticker, start_date, end_date: "UNIQUE_COMPANY_MARKER",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.get_global_news.func",
        lambda curr_date: "global news",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_global_india_news",
        lambda: "india global news",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_corporate_announcements",
        lambda ticker, curr_date: "filings",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_stocktwits_messages",
        lambda ticker, limit=30: "social wire",
    )

    result = create_news_analyst(PlainLLM())(_state())

    assert "UNIQUE_COMPANY_MARKER" in result["news_report"]


# --- sentiment_analyst: News Block dedupe --------------------------------


class FreeTextLLM:
    """Forces invoke_structured_or_freetext's fallback path (no structured-output mocking needed)."""

    def with_structured_output(self, schema):
        raise AttributeError("no structured output support in this fake")

    def invoke(self, prompt):
        return AIMessage(content="Neutral sentiment, low confidence.")


@pytest.mark.unit
def test_sentiment_report_news_block_is_a_pointer_not_full_content(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.get_news.func",
        lambda ticker, start_date, end_date: "UNIQUE_NEWS_MARKER article body",
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.stocktwits.fetch_stocktwits_messages",
        lambda ticker, limit=30: "stocktwits block",
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

    result = create_sentiment_analyst(FreeTextLLM())(_state())

    assert "UNIQUE_NEWS_MARKER" not in result["sentiment_report"]
    assert "News Analyst report" in result["sentiment_report"]


@pytest.mark.unit
def test_sentiment_audit_trail_still_has_full_news_content(monkeypatch):
    # Trimming is disk/state-facing only — the audit trail (hallucination
    # tracing) must keep the full result.
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.get_news.func",
        lambda ticker, start_date, end_date: "UNIQUE_NEWS_MARKER article body",
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

    result = create_sentiment_analyst(FreeTextLLM())(_state())

    news_calls = [c for c in result["audit_tool_calls"] if c["name"] == "get_news"]
    assert news_calls
    assert "UNIQUE_NEWS_MARKER" in news_calls[0]["result"]


@pytest.mark.unit
def test_llm_prompt_still_receives_full_news_content(monkeypatch):
    # Only the disk/state-facing copy is trimmed — the LLM's own reasoning
    # must still see the full news block, or the sentiment analysis itself
    # would degrade.
    captured = {}

    class CapturingLLM(FreeTextLLM):
        def invoke(self, prompt):
            captured["prompt"] = prompt
            return AIMessage(content="Neutral sentiment, low confidence.")

    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.get_news.func",
        lambda ticker, start_date, end_date: "UNIQUE_NEWS_MARKER article body",
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

    create_sentiment_analyst(CapturingLLM())(_state())

    system_text = captured["prompt"][0].content
    assert "UNIQUE_NEWS_MARKER" in system_text


# --- state plumbing --------------------------------------------------------


@pytest.mark.unit
def test_initial_state_includes_news_synthesis():
    state = Propagator().create_initial_state("ORCL", "2026-06-03")

    assert state["news_synthesis"] == ""
