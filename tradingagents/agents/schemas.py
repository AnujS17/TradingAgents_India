"""Pydantic schemas used by agents that produce structured output.

The framework's primary artifact is still prose: each agent's natural-language
reasoning is what users read in the saved markdown reports and what the
downstream agents read as context.  Structured output is layered onto the
three decision-making agents (Research Manager, Trader, Portfolio Manager)
so that:

- Their outputs follow consistent section headers across runs and providers
- Each provider's native structured-output mode is used (json_schema for
  OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic)
- Schema field descriptions become the model's output instructions, freeing
  the prompt body to focus on context and the rating-scale guidance
- A render helper turns the parsed Pydantic instance back into the same
  markdown shape the rest of the system already consumes, so display,
  memory log, and saved reports keep working unchanged
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, create_model, model_validator

# Appended to free-text decision fields (Trader.reasoning, PortfolioDecision.
# executive_summary/investment_thesis) after a recurring, observed failure:
# a reasoning model narrating a revision to its own draft mid-field, e.g.
# "locking in gains from the ~~100% one-year run while retaining two-thirds
# exposure~~ to the genuine monopoly and regulatory tailwinds" -- GFM markdown
# renders that literally as struck-through text in the UI, and even read as
# plain text the sentence is broken (the surviving clause doesn't parse
# without the one it was "replacing"). This is not the model choosing to
# format an edit for the reader; it is internal self-correction leaking into
# a field that is supposed to hold only the final answer.
_FINAL_ANSWER_ONLY = (
    " Write only your final answer, in plain prose. Do not narrate a "
    "revision to your own draft, and do not use markdown strikethrough "
    "(~~text~~) or any similar crossed-out/redlined formatting."
)


# ---------------------------------------------------------------------------
# Shared rating types
# ---------------------------------------------------------------------------


class PortfolioRating(str, Enum):
    """5-tier rating used by the Research Manager and Portfolio Manager."""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    """3-tier transaction direction used by the Trader.

    The Trader's job is to translate the Research Manager's investment plan
    into a concrete transaction proposal: should the desk execute a Buy, a
    Sell, or sit on Hold this round.  Position sizing and the nuanced
    Overweight / Underweight calls happen later at the Portfolio Manager.
    """

    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


# ---------------------------------------------------------------------------
# Research Manager
# ---------------------------------------------------------------------------


class ResearchPlan(BaseModel):
    """Structured investment plan produced by the Research Manager.

    Hand-off to the Trader: the recommendation pins the directional view,
    the rationale captures which side of the bull/bear debate carried the
    argument, and the strategic actions translate that into concrete
    instructions the trader can execute against.
    """

    recommendation: PortfolioRating = Field(
        description=(
            "The investment recommendation. Exactly one of Buy / Overweight / "
            "Hold / Underweight / Sell. Reserve Hold for situations where the "
            "evidence on both sides is genuinely balanced; otherwise commit to "
            "the side with the stronger arguments."
        ),
    )
    rationale: str = Field(
        description=(
            "Conversational summary of the key points from both sides of the "
            "debate, ending with which arguments led to the recommendation. "
            "Speak naturally, as if to a teammate."
        ),
    )
    strategic_actions: str = Field(
        description=(
            "Concrete steps for the trader to implement the recommendation, "
            "including position sizing guidance consistent with the rating."
        ),
    )


def render_research_plan(plan: ResearchPlan) -> str:
    """Render a ResearchPlan to markdown for storage and the trader's prompt context."""
    return "\n".join([
        f"**Recommendation**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Strategic Actions**: {plan.strategic_actions}",
    ])


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------


