from tradingagents.agents.utils.agent_utils import (
    get_brevity_instruction,
    get_evidence_precedence_instruction,
    get_instrument_context_from_state,
    get_language_instruction,
    get_india_market_instruction,
)
from tradingagents.agents.utils.prompt_caching import invoke_with_cache_breakpoint


def create_bull_researcher(llm):
    def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        # news_synthesis (compact bullets + bullish/bearish points), not the
        # full news_report (raw source blocks + analysis, ~5-10x larger) —
        # this node re-runs every debate round and used to re-embed the full
        # report on each one.
        news_report = state["news_synthesis"]
        # fundamentals_synthesis, not the full fundamentals_report — same
        # reason as news_synthesis above: the report now carries all six
        # annual+quarterly statement blocks.
        fundamentals_report = state["fundamentals_synthesis"]
        instrument_context = get_instrument_context_from_state(state)
        asset_type = state.get("asset_type", "stock")
        target_label = "stock" if asset_type == "stock" else "asset"
        fundamentals_label = (
            "Company fundamentals report"
            if asset_type == "stock"
            else "Asset fundamentals report (may be unavailable for crypto)"
        )

        # Split for Anthropic prompt-cache breakpointing: static_context (role
        # framing + all 4 reports) is byte-identical across every round of
        # this debate — only dynamic_context (history + opponent's last
        # argument) changes. static_context + dynamic_context concatenated,
        # in that order, reproduces exactly the single prompt string this
        # node used to build.
        static_context = f"""You are a Bull Analyst advocating for investing in the {target_label}. Your task is to build a strong, evidence-based case emphasizing growth potential, competitive advantages, and positive market indicators. Leverage the provided research and data to address concerns and counter bearish arguments effectively.

Key points to focus on:
- Growth Potential: Highlight the company's market opportunities, revenue projections, and scalability.
- Competitive Advantages: Emphasize factors like unique products, strong branding, or dominant market positioning.
- Positive Indicators: Use financial health, industry trends, and recent positive news as evidence.
- India-Market Edge: {get_india_market_instruction("bull").strip()}
- Bear Counterpoints: Critically analyze the bear argument with specific data and sound reasoning, addressing concerns thoroughly and showing why the bull perspective holds stronger merit.
- Engagement: Present your argument in a conversational style, engaging directly with the bear analyst's points and debating effectively rather than just listing data.

Resources available:
{instrument_context}
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
{fundamentals_label}: {fundamentals_report}
"""

        dynamic_context = f"""Conversation history of the debate: {history}
Last bear argument: {current_response}
Use this information to deliver a compelling bull argument, refute the bear's concerns, and engage in a dynamic debate that demonstrates the strengths of the bull position.
""" + get_brevity_instruction(200) + get_evidence_precedence_instruction() + get_language_instruction()

        response = invoke_with_cache_breakpoint(llm, static_context, dynamic_context)

        argument = f"Bull Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bull_node
