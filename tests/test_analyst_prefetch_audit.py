from datetime import datetime, timedelta

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableLambda

from tradingagents.dataflows.config import get_config

from tradingagents.agents.analysts.news_analyst import create_news_analyst
from tradingagents.agents.analysts.market_analyst import create_market_analyst
from tradingagents.agents.analysts.sentiment_analyst import create_sentiment_analyst
from tradingagents.agents.analysts.fundamentals_analyst import create_fundamentals_analyst


class PlainLLM:
    def invoke(self, messages):
        return AIMessage(content="grounded report")


class ToolBindingLLM(PlainLLM):
    def bind_tools(self, tools):
        return RunnableLambda(lambda _: AIMessage(content="grounded report"))


def _state():
    return {
        "messages": [("human", "ORCL")],
        "company_of_interest": "ORCL",
        "trade_date": "2026-06-03",
        "asset_type": "stock",
        "instrument_context": "The instrument to analyze is `ORCL`.",
    }


def test_market_snapshot_prefetch_is_returned_as_audit_tool_call(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.agents.analysts.market_analyst.get_verified_market_snapshot.func",
        lambda symbol, curr_date, look_back_days: (
            "## Verified Market Snapshot for ORCL\n"
            "Latest trading date used: 2026-06-02\n"
            "Close: 244.5800\n"
            "Low: 238.8400"
        ),
    )

    result = create_market_analyst(ToolBindingLLM())(_state())

    assert "Close: 244.5800" in result["market_report"]
    assert result["audit_tool_calls"] == [
        {
            "name": "get_verified_market_snapshot",
            "args": {
                "symbol": "ORCL",
                "curr_date": "2026-06-03",
                "look_back_days": 30,
            },
            "result": (
                "## Verified Market Snapshot for ORCL\n"
                "Latest trading date used: 2026-06-02\n"
                "Close: 244.5800\n"
                "Low: 238.8400"
            ),
        }
    ]


def test_news_prefetches_are_returned_as_audit_tool_calls(monkeypatch):
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
    # Stubbed so this stays offline: both hit live endpoints (NSE, StockTwits).
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_corporate_announcements",
        lambda ticker, curr_date: "## NSE Corporate Filings\n- 13-Aug-2026 — results",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.news_analyst.fetch_stocktwits_messages",
        lambda ticker, limit=20: "social wire block",
    )

    result = create_news_analyst(PlainLLM())(_state())

    assert "company news" in result["news_report"]
    assert [call["name"] for call in result["audit_tool_calls"]] == [
        "get_news",
        "get_global_news",
        "fetch_global_india_news",
        # Exchange filings are authoritative for scheduled events; StockTwits
        # is included as an unverified lead source because for Indian tickers
        # it repeatedly carried company news the wire feeds missed entirely.
        "fetch_corporate_announcements",
        "fetch_stocktwits_messages",
    ]
    # Derived from config rather than hardcoded: the company-news window is
    # deliberately wider than the 7-day global one (Indian mid-caps are covered
    # too sparsely for 7 days to return anything), and this assertion should
    # track that knob instead of pinning a stale literal.
    expected_start = (
        datetime.strptime("2026-06-03", "%Y-%m-%d")
        - timedelta(days=get_config().get("company_news_lookback_days", 30))
    ).strftime("%Y-%m-%d")
    assert result["audit_tool_calls"][0]["args"] == {
        "ticker": "ORCL",
        "start_date": expected_start,
        "end_date": "2026-06-03",
    }
    assert result["audit_tool_calls"][0]["result"] == "company news"
    assert result["audit_tool_calls"][1]["result"] == "global news"
    assert result["audit_tool_calls"][2]["result"] == "india global news"


def test_sentiment_prefetches_are_returned_as_audit_tool_calls(monkeypatch):
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
        lambda ticker: "reddit block",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.fetch_ticker_india_news",
        lambda ticker: "india news block",
    )

    result = create_sentiment_analyst(PlainLLM())(_state())

    assert "stocktwits block" in result["sentiment_report"]
    assert [call["name"] for call in result["audit_tool_calls"]] == [
        "get_news",
        "fetch_stocktwits_messages",
        "fetch_reddit_posts",
        "fetch_ticker_india_news",
    ]
    assert result["audit_tool_calls"][1]["result"] == "stocktwits block"
    assert result["audit_tool_calls"][2]["result"] == "reddit block"
    assert result["audit_tool_calls"][3]["result"] == "india news block"


def test_fundamentals_bulk_deals_prefetch_is_returned_as_audit_tool_call(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.agents.analysts.fundamentals_analyst.fetch_promoter_bulk_deals",
        lambda ticker, curr_date: "## NSE Bulk-Deal Activity for ORCL\n- BUY: SOME FUND — qty 100000 @ avg price 50.00",
    )

    result = create_fundamentals_analyst(ToolBindingLLM())(_state())

    assert result["audit_tool_calls"] == [
        {
            "name": "fetch_promoter_bulk_deals",
            "args": {"ticker": "ORCL", "curr_date": "2026-06-03"},
            "result": "## NSE Bulk-Deal Activity for ORCL\n- BUY: SOME FUND — qty 100000 @ avg price 50.00",
        }
    ]


def test_fundamentals_bulk_deals_audit_entry_not_repeated_across_react_turns(monkeypatch):
    """Regression test: this node re-runs on every ReAct tool-call round-trip
    (same mechanism market_analyst.py had a duplicate-logging bug from earlier
    this session). The audit entry must only appear on the first turn.
    """
    monkeypatch.setattr(
        "tradingagents.agents.analysts.fundamentals_analyst.fetch_promoter_bulk_deals",
        lambda ticker, curr_date: "bulk deal block",
    )

    state = _state()
    result_turn1 = create_fundamentals_analyst(ToolBindingLLM())(state)
    assert len(result_turn1["audit_tool_calls"]) == 1

    state_turn2 = dict(state)
    state_turn2["messages"] = state["messages"] + [
        ToolMessage(content="fundamentals csv", name="get_fundamentals", tool_call_id="1")
    ]
    result_turn2 = create_fundamentals_analyst(ToolBindingLLM())(state_turn2)
    assert "audit_tool_calls" not in result_turn2
