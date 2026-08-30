"""Guard for api.service's verdict parser.

The graph does not keep the parsed pydantic objects — the trader and portfolio
nodes render ``TraderProposal``/``PortfolioDecision`` to markdown and only the
string reaches state. So the API recovers the structured verdict by parsing
that markdown, which is reverse-engineering our own output and would rot
silently the moment a renderer changed.

These tests round-trip REAL schema instances through renderer -> parser, so a
renderer change fails here immediately instead of quietly producing empty
verdicts in production.
"""

import pandas as pd
import pytest

from api.service import _extract_verdict
from tradingagents.agents.schemas import (
    PortfolioDecision,
    PortfolioRating,
    TraderAction,
    TraderProposal,
    render_pm_decision,
    render_trader_proposal,
)


def _state(proposal=None, decision=None, ticker=None, trade_date=None) -> dict:
    state = {
        "trader_investment_plan": render_trader_proposal(proposal) if proposal else "",
        "final_trade_decision": render_pm_decision(decision) if decision else "",
    }
    if ticker is not None:
        state["company_of_interest"] = ticker
    if trade_date is not None:
        state["trade_date"] = trade_date
    return state


@pytest.mark.unit
def test_round_trips_a_full_trader_proposal():
    proposal = TraderProposal(
        action=TraderAction.SELL,
        reasoning="Trim into strength.",
        entry_price=3970.0,
        stop_loss=3650.0,
        position_sizing="Trim 25-40% of the position.",
    )

    verdict = _extract_verdict(_state(proposal=proposal))

    assert verdict.levels.action == "Sell"
    assert verdict.levels.entry_price == 3970.0
    assert verdict.levels.stop_loss == 3650.0
    assert verdict.levels.position_sizing == "Trim 25-40% of the position."


@pytest.mark.unit
def test_round_trips_a_full_portfolio_decision():
    decision = PortfolioDecision(
        rating=PortfolioRating.UNDERWEIGHT,
        executive_summary="Reduce into strength.",
        investment_thesis="Earnings quality is deteriorating at ~59x forward.",
        price_target=3200.0,
        time_horizon="1-2 quarters",
    )

    verdict = _extract_verdict(_state(decision=decision))

    assert verdict.rating == "Underweight"
    assert verdict.price_target == 3200.0
    assert verdict.time_horizon == "1-2 quarters"


@pytest.mark.unit
def test_omitted_levels_come_back_as_none_not_zero():
    """A missing stop is EXPECTED — the trader schema drops one it cannot make
    coherent. It must not surface as 0.0, which would read as a real level and
    could be sized against."""
    proposal = TraderProposal(
        action=TraderAction.HOLD,
        reasoning="Evidence is balanced.",
    )

    verdict = _extract_verdict(_state(proposal=proposal))

    assert verdict.levels.action == "Hold"
    assert verdict.levels.entry_price is None
    assert verdict.levels.stop_loss is None


@pytest.mark.unit
def test_a_dropped_incoherent_stop_does_not_reach_the_api():
    """End-to-end on the long-only rule: the schema nulls a stop at or above
    entry, so the wire response must show no stop rather than a bad one."""
    proposal = TraderProposal(
        action=TraderAction.HOLD,
        reasoning="Balanced.",
        entry_price=3700.0,
        stop_loss=3700.0,  # degenerate — validator drops it
    )

    verdict = _extract_verdict(_state(proposal=proposal))

    assert verdict.levels.entry_price == 3700.0
    assert verdict.levels.stop_loss is None


@pytest.mark.unit
def test_empty_state_yields_an_empty_verdict_rather_than_raising():
    """A run that failed mid-way still has to serialise."""
    verdict = _extract_verdict({})

    assert verdict.rating is None
    assert verdict.levels.action is None


@pytest.mark.unit
def test_current_price_is_the_last_close_for_the_resolved_ticker(monkeypatch):
    """current_price comes from real OHLCV data keyed on company_of_interest
    (the resolved symbol, e.g. TORNTPOWER.NS) and trade_date -- not the raw
    ticker a caller might have passed to run_analysis, and not anything the
    model wrote."""
    import tradingagents.dataflows.stockstats_utils as stockstats_utils

    seen = {}

    def fake_load_ohlcv(symbol, curr_date):
        seen["symbol"] = symbol
        seen["curr_date"] = curr_date
        return pd.DataFrame({"Close": [100.0, 105.5]})

    monkeypatch.setattr(stockstats_utils, "load_ohlcv", fake_load_ohlcv)

    verdict = _extract_verdict(_state(ticker="TORNTPOWER.NS", trade_date="2026-08-26"))

    assert verdict.current_price == 105.5
    assert seen == {"symbol": "TORNTPOWER.NS", "curr_date": "2026-08-26"}


