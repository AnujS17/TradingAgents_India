from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_stock_data,
    get_india_market_instruction,
    get_verified_market_snapshot,
    is_length_limited,
    keeps_markdown_tables,
    scale_word_budget,
)
from tradingagents.dataflows.config import get_config


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        instrument_context = get_instrument_context_from_state(state)
        verified_snapshot = get_verified_market_snapshot.func(ticker, current_date, 30)

        # get_verified_market_snapshot is deliberately NOT in this tool list —
        # it's already pre-fetched above and injected into the prompt below.
        # It used to be both pre-fetched AND LLM-callable, which let the LLM
        # redundantly re-invoke it with the same args, producing confusing
        # duplicate [Tool Call]/[Data] log entries for no new information
        # (observed live on the RELIANCE run, 2026-08-10).
        #
        # get_indicators is ALSO deliberately not here anymore, for the same
        # "already have it, don't re-fetch it" reason — but this one needed a
        # data-side fix first, not just removal. get_indicators returns
        # day-by-day history (e.g. RSI for each of the last 30 days); the
        # snapshot used to give only a single latest value per indicator, so
        # removing the tool would have silently discarded trend visibility
        # (is RSI rising toward overbought, did MACD just cross its signal
        # line). market_data_validator.build_verified_market_snapshot now
        # includes an "Indicator Trend" section (rsi/macd/macds/macdh, last
        # 10 sessions) specifically to cover that before this removal.
        tools = [
            get_stock_data,
        ]

        # "concise" (fast platform profile) requests a shorter write-up —
        # see default_config.get_fast_config for why. The evidence/citation
        # discipline two paragraphs below is unconditional either way.
        concise = is_length_limited()
        # An explicit word count, not the word "concise" — models reliably
        # ignore the latter. Measured: the detailed prompt produced ~2,100
        # words of market commentary, which at typical generation speed is
        # over a minute of wall-clock for this one call alone.
        depth_instruction = (
            f"HARD LIMIT: {scale_word_budget(250)} words maximum, EXCLUDING the "
            "Support & Resistance block required below. Lead with the trend "
            "verdict, then only the indicator readings that justify it. No "
            "preamble, no restating the snapshot back, no per-indicator "
            "walkthrough."
            if concise
            else "Write a very detailed and nuanced report of the trends you observe."
        )
        # Structural, not prose -- and therefore NOT subject to the word
        # budget above. ITC.NS 2026-09-02: under "balanced" the market report
        # came in at 647 words against a 625 cap and contained the word
        # "support" exactly ZERO times, while the same ticker under
        # "detailed" produced a full S/R section stating "no measured support
        # below 255.50 in 13 months". That sentence was the only place in the
        # entire system that contradicted a ~253-255 "multi-year support"
        # claim which had come from a retail StockTwits post -- and with the
        # section gone, the claim went unchallenged into the debate and
        # became the load-bearing pillar of a Buy-the-dip verdict.
        #
        # The failure was not that the model judged S/R unimportant; it was
        # that "only the evidence that justifies your verdict" plus a hard
        # cap makes price STRUCTURE lose to indicator READINGS every time.
        # Exempting it from the cap is what makes the trade-off explicit
        # rather than silent.
        levels_instruction = """

REQUIRED — **Support & Resistance** (a separate block, and it does NOT count against any word limit above):
- List the specific price levels that matter, each with the concrete evidence for it (a dated high/low from the recent-closes table, a moving average, a band edge). No level without evidence.
- State explicitly how far back the data you were given actually goes, and say so in the form "over the N sessions provided". Never describe a level as "multi-year", "long-term" or "historical" support unless the snapshot itself covers that span -- it does not.
- If there is NO measured support below the current price within the data provided, say that in exactly those terms. That absence is a finding, not a gap to skip: it means downside is price discovery.
- If another report cites a support or resistance level you cannot corroborate from this snapshot, say so plainly rather than repeating it."""
        # Markdown tables are disproportionately token-expensive (row
        # scaffolding, padding, repeated headers) for the information they
        # add over prose at this length.
        table_instruction = (
            "" if concise
            else """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
        )

        system_message = (
            f"""You are a trading assistant tasked with analyzing financial markets. Every indicator below is already computed and included in the verified market snapshot — do not call a tool to re-fetch any of them. Select the **most relevant indicators** from what's provided for a given market condition or trading strategy, choosing up to **8** that provide complementary insights without redundancy. Categories and each category's indicators are:

Moving Averages:
- close_50_sma: 50 SMA: A medium-term trend indicator. Usage: Identify trend direction and serve as dynamic support/resistance. Tips: It lags price; combine with faster indicators for timely signals.
- close_200_sma: 200 SMA: A long-term trend benchmark. Usage: Confirm overall market trend and identify golden/death cross setups. Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries.
- close_10_ema: 10 EMA: A responsive short-term average. Usage: Capture quick shifts in momentum and potential entry points. Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals.

MACD Related:
- macd: MACD: Computes momentum via differences of EMAs. Usage: Look for crossovers and divergence as signals of trend changes. Tips: Confirm with other indicators in low-volatility or sideways markets.
- macds: MACD Signal: An EMA smoothing of the MACD line. Usage: Use crossovers with the MACD line to trigger trades. Tips: Should be part of a broader strategy to avoid false positives.
- macdh: MACD Histogram: Shows the gap between the MACD line and its signal. Usage: Visualize momentum strength and spot divergence early. Tips: Can be volatile; complement with additional filters in fast-moving markets.

Momentum Indicators:
- rsi: RSI: Measures momentum to flag overbought/oversold conditions. Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis.

Volatility Indicators:
- boll: Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. Usage: Acts as a dynamic benchmark for price movement. Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals.
- boll_ub: Bollinger Upper Band: Typically 2 standard deviations above the middle line. Usage: Signals potential overbought conditions and breakout zones. Tips: Confirm signals with other tools; prices may ride the band in strong trends.
- boll_lb: Bollinger Lower Band: Typically 2 standard deviations below the middle line. Usage: Indicates potential oversold conditions. Tips: Use additional analysis to avoid false reversal signals.
- atr: ATR: Averages true range to measure volatility. Usage: Set stop-loss levels and adjust position sizes based on current market volatility. Tips: It's a reactive measure, so use it as part of a broader risk management strategy.

Volume-Based Indicators:
- vwma: VWMA: A moving average weighted by volume. Usage: Confirm trends by integrating price action with volume data. Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses.

- Select indicators that provide diverse and complementary information. Avoid redundancy (e.g., do not select both rsi and stochrsi). Also briefly explain why they are suitable for the given market context.

The verified market snapshot below has already been fetched before you were invoked, including an Indicator Trend section (RSI, MACD, MACD Signal, MACD Histogram) showing the last 10 sessions so you can read momentum direction and crossovers, not just a single current value. Treat the snapshot as the source of truth for any exact OHLCV, price-level, or indicator-value claim. Call get_stock_data only if you need raw daily OHLCV beyond the snapshot's own recent-closes table (e.g. a longer or differently-positioned date range) — never to re-derive an indicator value already shown above. If a get_stock_data result conflicts with the verified snapshot, flag the discrepancy rather than inventing a reconciled number. Do not claim historical validation, support/resistance bounces, or exact percentage moves unless they are directly supported by tool output with concrete dates and prices.

<verified_market_snapshot>
{verified_snapshot}
</verified_market_snapshot>

{depth_instruction}{levels_instruction}

Provide specific, actionable insights with supporting evidence to help traders make informed decisions."""
            + get_india_market_instruction("market")
            + table_instruction
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)

        result = chain.invoke(state["market_messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = (
                "## Verified Market Snapshot Used\n\n"
                f"{verified_snapshot}\n\n"
                "## Market Analyst Report\n\n"
                f"{result.content}"
            )

        update = {
            "market_messages": [result],
            "market_report": report,
        }

        # This node re-runs on every ReAct tool-call round-trip (LangGraph
        # re-invokes the whole function each turn), but the snapshot is only
        # freshly presented once. Gate the audit entry to the first turn —
        # detected by the absence of this node's own prior tool responses —
        # so it isn't re-logged into message_tool.log on every subsequent turn.
        already_ran = any(
            getattr(m, "name", None) == "get_stock_data"
            for m in state["market_messages"]
        )
        if not already_ran:
            update["audit_tool_calls"] = [
                {
                    "name": "get_verified_market_snapshot",
                    "args": {
                        "symbol": ticker,
                        "curr_date": current_date,
                        "look_back_days": 30,
                    },
                    "result": verified_snapshot,
                }
            ]

        return update

    return market_analyst_node
