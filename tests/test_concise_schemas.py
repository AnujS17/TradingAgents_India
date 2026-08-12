"""concise_variant — shortening the STRUCTURED agents' output.

For the four structured-output agents (Sentiment, Research Manager, Trader,
Portfolio Manager) langchain sends the pydantic JSON schema to the provider,
and the field descriptions ARE the output instructions. An earlier pass
trimmed only the prompt text, which left these agents' schemas still asking
for e.g. "Full sentiment report covering, in order: (1)...(5) a markdown
table" — so their output did not shrink at all. concise_variant rebuilds the
model with shorter descriptions, which is what actually reaches the API.

The dangerous part is mutation: create_model(__base__=...) leaves the
subclass sharing FieldInfo objects with the parent, so a naive in-place edit
would rewrite the ORIGINAL schema too and silently make the default
"detailed" path concise as well.
"""

import re

import pytest

from tradingagents.agents.schemas import (
    CONCISE_PORTFOLIO_OVERRIDES,
    CONCISE_RESEARCH_PLAN_OVERRIDES,
    CONCISE_SENTIMENT_OVERRIDES,
    CONCISE_TRADER_OVERRIDES,
    PortfolioDecision,
    ResearchPlan,
    SentimentReport,
    TraderAction,
    TraderProposal,
    concise_variant,
    render_trader_proposal,
)

CASES = [
    (SentimentReport, CONCISE_SENTIMENT_OVERRIDES),
    (ResearchPlan, CONCISE_RESEARCH_PLAN_OVERRIDES),
    (TraderProposal, CONCISE_TRADER_OVERRIDES),
    (PortfolioDecision, CONCISE_PORTFOLIO_OVERRIDES),
]


@pytest.mark.unit
@pytest.mark.parametrize("model,overrides", CASES)
def test_concise_variant_does_not_mutate_the_original_schema(model, overrides):
    before = {name: model.model_fields[name].description for name in overrides}

    concise_variant(model, overrides)

    after = {name: model.model_fields[name].description for name in overrides}
    assert before == after, (
        f"{model.__name__} was mutated in place — the detailed path would "
        "silently inherit the concise descriptions"
    )


@pytest.mark.unit
@pytest.mark.parametrize("model,overrides", CASES)
def test_concise_variant_applies_every_override(model, overrides):
    variant = concise_variant(model, overrides)

    for name, description in overrides.items():
        assert variant.model_fields[name].description == description


@pytest.mark.unit
@pytest.mark.parametrize("model,overrides", CASES)
def test_concise_variant_keeps_all_fields_and_types(model, overrides):
    variant = concise_variant(model, overrides)

    assert set(variant.model_fields) == set(model.model_fields)
    for name, info in model.model_fields.items():
        assert variant.model_fields[name].annotation == info.annotation


@pytest.mark.unit
def test_concise_variant_preserves_numeric_constraints():
    # overall_score has ge=0/le=10. Losing those in the rebuild would let an
    # out-of-range score through and break the downstream renderer's
    # band/score consistency.
    variant = concise_variant(SentimentReport, CONCISE_SENTIMENT_OVERRIDES)

    variant(overall_band="Bullish", overall_score=7.0, confidence="high", narrative="ok")
    with pytest.raises(Exception):
        variant(overall_band="Bullish", overall_score=99.0, confidence="high", narrative="ok")


@pytest.mark.unit
def test_concise_variant_output_still_renders():
    # The whole point is that only the description text changes, so every
    # existing render_* helper must keep working on the parsed result.
    from tradingagents.agents.schemas import render_sentiment_report

    variant = concise_variant(SentimentReport, CONCISE_SENTIMENT_OVERRIDES)
    instance = variant(
        overall_band="Mildly Bullish", overall_score=6.0, confidence="medium", narrative="Short read."
    )

    rendered = render_sentiment_report(instance)
    assert "Mildly Bullish" in rendered
    assert "Short read." in rendered


@pytest.mark.unit
def test_unknown_field_name_raises_rather_than_silently_doing_nothing():
    # A typo'd override would otherwise be a no-op, and the agent would keep
    # emitting long output with no indication why.
    with pytest.raises(KeyError):
        concise_variant(SentimentReport, {"nonexistent_field": "..."})


@pytest.mark.unit
@pytest.mark.parametrize("model,overrides", CASES)
def test_every_concise_override_states_an_explicit_numeric_word_cap(model, overrides):
    # The property that actually matters is the requested OUTPUT length, not
    # the length of the instruction string — an earlier version of this test
    # compared description lengths and wrongly flagged TraderProposal, whose
    # original description was already short ("Two to four sentences") while
    # its replacement text happened to be a few characters longer. What makes
    # these overrides effective is that each names a hard number, since models
    # reliably ignore qualitative words like "concise".
    for name, description in overrides.items():
        assert re.search(r"\d+\s+words\s+MAXIMUM", description), (
            f"{model.__name__}.{name} override has no explicit numeric word cap"
        )


