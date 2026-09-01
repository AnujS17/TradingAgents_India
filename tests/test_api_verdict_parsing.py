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
    """Buy and Sell are full trades with nothing rating-specific to null --
    a Buy/Sell rating must not silently strip a real, still-relevant trade
    setup just because the Hold/Overweight/Underweight reconciliation code
    path now exists. (Overweight and Underweight DO selectively null
    fields — see test_overweight_only_keeps_entry and
    test_underweight_only_keeps_exit below; this test is scoped to the
    rating that must NOT be touched.)"""
    proposal = TraderProposal(
        action=TraderAction.BUY,
        reasoning="Momentum confirmed.",
        entry_price=195.9,
        stop_loss=170.0,
    )
    decision = PortfolioDecision(
        rating=PortfolioRating.BUY,
        executive_summary="Strong conviction entry.",
        investment_thesis="Aligned with the trader's setup.",
        price_target=220.0,
    )

    verdict = _extract_verdict(_state(proposal=proposal, decision=decision))

    assert verdict.rating == "Buy"
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


# ---------------------------------------------------------------------------
# Portfolio Manager levels + implausible-level guard
# ---------------------------------------------------------------------------


def _priced_state(proposal, decision, price):
    """A state whose _extract_current_price resolves to `price`."""
    from unittest.mock import patch

    import api.service as service

    state = _state(proposal=proposal, decision=decision)
    return state, patch.object(service, "_extract_current_price", return_value=price)


def _priced_state_with_atr(proposal, decision, price, atr):
    """A state whose _extract_current_price resolves to `price` and
    _extract_atr resolves to `atr`."""
    from unittest.mock import patch

    import api.service as service

    state = _state(proposal=proposal, decision=decision)
    return state, patch.multiple(
        service,
        _extract_current_price=lambda s: price,
        _extract_atr=lambda s: atr,
    )


@pytest.mark.unit
def test_the_portfolio_managers_own_levels_win_over_the_traders():
    """The PM rules last, having read the Trader's proposal AND the full risk
    debate, and routinely works out better levels than the Trader had.
    SKYGOLD.NS 2026-08-31: the PM said "trim toward the 843-850 resistance
    zone ... hard-stop near 770-774" against an 811.40 close while the card
    rendered the Trader's entry 5000 / stop 4200 -- because the PM had
    nowhere structured to put what it had already worked out.

    Rated Sell rather than the real incident's Underweight so this test
    isolates PM-overrides-Trader precedence from the separate
    Overweight/Underweight field-nulling rule (which would null stop_loss
    here regardless of which source proposed it) -- see
    test_underweight_only_keeps_exit for that behaviour on its own."""
    proposal = TraderProposal(
        action=TraderAction.SELL, reasoning="Trim.", entry_price=5000.0, stop_loss=4200.0
    )
    decision = PortfolioDecision(
        rating=PortfolioRating.SELL,
        executive_summary="Exit into resistance.",
        investment_thesis="Cash conversion is structurally weak.",
        price_target=850.0,
        entry_price=846.0,
        stop_loss=772.0,
    )
    state, patched = _priced_state(proposal, decision, 811.40)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.levels.entry_price == 846.0
    assert verdict.levels.stop_loss == 772.0


@pytest.mark.unit
def test_the_traders_levels_are_still_used_when_the_pm_adds_nothing():
    """The PM's fields are optional and additive -- a PM with nothing to
    correct must leave the previous behaviour exactly intact.

    Rated Buy rather than Overweight so this isolates PM-adds-nothing
    pass-through from the separate Overweight/Underweight field-nulling
    rule, which would null stop_loss here regardless of source -- see
    test_overweight_only_keeps_entry for that behaviour on its own."""
    proposal = TraderProposal(
        action=TraderAction.BUY, reasoning="Momentum.", entry_price=3970.0, stop_loss=3800.0
    )
    decision = PortfolioDecision(
        rating=PortfolioRating.BUY,
        executive_summary="Strong conviction entry.",
        investment_thesis="Order book supports it.",
        price_target=4300.0,
    )
    state, patched = _priced_state(proposal, decision, 3943.10)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.levels.entry_price == 3970.0
    assert verdict.levels.stop_loss == 3800.0


