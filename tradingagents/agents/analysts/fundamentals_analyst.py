from concurrent.futures import ThreadPoolExecutor

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    get_language_instruction,
    get_india_market_instruction,
    is_length_limited,
    keeps_markdown_tables,
    scale_word_budget,
)
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.india_insider import fetch_promoter_bulk_deals


# Both reporting frequencies, always. The statement tools default to
# freq="quarterly" (fundamental_data_tools.py), and when this analyst was a
# ReAct agent it simply never passed the argument — so it fetched quarterly
# only and NEVER saw an annual statement. Measured on SIEMENS.NS 2026-08-12:
# the detailed run called each statement twice (once per freq) while the fast
# run called each once with no freq, and consequently lost the FY25 profit
# decline (-13.9%), the multi-year operating-margin slide (~12% -> 9.9% ->
# 8-9%), FY25 free cash flow (~-Rs 57M), the Rs 14.6B working-capital outflow
# and ~128-day receivables. The same defect produced HDFCBANK.NS's "No
# cash-flow statement data available" on 2026-08-11 — that vendor has no
# QUARTERLY cash flow for it, while annual was fine.
#
# Pre-fetching removes the dependence on the model choosing to ask twice.
_STATEMENT_TOOLS = (
    ("get_income_statement", get_income_statement),
    ("get_balance_sheet", get_balance_sheet),
    ("get_cashflow", get_cashflow),
)
_STATEMENT_FREQUENCIES = ("annual", "quarterly")


def _build_prefetch_plan(ticker, current_date):
    """(name, args, thunk) for every block this analyst needs, in report order."""
    plan = [
        (
            "fetch_promoter_bulk_deals",
            {"ticker": ticker, "curr_date": current_date},
            lambda: fetch_promoter_bulk_deals(ticker, current_date),
        ),
        (
            "get_fundamentals",
            {"ticker": ticker, "curr_date": current_date},
            lambda: get_fundamentals.func(ticker, current_date),
        ),
    ]
    for name, tool in _STATEMENT_TOOLS:
        for freq in _STATEMENT_FREQUENCIES:
            plan.append(
                (
                    name,
                    {"ticker": ticker, "freq": freq, "curr_date": current_date},
                    # freq/tool bound per-iteration; a bare closure would
                    # capture the loop variables and fetch the last pair 6x.
                    lambda tool=tool, freq=freq: tool.func(ticker, freq, current_date),
                )
            )
    return plan


