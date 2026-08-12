"""Sentiment analyst — multi-source sentiment analysis for a target ticker.

Previously named ``social_media_analyst``. Renamed and redesigned because
the old version had a prompt that demanded social-media analysis but the
only tool available was Yahoo Finance news — which led LLMs to fabricate
Reddit/X/StockTwits content under prompt pressure (verified live).

The redesigned agent pre-fetches four complementary data sources before
the LLM is invoked and injects them into the prompt as structured blocks:

  1. News headlines     — Yahoo Finance (institutional framing)
  2. StockTwits messages — retail-trader posts indexed by cashtag, with
                           user-labeled Bullish/Bearish sentiment tags
  3. Reddit posts        — India-market subreddits (see
                           tradingagents.dataflows.reddit.DEFAULT_SUBREDDITS)
  4. India-market RSS news — supplemental promoter-action/regulatory/
                           sector context (tradingagents.dataflows.india_news)

The agent does not use tool-calling; the data is in the prompt from
turn 0. Output uses the structured-output pattern (json_schema for
OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic), falling
back to free-text generation for providers that lack native support, so
the sentiment header (band + score + confidence) is deterministic across
runs and providers instead of free-form per-model prose.

See: https://github.com/TauricResearch/TradingAgents/issues/557
See: https://github.com/TauricResearch/TradingAgents/issues/796
"""

from datetime import datetime, timedelta

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.schemas import (
    CONCISE_SENTIMENT_OVERRIDES,
    SentimentReport,
    concise_variant,
    render_sentiment_report,
)
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_news,
    get_india_market_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.reddit import DEFAULT_SUBREDDITS, fetch_reddit_posts
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages
from tradingagents.dataflows.india_news import fetch_ticker_india_news


def _article_count(news_block: str) -> int:
    """Count of '### ' article headings in a formatted news block, for the pointer note."""
    return sum(1 for line in news_block.splitlines() if line.startswith("### "))


def _news_window_start(trade_date: str) -> str:
    """Start of the company-news window, matching news_analyst's lookback.

    Shares ``company_news_lookback_days`` with news_analyst so both agents
    reason over the same window; a 7-day window left this agent with no news
    at all for sparsely-covered Indian mid-caps. Note the social sources
    (StockTwits, Reddit) have their own recency semantics and are unaffected.
    """
    lookback_days = get_config().get("company_news_lookback_days", 30)
    return (
        datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=lookback_days)
    ).strftime("%Y-%m-%d")