# --- TraderProposal entry/stop coherence -----------------------------------
#
# Two malformed pairs were observed in real runs, in BOTH report styles, so
# this is not a concise-mode defect: the field descriptions are the model's
# only instruction here (trader.py's prompt never mentions levels), and they
# stated no relationship between the two fields.
#
# The book is long-only, so the stop always guards a long and always belongs
# BELOW entry — including on Sell, which trims a long rather than opening a
# short.


@pytest.mark.unit
def test_trader_stop_equal_to_entry_is_dropped():
    """SIEMENS.NS 2026-08-12 fast run: entry 3700.0 with stop 3700.0.

    A stop at the entry offers no protection, and printing it in a trading
    report invites sizing against protection that does not exist.
    """
    proposal = TraderProposal(
        action=TraderAction.HOLD,
        reasoning="Balanced evidence.",
        entry_price=3700.0,
        stop_loss=3700.0,
    )

    assert proposal.stop_loss is None
    assert proposal.entry_price == 3700.0
    assert "Stop Loss" not in render_trader_proposal(proposal)


@pytest.mark.unit
def test_trader_stop_above_entry_is_dropped_for_a_buy():
    proposal = TraderProposal(
        action=TraderAction.BUY,
        reasoning="Accumulate.",
        entry_price=3650.0,
        stop_loss=3736.0,
    )

    assert proposal.stop_loss is None


@pytest.mark.unit
def test_trader_stop_below_entry_is_KEPT_for_a_sell():
    """SIEMENS.NS 2026-08-12 fast run: Sell with entry 3900, stop 3650.

    This pair is CORRECT and must survive. The book is long-only — Sell means
    trim a long, so the stop guards the retained long and belongs below the
    trim level. The portfolio decision for that same run says it in prose:
    "Reduce SIEMENS.NS into strength near Rs 4,000 ... stop below Rs 3,800".
    An earlier version of this validator required stop > entry for Sell and
    would have thrown this away.
    """
    proposal = TraderProposal(
        action=TraderAction.SELL,
        reasoning="Trim into strength.",
        entry_price=3900.0,
        stop_loss=3650.0,
    )

    assert proposal.stop_loss == 3650.0


@pytest.mark.unit
@pytest.mark.parametrize(
    "action,entry,stop",
    [
        (TraderAction.BUY, 393.0, 374.0),      # LICI.NS
        (TraderAction.SELL, 3900.0, 3650.0),   # SIEMENS.NS — trim a long
        (TraderAction.HOLD, 731.0, 714.83),    # HDFCBANK.NS
    ],
)
def test_trader_keeps_coherent_levels(action, entry, stop):
    """Valid pairs from real runs must survive untouched."""
    proposal = TraderProposal(
        action=action, reasoning="ok", entry_price=entry, stop_loss=stop
    )

    assert proposal.stop_loss == stop
    assert proposal.entry_price == entry
    assert f"**Stop Loss**: {stop}" in render_trader_proposal(proposal)


@pytest.mark.unit
def test_trader_omitting_both_levels_is_allowed():
    """A Hold with no new money in is the case the descriptions now name
    explicitly — it must not be forced to invent numbers."""
    proposal = TraderProposal(action=TraderAction.HOLD, reasoning="Sit tight.")

    assert proposal.entry_price is None
    assert proposal.stop_loss is None
    rendered = render_trader_proposal(proposal)
    assert "Entry Price" not in rendered
    assert "Stop Loss" not in rendered
    assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in rendered


@pytest.mark.unit
def test_level_descriptions_state_the_relationship_and_when_to_omit():
    """The descriptions ARE the instructions for structured output, and they
    must survive into the concise variant too — this is accuracy discipline,
    not verbosity, so concise_variant must not override these two fields."""
    for model in (TraderProposal, concise_variant(TraderProposal, CONCISE_TRADER_OVERRIDES)):
        stop_desc = model.model_fields["stop_loss"].description
        entry_desc = model.model_fields["entry_price"].description
        assert "strictly BELOW" in stop_desc
        assert "including Sell" in stop_desc
        assert "never equal" in stop_desc
        assert "Omit it (null)" in entry_desc


@pytest.mark.unit
def test_trader_stop_above_entry_is_dropped_for_a_sell():
    """Long-only: a stop above the trim level protects nothing."""
    proposal = TraderProposal(
        action=TraderAction.SELL,
        reasoning="Trim.",
        entry_price=3900.0,
        stop_loss=4100.0,
    )

    assert proposal.stop_loss is None