def _run_prefetches(plan):
    """Fetch every block concurrently, returning results in plan order.

    These are independent network calls against the same vendor. Serially they
    would add roughly 8x a single round-trip to a node that previously made ~4
    fetches, which would hand back a chunk of the latency win the fast profile
    exists for. Failures are degraded to an inline marker rather than raised:
    a missing cash-flow statement must not abort the whole analysis, and the
    model needs to SEE that a block is missing so it can caveat it instead of
    silently reasoning as though the data were complete.
    """
    with ThreadPoolExecutor(max_workers=len(plan)) as pool:
        futures = [pool.submit(thunk) for _, _, thunk in plan]
        results = []
        for (name, args, _), future in zip(plan, futures):
            try:
                results.append(str(future.result()))
            except Exception as exc:  # noqa: BLE001 - degrade, never abort
                freq = args.get("freq")
                label = f"{name}({freq})" if freq else name
                results.append(f"<{label} unavailable: {exc}>")
    return results


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        ticker = state["company_of_interest"]
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        plan = _build_prefetch_plan(ticker, current_date)
        results = _run_prefetches(plan)
        bulk_deals_block, fundamentals_block = results[0], results[1]
        statement_blocks = dict(
            zip(
                [
                    (name, args["freq"])
                    for name, args, _ in plan[2:]
                ],
                results[2:],
            )
        )

        def block(name, freq):
            return statement_blocks[(name, freq)]

        # "concise" (fast platform profile) requests a shorter write-up —
        # see default_config.get_fast_config for why.
        concise = is_length_limited()
        # Explicit word count — see market_analyst.py. Measured: the detailed
        # prompt produced ~2,560 words here, the longest of the four analysts.
        depth_instruction = (
            f"HARD LIMIT: {scale_word_budget(250)} words maximum. Lead with the fundamental verdict, then only "
            "the figures that drive it (growth, margins, leverage, cash generation, "
            "valuation). No line-by-line statement walkthrough, no restating the raw data."
            if concise
            else "Please write a comprehensive report of the company's fundamental information such as financial documents, company profile, basic company financials, and company financial history to gain a full view of the company's fundamental information to inform traders. Make sure to include as much detail as possible."
        )
        table_instruction = (
            " Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."
            if keeps_markdown_tables()
            else ""
        )

        system_message = (
            "You are a researcher tasked with analyzing fundamental information over the past week about a company. "
            + depth_instruction
            + " Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            + get_india_market_instruction("fundamentals")
            + table_instruction
            # Unconditional in BOTH modes, like the news analyst's grounding
            # sentence and the evidence/citation guardrails: these are accuracy
            # obligations, not verbosity. The concise fast run on HDFCBANK.NS
            # stated vendor ROE (13.84%) and Common Stock Equity (Rs 8.17 lakh
            # crore) as fact where the detailed run found them mutually
            # irreconcilable (~9-10% on an NI/avg-equity basis), and quoted a
            # forward P/E without ever saying what growth it assumed.
            + "\n\nAll the financial data you need is pre-fetched below — annual AND quarterly for each statement. Ground your report only in it and do not call or imply additional tools were used."
            + " Two obligations that apply no matter how short the report is:"
            + " (1) Use the ANNUAL blocks for multi-year trend claims (growth, margin direction, cash generation) and the QUARTERLY blocks for the latest print — a single quarter is not a trend."
            + " (2) State what a forward multiple assumes before leaning on it, and if two vendor figures cannot be reconciled with each other, say so and prefer the one you can derive from the statements."
            + " If a block below is marked unavailable, say so explicitly rather than reasoning as though it were present."
            + "\n\nThe promoter/large-holder bulk-deal activity below has already been fetched for you — treat it as supplemental context on promoter conviction or distribution, not as a full insider-trading disclosure feed, and respect its stated data-freshness caveat rather than treating it as historically precise."
            + f"\n\n<promoter_bulk_deal_activity>\n{bulk_deals_block}\n</promoter_bulk_deal_activity>"
            + f"\n\n<prefetched_fundamentals_overview>\n{fundamentals_block}\n</prefetched_fundamentals_overview>"
            + f"\n\n<prefetched_income_statement_annual>\n{block('get_income_statement', 'annual')}\n</prefetched_income_statement_annual>"
            + f"\n\n<prefetched_income_statement_quarterly>\n{block('get_income_statement', 'quarterly')}\n</prefetched_income_statement_quarterly>"
            + f"\n\n<prefetched_balance_sheet_annual>\n{block('get_balance_sheet', 'annual')}\n</prefetched_balance_sheet_annual>"
            + f"\n\n<prefetched_balance_sheet_quarterly>\n{block('get_balance_sheet', 'quarterly')}\n</prefetched_balance_sheet_quarterly>"
            + f"\n\n<prefetched_cashflow_annual>\n{block('get_cashflow', 'annual')}\n</prefetched_cashflow_annual>"
            + f"\n\n<prefetched_cashflow_quarterly>\n{block('get_cashflow', 'quarterly')}\n</prefetched_cashflow_quarterly>"
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the pre-fetched financial data to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
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

        # No bind_tools: every statement is already in the prompt, so the ReAct
        # loop has nothing left to fetch. Dropping it also removes the
        # round-trips that made this the slowest analyst on the fast profile
        # (54.38s on SIEMENS.NS), and removes the failure mode entirely — the
        # data no longer depends on the model deciding to ask for it.
        result = llm.invoke(prompt.format_messages(messages=state["fundamentals_messages"]))

        report = (
            "## Pre-Fetched Promoter Bulk-Deal Activity Used\n\n"
            f"{bulk_deals_block}\n\n"
            "## Pre-Fetched Fundamentals Overview Used\n\n"
            f"{fundamentals_block}\n\n"
            "## Pre-Fetched Income Statement (Annual) Used\n\n"
            f"{block('get_income_statement', 'annual')}\n\n"
            "## Pre-Fetched Income Statement (Quarterly) Used\n\n"
            f"{block('get_income_statement', 'quarterly')}\n\n"
            "## Pre-Fetched Balance Sheet (Annual) Used\n\n"
            f"{block('get_balance_sheet', 'annual')}\n\n"
            "## Pre-Fetched Balance Sheet (Quarterly) Used\n\n"
            f"{block('get_balance_sheet', 'quarterly')}\n\n"
            "## Pre-Fetched Cash Flow (Annual) Used\n\n"
            f"{block('get_cashflow', 'annual')}\n\n"
            "## Pre-Fetched Cash Flow (Quarterly) Used\n\n"
            f"{block('get_cashflow', 'quarterly')}\n\n"
            "## Fundamentals Analyst Report\n\n"
            f"{result.content}"
        )

        return {
            # Only the synthesis goes into this analyst's message channel —
            # same reasoning as news_analyst.py, and it matters more here:
            # six statement blocks would otherwise be resent as context.
            "fundamentals_messages": [AIMessage(content=result.content)],
            "fundamentals_report": report,
            # The 5 debate/risk nodes read this instead of the full report.
            "fundamentals_synthesis": result.content,
            "audit_tool_calls": [
                {"name": name, "args": args, "result": value}
                for (name, args, _), value in zip(plan, results)
            ],
        }

    return fundamentals_analyst_node
