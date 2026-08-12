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
        lambda ticker, subreddits=None: "reddit block",
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


def _stub_fundamentals(monkeypatch, calls=None):
    def record(name, freq=None):
        if calls is not None:
            calls.append((name, freq))

    monkeypatch.setattr(
        "tradingagents.agents.analysts.fundamentals_analyst.fetch_promoter_bulk_deals",
        lambda ticker, curr_date: (
            record("fetch_promoter_bulk_deals"),
            "## NSE Bulk-Deal Activity for ORCL\n- BUY: SOME FUND — qty 100000 @ avg price 50.00",
        )[1],
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.fundamentals_analyst.get_fundamentals.func",
        lambda ticker, curr_date: (record("get_fundamentals"), "overview block")[1],
    )
    for tool in ("get_income_statement", "get_balance_sheet", "get_cashflow"):
        monkeypatch.setattr(
            f"tradingagents.agents.analysts.fundamentals_analyst.{tool}.func",
            lambda ticker, freq, curr_date, _t=tool: (
                record(_t, freq),
                f"{_t} {freq} block",
            )[1],
        )


def test_fundamentals_prefetches_every_statement_in_both_frequencies(monkeypatch):
    """The whole point of the pre-fetch: no statement/frequency can be skipped.

    Regression for the defect measured on SIEMENS.NS 2026-08-12. The statement
    tools default to freq="quarterly"; as a ReAct agent this analyst never
    passed the argument, so it fetched quarterly only and never saw an annual
    statement — losing the multi-year growth, margin and free-cash-flow series
    the detailed run used. Same cause as HDFCBANK.NS's "No cash-flow statement
    data available" (that vendor has no quarterly cash flow; annual was fine).
    """
    calls = []
    _stub_fundamentals(monkeypatch, calls)

    result = create_fundamentals_analyst(PlainLLM())(_state())

    assert set(calls) == {
        ("fetch_promoter_bulk_deals", None),
        ("get_fundamentals", None),
        ("get_income_statement", "annual"),
        ("get_income_statement", "quarterly"),
        ("get_balance_sheet", "annual"),
        ("get_balance_sheet", "quarterly"),
        ("get_cashflow", "annual"),
        ("get_cashflow", "quarterly"),
    }
    assert len(calls) == 8, "each block must be fetched exactly once"

    # Every block reaches the model, and every block is auditable.
    assert [call["name"] for call in result["audit_tool_calls"]] == [
        "fetch_promoter_bulk_deals",
        "get_fundamentals",
        "get_income_statement",
        "get_income_statement",
        "get_balance_sheet",
        "get_balance_sheet",
        "get_cashflow",
        "get_cashflow",
    ]
    assert {
        call["args"].get("freq")
        for call in result["audit_tool_calls"]
        if call["name"] == "get_cashflow"
    } == {"annual", "quarterly"}


def test_fundamentals_report_carries_raw_blocks_but_synthesis_does_not(monkeypatch):
    """Same split as news_report/news_synthesis, and for the same reason.

    The report keeps the raw blocks for the human record and hallucination
    audits; the synthesis is what the 5 debate/risk nodes read, so six
    statement blocks are not re-embedded into every one of their prompts.
    """
    _stub_fundamentals(monkeypatch)

    result = create_fundamentals_analyst(PlainLLM())(_state())

    for marker in (
        "get_cashflow annual block",
        "get_cashflow quarterly block",
        "get_income_statement annual block",
        "get_balance_sheet annual block",
        "overview block",
    ):
        assert marker in result["fundamentals_report"]

    assert result["fundamentals_synthesis"] == "grounded report"
    assert "get_cashflow annual block" not in result["fundamentals_synthesis"]
    assert result["fundamentals_messages"][0].content == "grounded report"


def test_fundamentals_degrades_when_a_block_fails(monkeypatch):
    """A dead vendor endpoint must not abort the run — and the model must be
    told the block is missing rather than silently reasoning without it."""
    _stub_fundamentals(monkeypatch)

    def boom(ticker, freq, curr_date):
        raise RuntimeError("vendor 503")

    monkeypatch.setattr(
        "tradingagents.agents.analysts.fundamentals_analyst.get_cashflow.func", boom
    )

    result = create_fundamentals_analyst(PlainLLM())(_state())

    assert "get_cashflow(annual) unavailable: vendor 503" in result["fundamentals_report"]
    assert "get_cashflow(quarterly) unavailable: vendor 503" in result["fundamentals_report"]
    # The other seven still made it through.
    assert "overview block" in result["fundamentals_report"]