@pytest.mark.unit
def test_current_price_is_none_when_state_lacks_ticker_or_date():
    """Never called on a genuinely empty state -- confirms _extract_current_price
    short-circuits rather than calling load_ohlcv with None."""
    verdict = _extract_verdict(_state())

    assert verdict.current_price is None


@pytest.mark.unit
def test_current_price_failure_does_not_break_the_rest_of_the_verdict(monkeypatch):
    """A vendor outage while fetching current_price must not take down a run
    that otherwise completed -- same never-raise contract as the rest of
    _extract_verdict."""
    import tradingagents.dataflows.stockstats_utils as stockstats_utils

    def boom(symbol, curr_date):
        raise RuntimeError("vendor exploded")

    monkeypatch.setattr(stockstats_utils, "load_ohlcv", boom)

    proposal = TraderProposal(action=TraderAction.BUY, reasoning="Momentum confirmed.", entry_price=100.0)
    verdict = _extract_verdict(_state(proposal=proposal, ticker="X.NS", trade_date="2026-08-26"))

    assert verdict.current_price is None
    assert verdict.levels.entry_price == 100.0


@pytest.mark.unit
def test_hold_rating_overrides_a_directional_trader_proposal():
    """Reproduces a real production case (SAIL, 2026-08-29, 6-month horizon):
    the Trader proposed Buy with real entry/stop BEFORE the Portfolio
    Manager ran, and the Portfolio Manager -- reading the full risk debate,
    more context than the Trader had -- landed on Hold. Without
    reconciliation the card showed "Rating: Hold" next to a live Buy setup
    (entry 195.9, stop 170): a real, actionable-looking number pair that
    contradicted the product's own "nothing to size on a Hold" contract.
    The Portfolio Manager's rating is the FINAL word; it must win."""
    proposal = TraderProposal(
        action=TraderAction.BUY,
        reasoning="Technicals confirm a breakout.",
        entry_price=195.9,
        stop_loss=170.0,
        position_sizing="Full position.",
    )
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="Evidence is more balanced than the trader's setup suggests.",
        investment_thesis="Risk debate surfaced a caveat the trader proposal didn't weigh.",
    )

    verdict = _extract_verdict(_state(proposal=proposal, decision=decision))

    assert verdict.rating == "Hold"
    assert verdict.levels.action == "Hold"
    assert verdict.levels.entry_price is None
    assert verdict.levels.stop_loss is None
    assert verdict.levels.position_sizing is None
    assert verdict.price_target is None


@pytest.mark.unit
def test_non_hold_rating_leaves_the_traders_directional_proposal_alone():
    """The reconciliation is scoped to Hold only -- a Buy/Sell/Overweight/
    Underweight rating must not silently strip a real, still-relevant trade
    setup just because this code path now exists."""
    proposal = TraderProposal(
        action=TraderAction.BUY,
        reasoning="Momentum confirmed.",
        entry_price=195.9,
        stop_loss=170.0,
    )
    decision = PortfolioDecision(
        rating=PortfolioRating.OVERWEIGHT,
        executive_summary="Add on strength.",
        investment_thesis="Aligned with the trader's setup.",
        price_target=220.0,
    )

    verdict = _extract_verdict(_state(proposal=proposal, decision=decision))

    assert verdict.rating == "Overweight"
    assert verdict.levels.action == "Buy"
    assert verdict.levels.entry_price == 195.9
    assert verdict.levels.stop_loss == 170.0
    assert verdict.price_target == 220.0


@pytest.mark.unit
def test_prose_containing_the_label_does_not_confuse_the_parser():
    """Only a line that STARTS with the bold label counts, so a rating
    discussed inside the thesis text cannot be mistaken for the field."""
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="We considered **Rating**: Sell before settling here.",
        investment_thesis="Balanced.",
    )

    verdict = _extract_verdict(_state(decision=decision))

    assert verdict.rating == "Hold"
