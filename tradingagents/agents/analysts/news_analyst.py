from datetime import datetime, timedelta

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_global_news,
    get_language_instruction,
    get_news,
    get_india_market_instruction,
)
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.india_news import fetch_global_india_news
from tradingagents.dataflows.nse_announcements import fetch_corporate_announcements
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        config = get_config()
        lookback_days = config.get("company_news_lookback_days", 30)
        start_date = (
            datetime.strptime(current_date, "%Y-%m-%d") - timedelta(days=lookback_days)
        ).strftime("%Y-%m-%d")
        asset_type = state.get("asset_type", "stock")
        asset_label = "company" if asset_type == "stock" else "asset"
        instrument_context = get_instrument_context_from_state(state)
        company_news_block = get_news.func(ticker, start_date, current_date)
        global_news_block = get_global_news.func(current_date)
        india_global_news_block = fetch_global_india_news()
        filings_block = fetch_corporate_announcements(ticker, current_date)
        # StockTwits is normally the sentiment analyst's source, but for Indian
        # equities its stream is heavily populated by news-wire accounts and it
        # repeatedly carried material company news the wire feeds missed
        # entirely (TMPV.NS 2026-08-10: JLR margin-guidance cut, July PV sales
        # +59% YoY, Sanand plant flooding — none of which reached this agent).
        # It is included as a lead source, explicitly marked unverified below,
        # not as established fact.
        social_wire_block = (
            # Limit defaults to 30 to match the sentiment analyst's request.
            # fetch_stocktwits_messages is lru_cached on (ticker, limit,
            # timeout), so a different limit here is a cache miss and costs a
            # second real network call for a subset of the same data — two
            # fetches were observed on the BLUEJET run. Matching the limit
            # makes the second call a cache hit.
            fetch_stocktwits_messages(ticker, limit=config.get("news_stocktwits_limit", 30))
            if config.get("news_include_stocktwits", True)
            else ""
        )

        # Kept out of the f-string above so the whole section disappears when
        # StockTwits is disabled or unavailable, rather than leaving an empty
        # tag the model may try to explain.
        social_wire_section = ""
        if social_wire_block and not social_wire_block.startswith("<"):
            social_wire_section = f"""
Retail social posts follow. For Indian tickers this stream carries a lot of news-wire reposting and often breaks company news days before it reaches the wire feeds above — but it is UNVERIFIED user-generated content. Treat any claim here as a lead, not a fact: report it only if you attribute it to social chatter and flag that it is uncorroborated, and never let it override an exchange filing or a dated article above. Do not compute sentiment from it; that is another analyst's job.

<prefetched_social_wire>
{social_wire_block}
</prefetched_social_wire>
"""

        system_message = (
            f"""You are a news researcher tasked with analyzing recent news and trends. Pre-fetched news data is provided below; ground your report only in it. Do not call or imply additional news tools were used. Provide specific, actionable insights with supporting evidence to help traders make informed decisions.

Company news below covers {start_date} to {current_date}; the global and India-market blocks cover roughly the past week. Company coverage is deliberately wider because Indian mid- and small-caps are reported on sparsely. Every article is dated — weight recent items more heavily, and say explicitly how old a story is when you lean on it, rather than implying an older item is breaking news.

Your entire output is reused downstream in place of these raw source blocks — 5 separate debate/risk-analysis agents read only your synthesis, not the pre-fetched blocks above, so it must be self-sufficient: every material fact from the sources needs to survive into your output, but as dense structured points rather than re-quoted prose. Write it in exactly this shape:

1. A brief narrative (3-6 sentences): the overall picture and what it means for the trade.
2. **### Coverage** — one bullet per material item, format `- [source, date]: <highlight>`. Give full coverage to every company-specific item (company news, exchange filings, social-wire leads) since those are the ones downstream agents cannot get anywhere else. For the global/macro and India-market blocks, merge near-duplicate headlines on the same story into one bullet rather than repeating each near-identical wire update — Indian financial press tends to file 5-10 near-identical Hormuz/oil/index-level updates from the same day, and each needs to survive as one synthesized point, not five.
3. **### Bullish Points** — the items that argue for the stock.
4. **### Bearish Points** — the items that argue against it.

Do not omit a company-specific fact to save space; compress macro noise instead.

<prefetched_company_news>
{company_news_block}
</prefetched_company_news>

<prefetched_global_news>
{global_news_block}
</prefetched_global_news>

<prefetched_india_market_news>
{india_global_news_block}
</prefetched_india_market_news>

The block below is filed by the company with the exchange, so it is the authoritative record of scheduled events. Where a filing date conflicts with a date mentioned in a news article or social post, the filing wins — say so explicitly rather than averaging the two.

<prefetched_exchange_filings>
{filings_block}
</prefetched_exchange_filings>
{social_wire_section}"""
            + get_india_market_instruction("news")
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the pre-fetched news blocks to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    "\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        result = llm.invoke(prompt.format_messages(messages=state["messages"]))

        report = (
            "## Pre-Fetched Company News Used\n\n"
            f"{company_news_block}\n\n"
            "## Pre-Fetched Global News Used\n\n"
            f"{global_news_block}\n\n"
            "## Pre-Fetched India-Market News Used\n\n"
            f"{india_global_news_block}\n\n"
            "## Pre-Fetched Exchange Filings Used\n\n"
            f"{filings_block}\n\n"
            "## News Analyst Report\n\n"
            f"{result.content}"
        )

        return {
            # Only the synthesized analysis goes into the shared message
            # thread — the raw pre-fetched blocks (already embedded in
            # `report` below) would otherwise get resent as context to
            # every downstream analyst that reads state["messages"]
            # (fundamentals_analyst), inflating tokens on every one of
            # its ReAct turns. The full report (raw blocks + analysis)
            # still reaches the saved report via news_report.
            "messages": [AIMessage(content=result.content)],
            "news_report": report,
            # news_report (above) is the full raw-blocks + analysis version,
            # saved to disk/CLI for the human record — it is what a
            # hallucination audit traces claims back to. news_synthesis is
            # the same analysis text ALONE (the prompt above requires it to
            # be self-sufficient: coverage bullets + bullish/bearish points),
            # for the 5 debate/risk nodes that used to each re-embed the full
            # news_report — ~40KB on a run with rich Google News coverage —
            # into their own prompt every round.
            "news_synthesis": result.content,
            "audit_tool_calls": [
                {
                    "name": "get_news",
                    "args": {
                        "ticker": ticker,
                        "start_date": start_date,
                        "end_date": current_date,
                    },
                    "result": company_news_block,
                },
                {
                    "name": "get_global_news",
                    "args": {
                        "curr_date": current_date,
                    },
                    "result": global_news_block,
                },
                {
                    "name": "fetch_global_india_news",
                    "args": {},
                    "result": india_global_news_block,
                },
                {
                    "name": "fetch_corporate_announcements",
                    "args": {"ticker": ticker, "curr_date": current_date},
                    "result": filings_block,
                },
            ]
            + (
                [
                    {
                        "name": "fetch_stocktwits_messages",
                        "args": {"ticker": ticker, "scope": "news_wire"},
                        "result": social_wire_block,
                    }
                ]
                if social_wire_section
                else []
            ),
        }

    return news_analyst_node
