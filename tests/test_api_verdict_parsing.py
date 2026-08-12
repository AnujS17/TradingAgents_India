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


def _state(proposal=None, decision=None) -> dict:
    return {
        "trader_investment_plan": render_trader_proposal(proposal) if proposal else "",
        "final_trade_decision": render_pm_decision(decision) if decision else "",
    }


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