def create_sentiment_analyst(llm):
    """Create a sentiment analyst node for the trading graph.

    Pre-fetches news + StockTwits + Reddit data, injects them into the
    prompt as structured blocks, and produces a deterministic sentiment
    report via structured output (with a free-text fallback for providers
    that do not support it).
    """
    # The schema's field descriptions are what langchain actually sends to
    # the provider as output instructions, so a concise PROMPT alone left
    # this agent writing the full 5-section report the schema still asked
    # for. Bind the concise schema variant instead when report_style says so.
    _schema = (
        concise_variant(SentimentReport, CONCISE_SENTIMENT_OVERRIDES)
        if get_config().get("report_style", "detailed") == "concise"
        else SentimentReport
    )
    structured_llm = bind_structured(llm, _schema, "Sentiment Analyst")

    def sentiment_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]
        start_date = _news_window_start(end_date)
        instrument_context = get_instrument_context_from_state(state)
        config = get_config()

        # Pre-fetch all four sources. Each fetcher degrades gracefully and
        # returns a string (no exceptions surface from here), so the LLM
        # always sees something — either real data or a clear placeholder.
        news_block = get_news.func(ticker, start_date, end_date)
        stocktwits_block = fetch_stocktwits_messages(ticker, limit=30)
        # None (the default) means "use every subreddit"; the fast profile
        # narrows this to the top 3 by subscriber count (see
        # default_config.get_fast_config) to cut Reddit's worst-case fetch
        # time — subreddit count is the direct multiplier, since every miss
        # still queries every configured subreddit.
        reddit_subreddits = tuple(config.get("reddit_subreddits") or DEFAULT_SUBREDDITS)
        reddit_block = fetch_reddit_posts(ticker, subreddits=reddit_subreddits)
        india_news_block = fetch_ticker_india_news(ticker)

        system_message = _build_system_message(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            stocktwits_block=stocktwits_block,
            reddit_block=reddit_block,
            india_news_block=india_news_block,
            reddit_subreddits=reddit_subreddits,
            report_style=config.get("report_style", "detailed"),
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    "\n{system_message}\n"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        # Format the template into a concrete message list so the structured
        # and free-text paths receive the same input. No bind_tools — the
        # data is already in the prompt.
        formatted_messages = prompt.format_messages(messages=state["sentiment_messages"])

        analysis_text = invoke_structured_or_freetext(
            structured_llm,
            llm,
            formatted_messages,
            render_sentiment_report,
            "Sentiment Analyst",
        )
        report_text = (
            "## Pre-Fetched Sentiment Sources Used\n\n"
            "### News Block\n\n"
            # The full news_block IS still in the prompt above (the LLM read
            # it in full to write analysis_text) and IS still in
            # audit_tool_calls below (for hallucination-tracing) — only this
            # disk/state-facing copy is trimmed. news_analyst fetches the
            # identical ticker + window (both use company_news_lookback_days
            # via get_news), so re-embedding the same ~30 articles here just
            # duplicates them into sentiment_report, which state["sentiment_report"]
            # resends whole into 5 separate debate/risk LLM calls downstream.
            f"_Full company news is in the News Analyst report (fetched independently, "
            f"same {start_date} to {end_date} window) — omitted here to avoid duplicating "
            f"the same ~{_article_count(news_block)} articles across graph state._\n\n"
            "### StockTwits Block\n\n"
            f"{stocktwits_block}\n\n"
            "### Reddit Block\n\n"
            f"{reddit_block}\n\n"
            "### India News Block\n\n"
            f"{india_news_block}\n\n"
            "## Sentiment Analyst Report\n\n"
            f"{analysis_text}"
        )

        return {
            # Only the synthesized analysis goes into the shared message
            # thread — the raw pre-fetched blocks (already embedded in
            # `report_text` below) would otherwise get resent as context
            # to every downstream analyst that reads state["messages"]
            # (fundamentals_analyst), inflating tokens on every one of
            # its ReAct turns. The full report still reaches the saved
            # report via sentiment_report.
            "sentiment_messages": [AIMessage(content=analysis_text)],
            "sentiment_report": report_text,
            "audit_tool_calls": [
                {
                    "name": "get_news",
                    "args": {
                        "ticker": ticker,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                    "result": news_block,
                },
                {
                    "name": "fetch_stocktwits_messages",
                    "args": {
                        "symbol": ticker,
                        "limit": 30,
                    },
                    "result": stocktwits_block,
                },
                {
                    "name": "fetch_reddit_posts",
                    "args": {
                        "ticker": ticker,
                    },
                    "result": reddit_block,
                },
                {
                    "name": "fetch_ticker_india_news",
                    "args": {
                        "ticker": ticker,
                    },
                    "result": india_news_block,
                },
            ],
        }

    return sentiment_analyst_node


def _build_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
    india_news_block: str,
    reddit_subreddits: tuple[str, ...],
    report_style: str = "detailed",
) -> str:
    """Assemble the sentiment-analyst system message with structured data blocks."""
    reddit_source_line = ", ".join(f"r/{s}" for s in reddit_subreddits)
    # Built from the actual subreddit set, not hardcoded: with a narrowed
    # list (fast profile) a static description would claim character notes
    # about subreddits (r/NSEbets, r/DalalStreetTalks, ...) that were never
    # queried in this run — a source-description error, not just verbosity.
    _character_notes = {
        "IndianStreetBets": "r/IndianStreetBets often contrarian/exuberant",
        "NSEbets": "r/NSEbets often contrarian/exuberant",
        "IndiaInvestments": "r/IndiaInvestments more measured/longer-term",
        "IndianStockMarket": "r/IndianStockMarket general NSE/BSE discussion",
        "StockMarketIndia": "r/StockMarketIndia general NSE/BSE discussion",
    }
    reddit_character_line = "; ".join(
        _character_notes[s] for s in reddit_subreddits if s in _character_notes
    )
    concise = report_style == "concise"
    task_line = (
        "Your task is to produce a concise sentiment report"
        if concise
        else "Your task is to produce a comprehensive sentiment report"
    )
    narrative_field = (
        "**narrative**: A concise source-by-source read (2-4 sentences per source that actually has data), "
        "any real cross-source divergence, and a short markdown summary table (direction, source, supporting "
        "evidence). Skip extended catalyst/risk elaboration — keep it tight; this is a fast-platform run, not "
        "a research report."
        if concise
        else "**narrative**: Full source-by-source breakdown, divergences, dominant narrative themes, catalysts "
        "and risks, and a markdown summary table of key sentiment signals (direction, source, supporting evidence)."
    )
    return f"""You are a financial market sentiment analyst. {task_line} for {ticker} covering the period from {start_date} to {end_date}, drawing on four complementary data sources that have already been collected for you.

## Data sources (pre-fetched, in this prompt)

### News headlines — Yahoo Finance, {start_date} to {end_date}
Institutional framing. Fact-driven, slower-moving signal. This window is wider than the social sources below because Indian mid- and small-caps are covered sparsely; each article is dated, so weight recent items more heavily and note explicitly when you are leaning on an older story.

<start_of_news>
{news_block}
<end_of_news>

### StockTwits messages — retail-trader social platform indexed by cashtag
Fast-moving signal. Each message carries a user-labeled sentiment tag (Bullish / Bearish / no-label) plus the message body.

<start_of_stocktwits>
{stocktwits_block}
<end_of_stocktwits>

### Reddit posts — India-market subreddits (past 7 days)
Community discussion across {reddit_source_line}. Engagement signal via upvote score and comment count.{" Subreddit character matters: " + reddit_character_line + "." if reddit_character_line else ""}

<start_of_reddit>
{reddit_block}
<end_of_reddit>

### Supplemental India-market news — RSS (promoter-action/regulatory/sector signals)
No-key context from Indian business and markets outlets that often surfaces promoter-action, regulatory, and sector signals before they are fully reflected in finance-only feeds.

<start_of_india_news>
{india_news_block}
<end_of_india_news>

## How to analyze this data (best practices)

1. **Read the StockTwits Bullish/Bearish ratio as a leading retail-sentiment signal.** A 70/30 bullish/bearish split is moderately bullish; ≥90/10 may indicate over-extension and contrarian risk; 50/50 is uncertainty. Sample size matters — base rates on the actual message count, not percentages alone.

2. **Look for cross-source divergences.** If news framing is bearish but StockTwits is overwhelmingly bullish, that mismatch is itself a signal — it can mean retail is leaning into a thesis the news flow hasn't caught up to (or vice versa, that retail is chasing while institutions are cautious).

3. **Weight Reddit posts by engagement.** A 400-upvote / 200-comment thread reflects community attention; a 3-upvote post is noise. Read the body excerpts for context — the title alone often misleads.

4. **Distinguish opinion from event.** A news headline ("Nvidia announces $500M Corning deal") is an event; a StockTwits post ("buying NVDA, this is going to moon") is opinion. Both are inputs but should be weighted differently in your conclusions.

5. **Identify recurring narrative themes.** What topic keeps coming up across sources? That's the dominant narrative driving current sentiment.

6. **Be honest about data limits.** If StockTwits returned only a handful of messages, or one or more sources returned an "<unavailable>" placeholder, the sentiment read is less robust — flag this explicitly in the `confidence` field and the narrative. If the sources are silent on a given subreddit, say so.

7. **Identify catalysts and risks** that emerge across sources — news of upcoming earnings, product launches, competitive threats, macro headlines, etc.

8. **Past sentiment is not predictive.** Frame your conclusions as signal for the trader to weigh alongside fundamentals and technicals, not as a price call.

## Output fields

Fill the following fields:

- **overall_band**: Exactly one of Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish. Use Mixed when sources point in clearly different directions; Neutral only when all sources are genuinely silent.
- **overall_score**: A number from 0 (maximally bearish) to 10 (maximally bullish); 5 is neutral. Keep it consistent with overall_band.
- **confidence**: low / medium / high, based on data quality and sample size.
- {narrative_field}

Scope discipline: do not state that technical analysis, fundamentals, or market data are unavailable or available. Those are handled by other analysts. This report is limited to the pre-fetched sentiment/news/social sources above.
{get_india_market_instruction("sentiment")}
{get_language_instruction()}"""


# ---------------------------------------------------------------------------
# Backwards-compatibility shim
# ---------------------------------------------------------------------------
def create_social_media_analyst(llm):
    """Deprecated alias for :func:`create_sentiment_analyst`.

    Kept so existing code that imports ``create_social_media_analyst``
    continues to work.

    .. deprecated::
        Import :func:`create_sentiment_analyst` directly instead.
    """
    import warnings
    warnings.warn(
        "create_social_media_analyst is deprecated and will be removed in a "
        "future version. Use create_sentiment_analyst instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_sentiment_analyst(llm)