@pytest.mark.unit
def test_a_level_that_cannot_belong_to_this_instrument_is_dropped():
    """SKYGOLD.NS 2026-08-31, reproduced: entry 5000 / stop 4200 on a stock
    that closed at 811.40 and whose 52-week high is 848. Both passed the
    schema's own check, which only compares stop to entry and never to the
    market. Dropped rather than clamped -- inventing a corrected number
    would assert a level nobody proposed."""
    proposal = TraderProposal(
        action=TraderAction.SELL, reasoning="Trim.", entry_price=5000.0, stop_loss=4200.0
    )
    decision = PortfolioDecision(
        rating=PortfolioRating.UNDERWEIGHT,
        executive_summary="Trim into strength.",
        investment_thesis="Cash flow is negative three years running.",
        price_target=850.0,
    )
    state, patched = _priced_state(proposal, decision, 811.40)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.levels.entry_price is None
    assert verdict.levels.stop_loss is None
    # The PM's own price target is unaffected -- it was never implausible.
    assert verdict.price_target == 850.0


@pytest.mark.unit
@pytest.mark.parametrize(
    "label,entry,stop,price",
    [
        ("deep pullback entry", 3470.0, 3300.0, 3943.10),
        ("breakout above resistance", 4220.0, 3846.0, 3943.10),
        ("the real luna KAYNES call", 4025.0, 3846.0, 3943.10),
        ("accumulate on a 40% correction", 2400.0, 2200.0, 4000.0),
    ],
)
def test_legitimate_setups_are_never_discarded(label, entry, stop, price):
    """The guard exists to catch a level that cannot belong to the
    instrument at all, NOT to opine on whether a level is well chosen. The
    band is deliberately wide (half to double the last close) so every real
    setup -- deep pullback, breakout, distant support stop -- survives."""
    proposal = TraderProposal(
        action=TraderAction.BUY, reasoning=label, entry_price=entry, stop_loss=stop
    )
    state, patched = _priced_state(proposal, None, price)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.levels.entry_price == entry, label
    assert verdict.levels.stop_loss == stop, label


@pytest.mark.unit
def test_a_stop_is_dropped_when_its_entry_was_implausible():
    """A stop only means something against an entry. If the entry was the
    implausible one, a surviving stop is orphaned rather than useful."""
    proposal = TraderProposal(
        action=TraderAction.BUY, reasoning="x", entry_price=9000.0, stop_loss=800.0
    )
    state, patched = _priced_state(proposal, None, 811.40)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.levels.entry_price is None
    assert verdict.levels.stop_loss is None


@pytest.mark.unit
def test_the_guard_is_inert_when_no_current_price_could_be_resolved():
    """_extract_current_price returns None on a vendor outage or an asset
    with no OHLCV concept. With no reference price there is nothing to
    judge against, so levels must pass through untouched rather than be
    discarded on a data failure."""
    proposal = TraderProposal(
        action=TraderAction.BUY, reasoning="x", entry_price=5000.0, stop_loss=4200.0
    )
    state, patched = _priced_state(proposal, None, None)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.levels.entry_price == 5000.0
    assert verdict.levels.stop_loss == 4200.0


@pytest.mark.unit
def test_a_hold_still_clears_pm_supplied_levels():
    """The Hold reconciliation must apply to the PM's own fields too, not
    just the Trader's -- otherwise the new fields reopen the exact conflict
    e950022 closed: 'Rating: Hold' beside a live, sizeable setup."""
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="Balanced.",
        investment_thesis="Evidence cuts both ways.",
        entry_price=846.0,
        stop_loss=772.0,
    )
    state, patched = _priced_state(
        TraderProposal(action=TraderAction.BUY, reasoning="x", entry_price=800.0, stop_loss=760.0),
        decision,
        811.40,
    )
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.rating == "Hold"
    assert verdict.levels.entry_price is None
    assert verdict.levels.stop_loss is None
    assert verdict.price_target is None


