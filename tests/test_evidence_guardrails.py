from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.unit
def test_fundamentals_prompt_requires_evidence_and_currency_discipline():
    text = (ROOT / "tradingagents/agents/analysts/fundamentals_analyst.py").read_text(
        encoding="utf-8"
    )

    assert "Provide specific, actionable insights with supporting evidence" in text
    assert "Use the available tools" in text
    assert "get_fundamentals" in text
    assert "get_balance_sheet" in text
    assert "get_cashflow" in text
    assert "get_income_statement" in text
    assert "get_india_market_instruction(\"fundamentals\")" in text
    assert "get_language_instruction()," not in text


@pytest.mark.unit
def test_market_prompt_requires_fetched_indicator_evidence():
    text = (ROOT / "tradingagents/agents/analysts/market_analyst.py").read_text(
        encoding="utf-8"
    )

    assert "Treat the snapshot as the source of truth" in text
    assert "exact OHLCV, price-level, or indicator-value claim" in text
    assert "flag the discrepancy rather than inventing" in text
    assert "directly supported by tool output with concrete dates and prices" in text
    assert "get_verified_market_snapshot" in text
    assert "get_india_market_instruction(\"market\")" in text


@pytest.mark.unit
def test_stocktwits_prompt_and_fetcher_keep_unlabeled_denominator_visible():
    sentiment_text = (
        ROOT / "tradingagents/agents/analysts/sentiment_analyst.py"
    ).read_text(encoding="utf-8")
    fetcher_text = (ROOT / "tradingagents/dataflows/stocktwits.py").read_text(
        encoding="utf-8"
    )

    assert "base rates on the actual message count" in sentiment_text
    assert "Be honest about data limits" in sentiment_text
    assert "no-label" in fetcher_text
    assert "Unlabeled:" in fetcher_text
    assert "Total:" in fetcher_text


@pytest.mark.unit
def test_trader_omits_unsupported_indicator_derived_levels():
    text = (ROOT / "tradingagents/agents/trader/trader.py").read_text(
        encoding="utf-8"
    )
    schema_text = (ROOT / "tradingagents/agents/schemas.py").read_text(
        encoding="utf-8"
    )

    assert "Anchor your reasoning in the analysts' reports and the research plan" in text
    assert "get_india_market_instruction(\"trader\")" in text
    assert "anchored in the analysts' reports" in schema_text
    assert "the research plan" in schema_text
    assert "Optional entry price target" in schema_text
    assert "Optional stop-loss price" in schema_text


@pytest.mark.unit
def test_news_prompt_forbids_plausible_company_headlines_without_tool_evidence():
    text = (ROOT / "tradingagents/agents/analysts/news_analyst.py").read_text(
        encoding="utf-8"
    )

    assert "Pre-fetched news data is provided below" in text
    assert "ground your report only in it" in text
    assert "Do not call or imply additional news tools were used" in text
    assert "<prefetched_company_news>" in text
    assert "<prefetched_global_news>" in text
    assert "audit_tool_calls" in text
    assert "get_india_market_instruction(\"news\")" in text


@pytest.mark.unit
@pytest.mark.parametrize(
    "relative_path",
    [
        "tradingagents/agents/researchers/bull_researcher.py",
        "tradingagents/agents/researchers/bear_researcher.py",
        "tradingagents/agents/risk_mgmt/aggressive_debator.py",
        "tradingagents/agents/risk_mgmt/conservative_debator.py",
        "tradingagents/agents/risk_mgmt/neutral_debator.py",
        "tradingagents/agents/managers/research_manager.py",
        "tradingagents/agents/managers/portfolio_manager.py",
        "tradingagents/agents/trader/trader.py",
    ],
)
def test_downstream_prompts_do_not_amplify_unsupported_claims(relative_path):
    text = (ROOT / relative_path).read_text(encoding="utf-8")

    lowered = text.lower()
    assert any(
        phrase in lowered
        for phrase in [
            "specific data",
            "available data",
            "specific evidence",
            "provided research",
            "analysts' reports",
            "analysts' debate",
            "data-driven",
            "evidence on both sides",
        ]
    )