class TraderProposal(BaseModel):
    """Structured transaction proposal produced by the Trader.

    The trader reads the Research Manager's investment plan and the analyst
    reports, then turns them into a concrete transaction: what action to
    take, the reasoning that justifies it, and the practical levels for
    entry, stop-loss, and sizing.
    """

    action: TraderAction = Field(
        description="The transaction direction. Exactly one of Buy / Hold / Sell.",
    )
    reasoning: str = Field(
        description=(
            "The case for this action, anchored in the analysts' reports and "
            "the research plan. Two to four sentences." + _FINAL_ANSWER_ONLY
        ),
    )
    # These two descriptions ARE the model's only instruction for these
    # fields — trader.py's prompt says nothing about levels at all. The
    # earlier wording ("Optional entry price target in the instrument's quote
    # currency") stated no relationship between them and gave no guidance on
    # when omitting is correct, which produced two malformed pairs across
    # observed runs, in BOTH report styles:
    #   SIEMENS.NS 2026-08-12 fast,     Hold: entry 3700.0, stop 3700.0 (identical)
    #   SIEMENS.NS 2026-08-11 detailed, Hold: entry 3650.0, stop 3736.0 (stop above entry)
    # Both were Holds, where "entry price" has no natural answer and the model
    # back-filled a number from the prose. Saying "Optional" was not enough;
    # it has to say when None is the RIGHT answer.
    #
    # 2026-08-26: the original wording also let the model omit these for a
    # Buy/Sell whenever it "wasn't proposing a specific level" -- meant for
    # genuinely level-less Holds, but a model given a conditional/staged plan
    # (e.g. tranche entries across multiple reference prices) took that as
    # license to leave a real trade's levels blank too, which reads as a
    # missing number on the card rather than a decision. Tightened so the
    # loophole applies to Hold only; a Buy or Sell now has to commit to one
    # concrete level even out of a staged plan.
    #
    # THE BOOK IS LONG-ONLY. There is no shorting anywhere in this codebase,
    # and Sell means "reduce or exit a long", not "open a short" — see the
    # Underweight/Sell wording on PortfolioRating and every observed run
    # ("Reduce SIEMENS.NS into strength near Rs 4,000 ... stop below Rs
    # 3,800"). So the protective stop guards a LONG in every case and belongs
    # BELOW entry for all three actions, including Sell. An earlier version of
    # this rule required stop > entry for Sell, which would have discarded the
    # correct pair entry 3900.0 / stop 3650.0 as malformed.
    entry_price: Optional[float] = Field(
        default=None,
        description=(
            "Entry or execution price target in the instrument's quote "
            "currency — the level at which the action is meant to happen "
            "(the level to buy at, or the level to trim into). REQUIRED "
            "whenever action is Buy or Sell: ground it in a level the "
            "analysts actually discussed (a quoted price, a moving average, "
            "a support/resistance level). If the plan is staged or "
            "conditional, state the level that starts it — e.g. the first "
            "tranche — rather than leaving this null; a range or 'wait for a "
            "pullback' is not a reason to omit it once you have decided to "
            "act. Omit it (null) ONLY when the action is Hold with nothing "
            "being executed. Never invent a number with no basis in the "
            "analysts' reports."
        ),
    )
    stop_loss: Optional[float] = Field(
        default=None,
        description=(
            "Protective stop price in the instrument's quote currency, for "
            "the long position being opened or retained. This book is "
            "long-only, so the stop MUST be strictly BELOW entry_price for "
            "every action — including Sell, where it protects the portion of "
            "the position you are keeping, not the portion you are trimming. "
            "It must never equal entry_price: a stop at the entry is not a "
            "stop. REQUIRED whenever action is Buy, or Sell with any part of "
            "the position retained. Omit it (null) only when action is Hold, "
            "or when action is Sell and the entire position is being closed "
            "— there is nothing left to protect once the position is fully "
            "exited."
        ),
    )
    position_sizing: Optional[str] = Field(
        default=None,
        description="Optional sizing guidance, e.g. '5% of portfolio'.",
    )

    @model_validator(mode="after")
    def _drop_incoherent_levels(self) -> "TraderProposal":
        """Discard an entry/stop pair that contradicts the action.

        Deliberately normalises instead of raising. A ValidationError here
        fails the structured-output parse, which triggers the fallback path
        and costs a SECOND full LLM call — the exact "truncated JSON makes
        runs slower, not faster" trap documented in PERF_HANDOFF.md. Worse,
        printing "Stop Loss: 3700.0" under "Entry Price: 3700.0" is an
        actively harmful number in a trading report: a reader may size a
        position against a stop that offers no protection. Dropping the bad
        value is both cheaper and safer than either raising or emitting it.

        Only the stop is dropped; the entry is left alone, since between the
        two it is the stop whose validity is checkable.

        The rule is the same for all three actions because the book is
        long-only (see the field comments above): the stop always guards a
        long, so it always belongs below the execution level.
        """
        if self.entry_price is None or self.stop_loss is None:
            return self

        if self.stop_loss >= self.entry_price:
            self.stop_loss = None
        return self