# ---------------------------------------------------------------------------
# ATR-aware minimum stop distance
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_stop_far_closer_than_ordinary_noise_is_dropped():
    """SKYGOLD.NS 2026-08-31 (one run before the one that got it right):
    entry 777 / stop 765, a 12-point gap against that day's real ATR of
    33.69 -- 0.36 ATR, well inside a single session's ordinary noise. It
    passed the schema's own stop<entry check and the implausible-level
    guard (both in the right ballpark), and still was not a functioning
    stop."""
    proposal = TraderProposal(
        action=TraderAction.BUY, reasoning="x", entry_price=777.0, stop_loss=765.0
    )
    state, patched = _priced_state_with_atr(proposal, None, 811.40, 33.69)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.levels.entry_price == 777.0
    assert verdict.levels.stop_loss is None


@pytest.mark.unit
def test_a_stop_at_a_sensible_atr_distance_survives():
    """The very next SKYGOLD.NS run, same ticker and ATR: entry 774 / stop
    740 is a 34-point gap -- essentially 1.0x ATR -- and must be kept
    exactly as proposed."""
    proposal = TraderProposal(
        action=TraderAction.BUY, reasoning="x", entry_price=774.0, stop_loss=740.0
    )
    state, patched = _priced_state_with_atr(proposal, None, 811.40, 33.69)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.levels.entry_price == 774.0
    assert verdict.levels.stop_loss == 740.0


@pytest.mark.unit
def test_a_stop_exactly_at_the_floor_is_kept():
    """The guard is a floor, not a target -- a stop AT 0.5x ATR (not under
    it) must survive. ATR 40.0 -> floor is 20.0; a 20-point gap must pass.
    Stop kept below entry throughout: this book is long-only, so a Sell's
    stop still protects the retained portion of the position (see
    TraderProposal's own long-only stop<entry rule) -- a stop ABOVE entry
    would be dropped by that validator before this guard ever runs."""
    proposal = TraderProposal(
        action=TraderAction.SELL, reasoning="x", entry_price=1020.0, stop_loss=1000.0
    )
    state, patched = _priced_state_with_atr(proposal, None, 1020.0, 40.0)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.levels.stop_loss == 1000.0


@pytest.mark.unit
def test_the_guard_is_inert_with_no_atr_available():
    """A young listing whose ATR is not computable (see
    market_data_validator._MIN_PERIODS), or any vendor failure, must not
    silently discard a stop it has no basis to judge -- _extract_atr
    returning None means "cannot judge", not "reject"."""
    proposal = TraderProposal(
        action=TraderAction.BUY, reasoning="x", entry_price=777.0, stop_loss=765.0
    )
    state, patched = _priced_state_with_atr(proposal, None, 811.40, None)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.levels.stop_loss == 765.0


@pytest.mark.unit
def test_a_tight_stop_on_a_low_volatility_stock_is_not_penalised():
    """The guard scales with the instrument's OWN volatility, not an
    absolute point distance -- the same 12-point gap that fails on
    SKYGOLD's 33.69 ATR is a legitimate ~2.4x ATR stop on a much quieter
    5.0-ATR stock, and must be kept."""
    proposal = TraderProposal(
        action=TraderAction.BUY, reasoning="x", entry_price=777.0, stop_loss=765.0
    )
    state, patched = _priced_state_with_atr(proposal, None, 811.40, 5.0)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.levels.stop_loss == 765.0


@pytest.mark.unit
def test_only_the_stop_is_dropped_never_the_entry():
    """A too-tight stop says nothing about whether the entry level itself
    was well chosen -- entry must survive even when its stop does not."""
    proposal = TraderProposal(
        action=TraderAction.BUY, reasoning="x", entry_price=774.0, stop_loss=773.0
    )
    state, patched = _priced_state_with_atr(proposal, None, 811.40, 33.69)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.levels.entry_price == 774.0
    assert verdict.levels.stop_loss is None


