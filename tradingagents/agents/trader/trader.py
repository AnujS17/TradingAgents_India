"""Trader: turns the Research Manager's investment plan into a concrete transaction proposal."""

from __future__ import annotations

import functools

import pandas as pd
from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import (
    CONCISE_TRADER_OVERRIDES,
    TraderProposal,
    concise_variant,
    render_trader_proposal,
)
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_india_market_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.dataflows.config import get_config


def _sessions_missed(as_of: str, trade_date: str) -> int:
    """Trading sessions strictly between the anchor bar and the analysis date.

    Weekday counting, not calendar days: a Friday close read on the
    following Monday is 3 calendar days old but misses NOTHING, while
    ITC.NS's 08-31 (Mon) close read on 09-02 (Wed) is 2 calendar days old
    and misses a full session -- the one in which the stock rose 4.3%.
    Calendar arithmetic cannot tell those apart; weekday arithmetic can.

    Exchange holidays are not modelled, so a holiday inside the span reads
    as a missed session. That direction is deliberate: a spurious "may be
    stale" warning costs a sentence of prompt and some caution, while a
    missed staleness warning costs an unfillable recommendation.

    Returns 0 on any parse failure -- an anchor that cannot be dated falls
    back to the previous unconditional behaviour rather than crying stale.
    """
    try:
        start = pd.Timestamp(as_of).normalize()
        end = pd.Timestamp(trade_date).normalize()
    except Exception:  # noqa: BLE001 - undateable anchor is not a stale anchor
        return 0
    if pd.isna(start) or pd.isna(end) or end <= start:
        return 0
    # Strictly between: the anchor's own bar is not missed, and the analysis
    # date itself may not have traded yet when the run starts.
    return max(0, len(pd.bdate_range(start, end)) - 2)


def _price_anchor(ticker: str, trade_date: str | None) -> str:
    """A one-line last-traded-price block for the Trader's prompt, or "".

    The Trader is asked for a concrete entry and stop, but until now it was
    handed only the Research Manager's plan and an instrument context that
    contains no price whatsoever (agent_utils.build_instrument_context:
    ticker, company, sector, exchange). When the plan's actions are
    qualitative -- SKYGOLD.NS 2026-08-31: "trim into any strength,
    targeting the recent momentum highs", "if it breaks below its recent
    consolidation range" -- there is no number anywhere in the Trader's
    input, and the schema still REQUIRES entry_price for a Buy or Sell. It
    filled the gap with entry 5000 / stop 4200 on a stock whose 52-week
    high is 848. KAYNES.NS 2026-08-30 failed the same way at entry 2600
    against a 3943 close.

    Deliberately just the anchor, not a second technical read: the Market
    Analyst's verified snapshot stays the single source of truth for
    indicators, and this quotes the SAME load_ohlcv row that snapshot and
    api.service._extract_current_price both read, so the three cannot
    disagree. Snapshot- and file-cached by the time the Trader runs, so
    this is a cache hit rather than a fresh fetch.

    Never raises, and never requires anything to be present: no anchor is
    exactly the status quo, so neither a data hiccup nor a bare
    programmatic state (tests, direct node calls -- the same case
    get_instrument_context_from_state documents) may fail the run.
    """
    if not ticker or not trade_date:
        return ""
    try:
        from tradingagents.dataflows.stockstats_utils import load_ohlcv

        data = load_ohlcv(ticker, trade_date)
        if data.empty:
            return ""
        latest = data.iloc[-1]
        close = float(latest["Close"])
        as_of = str(latest.get("Date", ""))[:10]
    except Exception:  # noqa: BLE001 - anchor is an aid, never a dependency
        return ""

    missed = _sessions_missed(as_of, trade_date)

    if missed:
        # A stale anchor must not be binding. ITC.NS 2026-09-02: the anchor
        # quoted the 08-31 close of 255.50 while the stock had closed at
        # 266.60 on 09-01 (+4.3%), and the "must transact at THIS price"
        # instruction below did exactly what it says -- the Trader proposed
        # an entry at 255.50 that was never fillable at any point afterwards.
        # The BASELINE system, which had no anchor at all, read the same
        # stale snapshot and still produced reachable levels (270, into the
        # analysts' 268-272 supply shelf) precisely because nothing forced
        # it onto the stale print.
        #
        # So the anchor is only ever as good as its bar. When it is behind,
        # it degrades to a floor-level sanity check (it still stops the
        # SKYGOLD "entry 5000 against a 848 high" class of fabrication) and
        # hands primacy back to the analysts' cited levels.
        session_word = "session has" if missed == 1 else "sessions have"
        return (
            f"\n\nMost recent price on file for {ticker}: {close:,.2f} "
            f"(close of {as_of}).\n**This is STALE: at least {missed} trading "
            f"{session_word} passed between that close and the "
            f"{trade_date} analysis date, so the live price is NOT this "
            "number and may differ materially.** Treat it only as an "
            "order-of-magnitude sanity check -- a proposed level ten times "
            "or one tenth of it is certainly wrong. Do NOT anchor your entry "
            "or stop to it. Prefer the specific levels the analysts cite "
            "(support/resistance shelves, moving averages, stated "
            "accumulation or distribution zones), and if the news or "
            "sentiment reports describe a price move after "
            f"{as_of}, weight that over this figure. State in your reasoning "
            "that the reference price is stale."
        )

    return (
        f"\n\nLast traded price for {ticker}: {close:,.2f} "
        f"(close of {as_of}).\nAny entry or stop you propose must be a level "
        "that makes sense against THIS price -- a level you would actually "
        "transact at. If the plan above describes levels only in words "
        "(\"recent highs\", \"the consolidation range\"), convert them into "
        "numbers anchored to this price and the analysts' cited levels "
        "rather than inventing a figure. This is the last traded price "
        "only; the market report remains the source of truth for indicator "
        "values."
    )


def create_trader(llm):
    # Schema descriptions are the real output instructions for structured
    # agents — see schemas.concise_variant.
    _schema = (
        concise_variant(TraderProposal, CONCISE_TRADER_OVERRIDES)
        if get_config().get("report_style", "detailed") == "concise"
        else TraderProposal
    )
    structured_llm = bind_structured(llm, _schema, "Trader")

    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = get_instrument_context_from_state(state)
        investment_plan = state["investment_plan"]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a trading agent analyzing market data to make investment decisions. "
                    "Based on your analysis, provide a specific recommendation to buy, sell, or hold. "
                    "Anchor your reasoning in the analysts' reports and the research plan."
                    + get_india_market_instruction("trader")
                    + get_language_instruction()
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Based on a comprehensive analysis by a team of analysts, here is an investment "
                    f"plan tailored for {company_name}. {instrument_context} This plan incorporates "
                    f"insights from current technical market trends, macroeconomic indicators, and "
                    f"social media sentiment. Use this plan as a foundation for evaluating your next "
                    f"trading decision.\n\nProposed Investment Plan: {investment_plan}"
                    f"{_price_anchor(company_name, state.get('trade_date'))}\n\n"
                    f"Leverage these insights to make an informed and strategic decision."
                ),
            },
        ]

        trader_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            messages,
            render_trader_proposal,
            "Trader",
        )

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