def render_trader_proposal(proposal: TraderProposal) -> str:
    """Render a TraderProposal to markdown.

    The trailing ``FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`` line is
    preserved for backward compatibility with the analyst stop-signal text
    and any external code that greps for it.
    """
    parts = [
        f"**Action**: {proposal.action.value}",
        "",
        f"**Reasoning**: {proposal.reasoning}",
    ]
    if proposal.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {proposal.entry_price}"])
    if proposal.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {proposal.stop_loss}"])
    if proposal.position_sizing:
        parts.extend(["", f"**Position Sizing**: {proposal.position_sizing}"])
    parts.extend([
        "",
        f"FINAL TRANSACTION PROPOSAL: **{proposal.action.value.upper()}**",
    ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Portfolio Manager
# ---------------------------------------------------------------------------


class PortfolioDecision(BaseModel):
    """Structured output produced by the Portfolio Manager.

    The model fills every field as part of its primary LLM call; no separate
    extraction pass is required. Field descriptions double as the model's
    output instructions, so the prompt body only needs to convey context and
    the rating-scale guidance.
    """

    rating: PortfolioRating = Field(
        description=(
            "The final position rating. Exactly one of Buy / Overweight / Hold / "
            "Underweight / Sell, picked based on the analysts' debate."
        ),
    )
    executive_summary: str = Field(
        description=(
            "A concise action plan covering entry strategy, position sizing, "
            "key risk levels, and time horizon. Two to four sentences." + _FINAL_ANSWER_ONLY
        ),
    )
    investment_thesis: str = Field(
        description=(
            "Detailed reasoning anchored in specific evidence from the analysts' "
            "debate. If prior lessons are referenced in the prompt context, "
            "incorporate them; otherwise rely solely on the current analysis."
            + _FINAL_ANSWER_ONLY
        ),
    )
    # Which of price_target/entry_price/stop_loss apply is a function of
    # the RATING, not uniform across every non-Hold rating. Overweight and
    # Underweight are tactical adjustments to an EXISTING position, not a
    # fresh full trade, so only the field describing that specific
    # adjustment is meaningful:
    #   Buy / Sell        -- a full trade: entry, stop, AND exit all apply.
    #   Overweight (add)  -- only entry applies (where to add). No fresh
    #                        stop (the risk sits on the core holding this
    #                        is layered onto, not on the add itself), no
    #                        exit (you are growing exposure, not closing
    #                        it).
    #   Underweight (trim)-- only the exit applies (the level to trim
    #                        into). No entry (you already hold it), no
    #                        fresh stop (the position is being reduced,
    #                        not protected).
    #   Hold               -- none apply.
    # api.service._extract_verdict enforces this regardless of what the
    # model produces (belt-and-suspenders, same pattern as its Hold
    # reconciliation), but stating it here means the model is not spending
    # reasoning on a field that will be discarded, and is not implying a
    # decision (a stop on a tactical add) that was never actually made.
    price_target: Optional[float] = Field(
        default=None,
        description=(
            "The exit / take-profit level in the instrument's quote "
            "currency — the price at which this position would be closed "
            "for a win. REQUIRED for Buy, Underweight (the level to trim "
            "INTO), and Sell: give one specific level grounded in the "
            "analysts' reports (a technical level, a valuation-based "
            "target, a prior high). Omit it (null) for Hold (nothing is "
            "being opened or added to) and for Overweight (you are "
            "growing the position, not closing it — there is no exit "
            "level to state yet)."
        ),
    )
    # These two exist because the Portfolio Manager ROUTINELY works out the
    # right levels and then had nowhere to put them. SKYGOLD.NS 2026-08-31:
    # the executive summary said "trim into strength toward the 843-850
    # resistance zone ... hard-stop below the consolidation range near
    # 770-774" -- both correct against a 811.40 close (774.03 is literally
    # the snapshot's Bollinger mid) -- while the card rendered the Trader's
    # entry 5000 / stop 4200 on a stock whose 52-week high is 848, because
    # api.service._extract_verdict had only the Trader's fields to read.
    #
    # The Trader still proposes first and its numbers are still used when
    # these are absent (see _extract_verdict) -- this ADDS the final word,
    # it does not remove the Trader's. Optional on purpose: a PM that has
    # nothing to add leaves them null and nothing changes.
    entry_price: Optional[float] = Field(
        default=None,
        description=(
            "Your own execution level in the instrument's quote currency, "
            "overriding the Trader's if you disagree with it. The Trader "
            "commits to its entry BEFORE the risk debate you have just "
            "read, so it can be stale or unanchored; when your summary "
            "names a level to act at, put that number here. Ground it in "
            "the verified market data the analysts cited (a support or "
            "resistance level, a moving average, a recent high or low) and "
            "keep it in the same ballpark as the last traded price. "
            "REQUIRED for Buy, Overweight (the level to ADD at) and Sell. "
            "Omit (null) for Hold and for Underweight — you already hold "
            "the position being trimmed, so there is nothing to enter."
        ),
    )
    stop_loss: Optional[float] = Field(
        default=None,
        description=(
            "Your own protective stop in the instrument's quote currency, "
            "overriding the Trader's if you disagree with it. This book is "
            "long-only, so it MUST be strictly BELOW entry_price whenever "
            "you supply both — including on a Sell, where it guards the "
            "portion of the position being retained rather than trimmed. "
            "Ground it in a real level (below a support zone, a moving "
            "average, an ATR multiple). REQUIRED for Buy and Sell. Omit "
            "(null) for Hold, for Overweight (an incremental add is not a "
            "fresh risk position with its own stop — the risk sits on the "
            "core holding), and for Underweight (a position being reduced "
            "is not being protected, it is being reduced)."
        ),
    )

    @model_validator(mode="after")
    def _drop_incoherent_levels(self) -> "PortfolioDecision":
        """Same long-only coherence rule TraderProposal enforces, and for
        the same reason: a stop at or above the entry is not a stop, and
        rendering one is worse than rendering nothing because a reader can
        size a position against protection that does not exist. Normalises
        rather than raises -- a ValidationError here would fail the
        structured parse and cost a second full LLM call (see
        TraderProposal._drop_incoherent_levels)."""
        if self.entry_price is not None and self.stop_loss is not None:
            if self.stop_loss >= self.entry_price:
                self.stop_loss = None
        return self
    time_horizon: Optional[str] = Field(
        default=None,
        description="Optional recommended holding period, e.g. '3-6 months'.",
    )


def render_pm_decision(decision: PortfolioDecision) -> str:
    """Render a PortfolioDecision back to the markdown shape the rest of the system expects.

    Memory log, CLI display, and saved report files all read this markdown,
    so the rendered output preserves the exact section headers (``**Rating**``,
    ``**Executive Summary**``, ``**Investment Thesis**``) that downstream
    parsers and the report writers already handle.
    """
    parts = [
        f"**Rating**: {decision.rating.value}",
        "",
        f"**Executive Summary**: {decision.executive_summary}",
        "",
        f"**Investment Thesis**: {decision.investment_thesis}",
    ]
    if decision.price_target is not None:
        parts.extend(["", f"**Price Target**: {decision.price_target}"])
    # Distinct labels from the Trader's own "**Entry Price**"/"**Stop Loss**"
    # so api.service._field can tell the two apart when both are present --
    # it matches on a line-leading bold label, and reusing the Trader's
    # wording here would make the PM's markdown indistinguishable.
    if decision.entry_price is not None:
        parts.extend(["", f"**PM Entry Price**: {decision.entry_price}"])
    if decision.stop_loss is not None:
        parts.extend(["", f"**PM Stop Loss**: {decision.stop_loss}"])
    if decision.time_horizon:
        parts.extend(["", f"**Time Horizon**: {decision.time_horizon}"])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Sentiment Analyst
# ---------------------------------------------------------------------------


class SentimentBand(str, Enum):
    """Discrete sentiment direction produced by the Sentiment Analyst.

    Six tiers keep the signal granular enough to be actionable while remaining
    small enough for every provider to map reliably from its JSON output.
    """

    BULLISH = "Bullish"
    MILDLY_BULLISH = "Mildly Bullish"
    NEUTRAL = "Neutral"
    MIXED = "Mixed"
    MILDLY_BEARISH = "Mildly Bearish"
    BEARISH = "Bearish"


class SentimentReport(BaseModel):
    """Structured sentiment report produced by the Sentiment Analyst.

    Replaces the previous free-form prose output so downstream consumers
    (dashboards, audit logs, PDF renderers, other agents) can read
    ``overall_band`` and ``overall_score`` without maintaining fragile regex
    fallbacks that drift with every model release. ``narrative`` preserves the
    rich source-by-source analysis; ``render_sentiment_report`` prepends a
    deterministic header so the saved report stays human-readable.
    """

    overall_band: SentimentBand = Field(
        description=(
            "Overall sentiment direction. Exactly one of: "
            "Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish. "
            "Use Mixed when sources point in clearly different directions. "
            "Use Neutral only when all sources are genuinely silent or non-committal."
        ),
    )
    overall_score: float = Field(
        ge=0.0,
        le=10.0,
        description=(
            "Numeric sentiment intensity on a 0–10 scale. "
            "0 = maximally bearish, 5 = neutral, 10 = maximally bullish. "
            "Guideline for consistency with overall_band: "
            "Bullish ~6.5–10, Mildly Bullish ~5.5–6.4, Neutral/Mixed ~4.5–5.5, "
            "Mildly Bearish ~3.5–4.4, Bearish ~0–3.4. "
            "Only the 0–10 bounds are enforced."
        ),
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description=(
            "Confidence in the assessment based on data quality and sample size. "
            "Use 'low' when one or more sources returned a placeholder or fewer "
            "than 5 data points; 'medium' when data is present but sparse; "
            "'high' when all three sources returned substantive data."
        ),
    )
    narrative: str = Field(
        description=(
            "Full sentiment report covering, in order: "
            "(1) source-by-source breakdown with specific evidence (cite message "
            "counts, ratios, notable posts); "
            "(2) cross-source divergences and alignments; "
            "(3) dominant narrative themes; "
            "(4) catalysts and risks surfaced by the data; "
            "(5) a markdown table summarising key sentiment signals, their "
            "direction, source, and supporting evidence."
        ),
    )


def concise_variant(model: type[BaseModel], overrides: dict[str, str]) -> type[BaseModel]:
    """Return a copy of ``model`` with some field descriptions replaced.

    For structured-output agents the field descriptions ARE the model's
    output instructions — langchain sends the JSON schema, so a schema that
    says "Full sentiment report covering, in order: (1)...(5) a markdown
    table" produces a long report no matter how concise the surrounding
    prompt asks it to be. Trimming only the prompt (as an earlier pass did)
    left these agents unchanged, which is why sentiment/manager/trader/PM
    output did not shrink. Rebuilding the model with shorter descriptions is
    what actually reaches the API.

    Field types, validators and constraints are preserved exactly; only the
    human-readable description text differs, so the parsed result is
    identical in shape and every downstream renderer keeps working.
    """
    rebuilt = create_model(f"Concise{model.__name__}", __base__=model)
    for name, description in overrides.items():
        if name not in rebuilt.model_fields:
            raise KeyError(f"{model.__name__} has no field {name!r} to override")
        # deepcopy first: create_model(__base__=...) leaves the subclass's
        # model_fields pointing at the SAME FieldInfo objects as the parent,
        # so mutating in place would rewrite the original schema too and the
        # "detailed" path would silently inherit the concise descriptions.
        field = copy.deepcopy(rebuilt.model_fields[name])
        field.description = description
        rebuilt.model_fields[name] = field
    rebuilt.model_rebuild(force=True)
    return rebuilt


CONCISE_SENTIMENT_OVERRIDES = {
    "narrative": (
        "SHORT sentiment read, 150 words MAXIMUM. One line per source that "
        "actually has data (skip silent sources entirely), then one line on "
        "any real cross-source divergence. No markdown table. No catalyst or "
        "risk section. Prose only, no headings."
    ),
}

CONCISE_RESEARCH_PLAN_OVERRIDES = {
    "rationale": (
        "80 words MAXIMUM. The single strongest argument from each side, then "
        "which one won and why. No preamble."
    ),
    "strategic_actions": (
        "60 words MAXIMUM. Concrete steps only — entry approach and position "
        "sizing. No hedging language, no restating the rationale."
    ),
}

# Note: TraderProposal.reasoning and PortfolioDecision.executive_summary
# already carried "Two to four sentences" limits, so these overrides are a
# modest tightening (~50 words) rather than the large win the uncapped
# fields below give. Kept for consistency of the concise profile, not
# because they were the problem.
CONCISE_TRADER_OVERRIDES = {
    "reasoning": (
        "50 words MAXIMUM. The evidence that decided it. No restating reports."
        + _FINAL_ANSWER_ONLY
    ),
}

CONCISE_PORTFOLIO_OVERRIDES = {
    "executive_summary": (
        "50 words MAXIMUM. The action, the level, the risk bound. Nothing else."
        + _FINAL_ANSWER_ONLY
    ),
    "investment_thesis": (
        "120 words MAXIMUM. The decisive evidence and the main counter-argument "
        "you are accepting the risk of. Do not re-summarise every analyst; "
        "cite only what changed the decision."
        + _FINAL_ANSWER_ONLY
    ),
}


def render_sentiment_report(report: SentimentReport) -> str:
    """Render a SentimentReport to the markdown shape the rest of the system expects.

    The structured header (band + score + confidence) is prepended to the
    narrative so the saved report is both human-readable and machine-parseable
    without regex.
    """
    return "\n".join([
        f"**Overall Sentiment:** **{report.overall_band.value}** "
        f"(Score: {report.overall_score:.1f}/10)",
        f"**Confidence:** {report.confidence.capitalize()}",
        "",
        report.narrative,
    ])