# ---------------------------------------------------------------------------
# Rating-scoped field applicability: Overweight (add) / Underweight (trim)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_overweight_only_keeps_entry():
    """Overweight is a tactical ADD to an existing/core position, not a
    fresh full trade: entry (where to add) is the only level that means
    anything. stop_loss and price_target must be nulled even when both
    were proposed, because there is no new position to protect and no
    exit being defined -- you are growing exposure, not closing it."""
    proposal = TraderProposal(
        action=TraderAction.BUY, reasoning="x", entry_price=777.0, stop_loss=740.0
    )
    decision = PortfolioDecision(
        rating=PortfolioRating.OVERWEIGHT,
        executive_summary="Add gradually.",
        investment_thesis="Structural growth intact.",
        price_target=884.0,
    )
    state, patched = _priced_state(proposal, decision, 811.40)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.rating == "Overweight"
    assert verdict.levels.entry_price == 777.0
    assert verdict.levels.stop_loss is None
    assert verdict.price_target is None


@pytest.mark.unit
def test_underweight_only_keeps_exit():
    """Underweight is a TRIM of an existing position, not a fresh trade:
    exit (where to trim into) is the only level that means anything.
    entry_price and stop_loss must be nulled -- there is nothing to enter
    (you already hold it) and the position being reduced is being reduced,
    not protected."""
    proposal = TraderProposal(
        action=TraderAction.SELL, reasoning="x", entry_price=850.0, stop_loss=780.0
    )
    decision = PortfolioDecision(
        rating=PortfolioRating.UNDERWEIGHT,
        executive_summary="Trim into strength.",
        investment_thesis="Valuation has run ahead of fundamentals.",
        price_target=843.0,
    )
    state, patched = _priced_state(proposal, decision, 811.40)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.rating == "Underweight"
    assert verdict.levels.entry_price is None
    assert verdict.levels.stop_loss is None
    assert verdict.price_target == 843.0


@pytest.mark.unit
def test_overweight_nulls_the_pms_own_stop_and_target_too():
    """The rating-scoped nulling must apply after the PM's own
    entry_price/stop_loss override, not just to whatever the Trader
    proposed -- a PM that (incorrectly) supplies its own stop/target on an
    Overweight must still have them nulled on the card."""
    decision = PortfolioDecision(
        rating=PortfolioRating.OVERWEIGHT,
        executive_summary="Add gradually.",
        investment_thesis="Structural growth intact.",
        price_target=884.0,
        entry_price=777.0,
        stop_loss=740.0,
    )
    state, patched = _priced_state(None, decision, 811.40)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.levels.entry_price == 777.0
    assert verdict.levels.stop_loss is None
    assert verdict.price_target is None


@pytest.mark.unit
def test_buy_and_sell_keep_every_level_unlike_overweight_and_underweight():
    """Parametrised-in-spirit confirmation that the new nulling is scoped
    to exactly Overweight/Underweight/Hold, not "every rating that isn't
    Buy" -- Sell is just as much a full trade as Buy and must keep all
    three fields."""
    # Long-only book: stop must be strictly BELOW entry even on a Sell (it
    # protects the portion of the position being retained, not trimmed) --
    # sell into strength above spot, stop below that entry.
    proposal = TraderProposal(
        action=TraderAction.SELL, reasoning="x", entry_price=1360.0, stop_loss=1330.0
    )
    decision = PortfolioDecision(
        rating=PortfolioRating.SELL,
        executive_summary="Exit the position.",
        investment_thesis="Thesis has broken down.",
        price_target=1200.0,
    )
    state, patched = _priced_state(proposal, decision, 1323.25)
    with patched:
        verdict = _extract_verdict(state)

    assert verdict.rating == "Sell"
    assert verdict.levels.entry_price == 1360.0
    assert verdict.levels.stop_loss == 1330.0
    assert verdict.price_target == 1200.0
