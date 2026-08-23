# TradingAgents/graph/propagation.py

from typing import Dict, Any, List, Optional
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    resolve_instrument_identity,
    resolve_ticker_symbol,
)


class Propagator:
    """Handles state initialization and propagation through the graph."""

    def __init__(self, max_recur_limit=100):
        """Initialize with configuration parameters."""
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self,
        company_name: str,
        trade_date: str,
        asset_type: str = "stock",
        past_context: str = "",
        investment_horizon: str | None = None,
    ) -> Dict[str, Any]:
        """Create the initial state for the agent graph."""
        # Resolve a bare ticker (e.g. "RELIANCE") to the suffixed symbol
        # yfinance actually serves (e.g. "RELIANCE.NS") ONCE, here, before
        # company_of_interest is set. Every analyst's deterministic
        # pre-fetch reads company_of_interest verbatim for the whole run and
        # has no way to self-correct on its own — fixing it at this single
        # source point fixes every downstream fetcher at once.
        resolved_ticker = resolve_ticker_symbol(company_name, asset_type)
        identity = resolve_instrument_identity(resolved_ticker)
        return {
            "messages": [("human", company_name)],
            # Every analyst reads its OWN channel now (see AgentState), so
            # each needs the same seed message the shared channel used to
            # provide — an unseeded channel would make the analyst invoke
            # with an empty message list.
            "market_messages": [("human", company_name)],
            "sentiment_messages": [("human", company_name)],
            "news_messages": [("human", company_name)],
            "fundamentals_messages": [("human", company_name)],
            "company_of_interest": resolved_ticker,
            "asset_type": asset_type,
            "instrument_context": build_instrument_context(
                resolved_ticker,
                asset_type,
                identity,
            ),
            "trade_date": str(trade_date),
            "past_context": past_context,
            # Optional user-requested holding-period guidance, consumed only
            # by the Portfolio Manager -- never reaches any analyst's
            # deterministic pre-fetch, so it cannot skew what data is seen.
            "investment_horizon": investment_horizon or "",
            "investment_debate_state": InvestDebateState(
                {
                    "bull_history": "",
                    "bear_history": "",
                    "history": "",
                    "current_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "aggressive_history": "",
                    "conservative_history": "",
                    "neutral_history": "",
                    "history": "",
                    "latest_speaker": "",
                    "current_aggressive_response": "",
                    "current_conservative_response": "",
                    "current_neutral_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "market_report": "",
            "fundamentals_report": "",
            "fundamentals_synthesis": "",
            "sentiment_report": "",
            "news_report": "",
            "news_synthesis": "",
            "audit_tool_calls": [],
        }

    def get_graph_args(self, callbacks: Optional[List] = None) -> Dict[str, Any]:
        """Get arguments for the graph invocation.

        Args:
            callbacks: Optional list of callback handlers for tool execution tracking.
                       Note: LLM callbacks are handled separately via LLM constructor.
        """
        config = {"recursion_limit": self.max_recur_limit}
        if callbacks:
            config["callbacks"] = callbacks
        return {
            "stream_mode": "values",
            "config": config,
        }
