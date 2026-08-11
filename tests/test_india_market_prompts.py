from tradingagents.agents.utils.agent_utils import get_india_market_instruction


def test_india_market_prompt_scopes_are_compact_and_specific():
    scopes = [
        "market",
        "fundamentals",
        "news",
        "bull",
        "bear",
        "trader",
        "sentiment",
        "aggressive_risk",
        "conservative_risk",
        "neutral_risk",
    ]

    for scope in scopes:
        instruction = get_india_market_instruction(scope)

        assert instruction.startswith(" India-market lens:")
        assert len(instruction.split()) <= 35


def test_india_market_prompts_cover_core_india_risks():
    text = " ".join(
        get_india_market_instruction(scope).lower()
        for scope in ["fundamentals", "news", "bear", "trader"]
    )

    assert "rbi" in text
    assert "fii" in text
    assert "promoter" in text
    assert "inr" in text
    assert "valuation" in text


def test_risk_debate_trio_and_sentiment_have_distinct_india_lenses():
    scopes = ["sentiment", "aggressive_risk", "conservative_risk", "neutral_risk"]
    instructions = [get_india_market_instruction(scope) for scope in scopes]

    # Each scope must resolve to its own instruction, not silently fall back
    # to the generic "fundamentals" default (get_india_market_instruction's
    # behavior for an unrecognized scope string).
    assert len(set(instructions)) == len(scopes)
    for instruction in instructions:
        assert instruction != get_india_market_instruction("unknown-scope")
